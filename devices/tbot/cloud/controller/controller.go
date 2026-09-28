// Package controller reconciles TBot lifecycle with fenced, on-demand ECS tasks.
package controller

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/mparkachov/txing/devices/tbot/cloud/agentstatus"
)

var ErrNotFound = errors.New("resource not found")
var ErrStartRejected = errors.New("ECS rejected task start")
var ErrNotReady = errors.New("task or superseded tasks are still starting or stopping; refresh readiness later")

const (
	StartGrace   = 10 * time.Minute
	RestartDelay = time.Minute
)

type Lifecycle struct {
	Topic struct {
		Namespace   string `json:"namespace"`
		MessageType string `json:"messageType"`
		DeviceID    string `json:"deviceId"`
	} `json:"topic"`
	Payload struct {
		Metrics struct {
			REDCON int `json:"redcon"`
		} `json:"metrics"`
	} `json:"payload"`
}

func (s Lifecycle) Active(thing string) bool {
	return s.Topic.Namespace == "spBv1.0" && s.Topic.DeviceID == thing &&
		(s.Topic.MessageType == "DBIRTH" || s.Topic.MessageType == "DDATA") &&
		(s.Payload.Metrics.REDCON == 1 || s.Payload.Metrics.REDCON == 2)
}

type Task struct {
	ARN, Thing, ID, Status, DesiredStatus, ENI, Reason string
}

func (t Task) Live() bool    { return t.Status != "STOPPED" }
func (t Task) Running() bool { return t.Status == "RUNNING" && t.DesiredStatus == "RUNNING" }

// Cloud implementations must bound retries and pagination and honor ctx.
// Tasks contains only tasks managed by this companion controller.
type Cloud interface {
	Things(context.Context) ([]string, error)
	ThingType(context.Context, string) (string, error)
	Lifecycle(context.Context, string) (Lifecycle, error)
	Store(string) agentstatus.Store
	Tasks(context.Context) ([]Task, error)
	Run(context.Context, string, string) (Task, error)
	Stop(context.Context, Task, string) error
	Addresses(context.Context, Task) (string, string, error)
}

// Readiness is invoked by the assigned task using its AWS task credentials.
// ID is the opaque TXING_AGENT_TASK_ID launch token, not the ECS task ARN.
type Readiness struct {
	ShadowVersion int64  `json:"shadowVersion"`
	ID            string `json:"taskId"`
	TaskARN       string `json:"taskArn"`
	UDPListening  bool   `json:"udpListening"`
	MAVLink       string `json:"mavlink"`
	Video         string `json:"video"`
}

type Event struct {
	Kind      string     `json:"kind"`
	Thing     string     `json:"thingName"`
	Readiness *Readiness `json:"readiness,omitempty"`
}

type Controller struct {
	Cloud Cloud
	Log   *slog.Logger
	Now   func() time.Time
	NewID func(time.Time) (string, error)
	mu    sync.Mutex
}

func New(cloud Cloud, log *slog.Logger) *Controller {
	return &Controller{Cloud: cloud, Log: log, Now: time.Now, NewID: newID}
}

// A 32-character token fits ECS startedBy and carries its creation time so a
// failed launch cannot be retried forever or cause an event-driven start storm.
func newID(now time.Time) (string, error) {
	b := make([]byte, 12)
	if _, err := rand.Read(b); err != nil {
		return "", err
	}
	return fmt.Sprintf("%08x%s", now.Unix(), hex.EncodeToString(b)), nil
}

func age(id string, now time.Time) time.Duration {
	if len(id) != 32 {
		return StartGrace
	}
	stamp, err := strconv.ParseInt(id[:8], 16, 64)
	if err != nil {
		return StartGrace
	}
	return now.Sub(time.Unix(stamp, 0))
}

// Handle is also serialized in-process for tests/tools. Production requires
// reserved concurrency=1 across all Lambda execution environments.
func (c *Controller) Handle(ctx context.Context, event Event) error {
	c.mu.Lock()
	defer c.mu.Unlock()
	if err := ctx.Err(); err != nil {
		return err
	}
	if event.Kind != "sparkplug" && event.Kind != "sweep" && event.Kind != "readiness" {
		return fmt.Errorf("unknown event kind %q", event.Kind)
	}
	if event.Kind != "sweep" && (!strings.HasPrefix(event.Thing, "tbot-") || strings.ContainsAny(event.Thing, "/+#")) {
		return nil
	}
	tasks, err := c.Cloud.Tasks(ctx)
	if err != nil {
		return fmt.Errorf("list companion tasks: %w", err)
	}
	if event.Kind != "sweep" {
		if event.Kind == "readiness" && event.Readiness == nil {
			return errors.New("readiness report is required")
		}
		return c.logged(ctx, event.Thing, tasks, event.Readiness)
	}
	things, enumerateErr := c.Cloud.Things(ctx)
	seen := make(map[string]bool)
	for _, thing := range things {
		seen[thing] = true
	}
	// Registry search may be eventually consistent. Tasks also supply deleted or
	// unindexed Things; DescribeThing below remains the authority for device type.
	for _, task := range tasks {
		seen[task.Thing] = true
	}
	things = things[:0]
	for thing := range seen {
		things = append(things, thing)
	}
	sort.Strings(things)
	var failures []error
	if enumerateErr != nil {
		failures = append(failures, fmt.Errorf("enumerate TBot things: %w", enumerateErr))
	}
	for _, thing := range things {
		if err := ctx.Err(); err != nil {
			return errors.Join(append(failures, err)...)
		}
		if err := c.logged(ctx, thing, tasks, nil); err != nil {
			failures = append(failures, err)
		}
	}
	return errors.Join(failures...)
}

func (c *Controller) logged(ctx context.Context, thing string, tasks []Task, report *Readiness) error {
	err := c.reconcile(ctx, thing, tasks, report)
	if err != nil {
		c.Log.ErrorContext(ctx, "companion reconciliation failed; minute sweep will retry", "thing", thing, "error", err)
	} else {
		c.Log.InfoContext(ctx, "companion reconciled", "thing", thing)
	}
	return err
}

func (c *Controller) active(ctx context.Context, thing string) (bool, error) {
	state, err := c.Cloud.Lifecycle(ctx, thing)
	if errors.Is(err, ErrNotFound) {
		return false, nil
	}
	return state.Active(thing), err
}

func (c *Controller) stop(ctx context.Context, tasks []Task, reason string) error {
	var failures []error
	for _, task := range tasks {
		if task.Live() && task.DesiredStatus != "STOPPED" {
			c.Log.InfoContext(ctx, "stopping companion", "thing", task.Thing, "taskId", task.ID, "taskArn", task.ARN, "reason", reason)
			if err := c.Cloud.Stop(ctx, task, reason); err != nil {
				failures = append(failures, fmt.Errorf("stop %s: %w", task.ARN, err))
			}
		}
	}
	return errors.Join(failures...)
}

func (c *Controller) inactive(ctx context.Context, store agentstatus.Store, tasks []Task) error {
	// Fence first, then stop. Even a failed StopTask cannot restore the endpoint.
	err := agentstatus.Update(ctx, store, func(agentstatus.Reported) (agentstatus.Reported, error) { return agentstatus.Stopped(), nil })
	if errors.Is(err, ErrNotFound) {
		err = nil
	} // A deleted shadow has no endpoint to clear.
	return errors.Join(err, c.stop(ctx, tasks, "TBot is dead, missing, or outside REDCON 1/2"))
}

func (c *Controller) reconcile(ctx context.Context, thing string, all []Task, report *Readiness) error {
	if !strings.HasPrefix(thing, "tbot-") {
		return nil
	}
	var tasks []Task
	for _, task := range all {
		if task.Thing == thing {
			tasks = append(tasks, task)
		}
	}
	typeName, err := c.Cloud.ThingType(ctx, thing)
	if errors.Is(err, ErrNotFound) {
		return c.inactive(ctx, c.Cloud.Store(thing), tasks)
	}
	if err != nil {
		return fmt.Errorf("verify Thing type: %w", err)
	}
	if typeName != "tbot" {
		return nil
	}
	store := c.Cloud.Store(thing)
	active, err := c.active(ctx, thing)
	if err != nil {
		return fmt.Errorf("read lifecycle: %w", err)
	}
	if !active {
		return c.inactive(ctx, store, tasks)
	}
	current, _, err := store.Read(ctx)
	if err != nil {
		if errors.Is(err, ErrNotFound) {
			return errors.Join(err, c.stop(ctx, tasks, "agent shadow missing; re-enlist the TBot"))
		}
		return fmt.Errorf("read agent state: %w", err)
	}
	var selected *Task
	var duplicates []Task
	sort.Slice(tasks, func(i, j int) bool { return tasks[i].ARN < tasks[j].ARN })
	for _, task := range tasks {
		if !task.Live() {
			continue
		}
		if current.Task.ID != nil && task.ID == *current.Task.ID && selected == nil && task.DesiredStatus != "STOPPED" {
			copy := task
			selected = &copy
		} else {
			duplicates = append(duplicates, task)
		}
	}
	if len(duplicates) > 0 {
		// Do not expose a new endpoint or launch a replacement while old tasks
		// are still stopping. Their shadow identity is already fenced.
		err := agentstatus.Update(ctx, store, func(s agentstatus.Reported) (agentstatus.Reported, error) {
			s.Endpoint = agentstatus.Endpoint{}
			if s.Task.Status == "ready" {
				s.Task.Status = "starting"
			}
			return s, nil
		})
		stopErr := c.stop(ctx, duplicates, "duplicate or superseded companion")
		if report != nil {
			return errors.Join(err, stopErr, ErrNotReady)
		}
		return errors.Join(err, stopErr)
	}
	if selected != nil {
		if current.Task.Status == "error" || (current.Task.Status != "ready" && age(selected.ID, c.Now()) >= StartGrace) {
			if err := c.fail(ctx, store, selected.ID, "task did not become ready within ten minutes or reported an error"); err != nil {
				return err
			}
			return c.stop(ctx, []Task{*selected}, "companion unhealthy")
		}
		if current.Task.Status == "ready" {
			ipv4, ipv6, err := c.Cloud.Addresses(ctx, *selected)
			if err != nil { // Clear availability even when the ENI lookup fails.
				return errors.Join(c.clear(ctx, store, selected.ID), err)
			}
			if !selected.Running() || current.MAVLink != "connected" || current.Endpoint.IPv4 == nil || current.Endpoint.IPv6 == nil ||
				*current.Endpoint.IPv4 != ipv4 || *current.Endpoint.IPv6 != ipv6 || current.Endpoint.UDPPort == nil || *current.Endpoint.UDPPort != agentstatus.UDPPort {
				if err := c.clear(ctx, store, selected.ID); err != nil {
					return err
				}
			}
		}
		if report != nil {
			return c.ready(ctx, thing, store, *selected, *report)
		}
		return c.confirm(ctx, thing, store, tasks)
	}
	if report != nil {
		return agentstatus.ErrStaleTask
	}
	// A disappeared ready task or a known stopped launch must get a fresh ID.
	knownStopped := false
	for _, task := range tasks {
		if current.Task.ID != nil && task.ID == *current.Task.ID && !task.Live() {
			knownStopped = true
		}
	}
	if current.Task.ID != nil && (current.Task.Status == "ready" || knownStopped) {
		if err := c.fail(ctx, store, *current.Task.ID, "ECS task stopped or disappeared; replacing after bounded backoff"); err != nil {
			return err
		}
		current.Task.Status = "error"
	}
	if current.Task.ID != nil && current.Task.Status == "error" && age(*current.Task.ID, c.Now()) < RestartDelay {
		return nil
	}
	id := ""
	if current.Task.ID != nil && current.Task.Status == "starting" && age(*current.Task.ID, c.Now()) < StartGrace {
		id = *current.Task.ID // Retry an ambiguous RunTask with the identical token.
	} else {
		id, err = c.NewID(c.Now())
		if err != nil {
			return err
		}
		if err := agentstatus.Update(ctx, store, func(s agentstatus.Reported) (agentstatus.Reported, error) {
			active, err := c.active(ctx, thing)
			if err != nil {
				return s, err
			}
			if !active {
				return agentstatus.Stopped(), nil
			}
			return agentstatus.Begin(s, id)
		}); err != nil {
			return err
		}
	}
	// Recheck the identity and lifecycle immediately before any task start.
	current, _, err = store.Read(ctx)
	if err != nil {
		return err
	}
	if current.Task.ID == nil || *current.Task.ID != id {
		return nil
	}
	active, err = c.active(ctx, thing)
	if err != nil {
		return err
	}
	if !active {
		return c.inactive(ctx, store, tasks)
	}
	c.Log.InfoContext(ctx, "launching or recovering companion", "thing", thing, "taskId", id)
	task, err := c.Cloud.Run(ctx, thing, id)
	if err != nil { // Preserve the token on ambiguous transport failures.
		if errors.Is(err, ErrStartRejected) {
			return errors.Join(c.fail(ctx, store, id, err.Error()), err)
		}
		statusErr := agentstatus.Update(ctx, store, func(s agentstatus.Reported) (agentstatus.Reported, error) {
			if s.Task.ID == nil || *s.Task.ID != id {
				return s, agentstatus.ErrStaleTask
			}
			message := "RunTask response unavailable; retrying the same launch identity: " + err.Error()
			s.LastError = &message
			return s, nil
		})
		return errors.Join(fmt.Errorf("RunTask (retry same launch token %s): %w", id, err), statusErr)
	}
	if !task.Live() {
		return c.fail(ctx, store, id, "ECS returned a stopped task: "+task.Reason)
	}
	return c.confirm(ctx, thing, store, append(tasks, task))
}

func (c *Controller) confirm(ctx context.Context, thing string, store agentstatus.Store, tasks []Task) error {
	active, err := c.active(ctx, thing)
	if err != nil {
		return err
	}
	if !active {
		return c.inactive(ctx, store, tasks)
	}
	return nil
}

func (c *Controller) clear(ctx context.Context, store agentstatus.Store, id string) error {
	return agentstatus.Update(ctx, store, func(s agentstatus.Reported) (agentstatus.Reported, error) {
		if s.Task.ID == nil || *s.Task.ID != id {
			return s, agentstatus.ErrStaleTask
		}
		s.Endpoint = agentstatus.Endpoint{}
		if s.Task.Status == "ready" {
			s.Task.Status = "starting"
		}
		return s, nil
	})
}

func (c *Controller) fail(ctx context.Context, store agentstatus.Store, id, message string) error {
	c.Log.WarnContext(ctx, "companion unavailable", "taskId", id, "reason", message)
	return agentstatus.Update(ctx, store, func(s agentstatus.Reported) (agentstatus.Reported, error) { return agentstatus.Fail(s, id, message) })
}

func (c *Controller) ready(ctx context.Context, thing string, store agentstatus.Store, task Task, r Readiness) error {
	if r.ID != task.ID || r.TaskARN != task.ARN {
		return agentstatus.ErrStaleTask
	}
	if !task.Running() {
		return ErrNotReady
	}
	ipv4, ipv6, err := c.Cloud.Addresses(ctx, task)
	if err != nil {
		return errors.Join(c.clear(ctx, store, task.ID), err)
	}
	// A delayed connection snapshot must not overwrite a newer snapshot from the
	// same task. The task reads this version just before sending its current state.
	state, version, err := store.Read(ctx)
	if err != nil {
		return err
	}
	if state.Task.ID == nil || *state.Task.ID != r.ID {
		return agentstatus.ErrStaleTask
	}
	if r.ShadowVersion != version {
		return agentstatus.ErrVersionConflict
	}
	next, err := func(s agentstatus.Reported) (agentstatus.Reported, error) {
		active, err := c.active(ctx, thing)
		if err != nil {
			return s, err
		}
		if !active {
			return agentstatus.Stopped(), nil
		}
		s, err = agentstatus.Connection(s, r.ID, "mavlink", r.MAVLink)
		if err != nil {
			return s, err
		}
		s, err = agentstatus.Connection(s, r.ID, "video", r.Video)
		if err != nil {
			return s, err
		}
		if !r.UDPListening || r.MAVLink != "connected" {
			s.Endpoint = agentstatus.Endpoint{}
			s.Task.Status = "starting"
			return s, nil
		}
		return agentstatus.Ready(s, r.ID, ipv4, ipv6, r.UDPListening)
	}(state)
	if err != nil {
		return err
	}
	if err := store.Write(ctx, next, version); err != nil {
		if errors.Is(err, agentstatus.ErrVersionConflict) {
			current, _, readErr := store.Read(ctx)
			if readErr != nil {
				return errors.Join(err, readErr)
			}
			if current.Task.ID == nil || *current.Task.ID != r.ID {
				return agentstatus.ErrStaleTask
			}
		}
		return err // Runtime must reread and regenerate its current readiness snapshot.
	}
	return c.confirm(ctx, thing, store, []Task{task})
}

// DecodeEvent rejects mixed readiness/event payloads. The IoT rule and minute
// schedule emit small envelopes; completed shadow contents are never trusted.
func DecodeEvent(payload json.RawMessage) (Event, error) {
	var event Event
	if err := json.Unmarshal(payload, &event); err != nil {
		return event, err
	}
	if event.Kind != "readiness" && event.Readiness != nil {
		return event, errors.New("readiness requires readiness event kind")
	}
	return event, nil
}
