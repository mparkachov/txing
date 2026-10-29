package witness

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"regexp"
	"time"
)

const AgentWatchSource = "txing.witness.agent-watch"
const AgentWatchGrace = 2 * time.Minute

type WatchMicrovm struct {
	ID, Image, State string
	StartedAt        time.Time
}

type AgentWatchAWS interface {
	AgentThings(context.Context) ([]string, error)
	AgentShadow(context.Context, string) ([]byte, bool, error)
	MicrovmPage(context.Context, string, string) ([]WatchMicrovm, string, error)
	Microvm(context.Context, string) (WatchMicrovm, error)
	TerminateMicrovm(context.Context, string) error
}

// The watch has no shadow-write or launch interface. Its image is dedicated to
// this environment's controller and covers all versions of that image.
type AgentWatcher struct {
	AWS        AgentWatchAWS
	Projection AWS
	Image      string
	Now        func() time.Time
}

type WatchResult struct {
	Checked    int  `json:"checked"`
	Requested  int  `json:"terminationRequests"`
	Incomplete bool `json:"incomplete"`
}

var watchImagePattern = regexp.MustCompile(`^arn:aws:lambda:eu-central-1:[0-9]{12}:microvm-image:[A-Za-z0-9_-]+$`)

func (w AgentWatcher) configured() bool { return watchImagePattern.MatchString(w.Image) }
func (w AgentWatcher) now() time.Time {
	if w.Now != nil {
		return w.Now()
	}
	return time.Now()
}

func (w AgentWatcher) Handle(ctx context.Context, event map[string]any) (map[string]any, error) {
	if event["source"] == AgentWatchSource {
		if w.Image == "" {
			return map[string]any{"status": "watch-disabled"}, nil
		}
		watchCtx, cancel := context.WithTimeout(ctx, 25*time.Second)
		defer cancel()
		result, err := w.Sweep(watchCtx)
		return map[string]any{"status": "watch", "watch": result}, err
	}
	result, err := HandleLambdaEvent(ctx, event, w.Projection)
	if err != nil || !w.configured() {
		return result, err
	}
	thing, _ := result["thingName"].(string)
	if thing != "" && thing != "ignored" {
		// Projection must not be retried or delayed by an unrelated watch error.
		watchCtx, cancel := context.WithTimeout(ctx, 4*time.Second)
		defer cancel()
		if err := w.Thing(watchCtx, thing); err != nil {
			log.Printf("agent watch incomplete for thing %s; scheduled pass will retry", thing)
			result["watchStatus"] = "incomplete"
		}
	}
	return result, nil
}

type watchShadow struct {
	Version int64 `json:"version"`
	State   struct {
		Reported struct {
			Lifecycle struct {
				State string `json:"state"`
			} `json:"lifecycle"`
			Run *struct {
				ID        string `json:"id"`
				MicrovmID string `json:"microvmId"`
			} `json:"run"`
			Activation *struct {
				ID        string `json:"id"`
				StartedAt int64  `json:"startedAt"`
				Deadline  int64  `json:"deadline"`
			} `json:"activation"`
			Controller struct {
				Active          bool   `json:"active"`
				RunPhase        string `json:"runPhase"`
				RunActivationID string `json:"runActivationId"`
				StopRequestedAt int64  `json:"stopRequestedAt"`
			} `json:"controller"`
		} `json:"reported"`
	} `json:"state"`
	Metadata struct {
		Reported struct {
			Lifecycle struct {
				State struct {
					Timestamp int64 `json:"timestamp"`
				} `json:"state"`
			} `json:"lifecycle"`
		} `json:"reported"`
	} `json:"metadata"`
}

func parseWatchShadow(body []byte) (watchShadow, error) {
	var s watchShadow
	if err := json.Unmarshal(body, &s); err != nil {
		return s, errors.New("invalid agent shadow JSON")
	}
	r := s.State.Reported
	if s.Version <= 0 {
		return s, errors.New("agent shadow has no current version")
	}
	switch r.Lifecycle.State {
	case "starting", "running":
		if r.Run == nil || r.Run.ID == "" || r.Activation == nil || r.Activation.ID == "" ||
			r.Activation.StartedAt <= 0 || r.Activation.Deadline <= r.Activation.StartedAt ||
			r.Activation.Deadline-r.Activation.StartedAt > 3000 || !r.Controller.Active ||
			r.Controller.RunActivationID != r.Activation.ID ||
			(r.Lifecycle.State == "running" && (r.Run.MicrovmID == "" || r.Controller.RunPhase != "running")) ||
			(r.Lifecycle.State == "starting" && r.Controller.RunPhase != "reserved") {
			return s, errors.New("inconsistent active agent assignment")
		}
	case "stopping", "stopped", "expired", "error":
	default:
		return s, errors.New("unknown agent lifecycle")
	}
	if r.Controller.StopRequestedAt < 0 || (r.Run != nil && r.Run.ID == "") {
		return s, errors.New("invalid agent stop time or run identity")
	}
	return s, nil
}

func (s watchShadow) microvmID() string {
	if s.State.Reported.Run == nil {
		return ""
	}
	return s.State.Reported.Run.MicrovmID
}

// A missing timestamp never turns an uncertain off assignment into an orphan.
func (s watchShadow) stopDue(now time.Time) bool {
	r := s.State.Reported
	var since int64
	if r.Activation != nil && r.Activation.Deadline > 0 && now.Unix() >= r.Activation.Deadline {
		since = r.Activation.Deadline
	}
	switch r.Lifecycle.State {
	case "stopping", "stopped", "expired", "error":
		off := r.Controller.StopRequestedAt
		if off == 0 {
			off = s.Metadata.Reported.Lifecycle.State.Timestamp
		}
		if off > 0 && (since == 0 || off < since) {
			since = off
		}
	}
	return since > 0 && now.Unix() >= since && now.Unix()-since >= int64(AgentWatchGrace/time.Second)
}

func (s watchShadow) needsShutdown(now time.Time) bool {
	r := s.State.Reported
	return (r.Lifecycle.State != "starting" && r.Lifecycle.State != "running") ||
		(r.Activation != nil && now.Unix() >= r.Activation.Deadline)
}

func actionable(state string) bool {
	switch state {
	case "PENDING", "RUNNING", "SUSPENDING", "SUSPENDED":
		return true
	default:
		return false
	}
}

func (w AgentWatcher) read(ctx context.Context, thing string) (*watchShadow, error) {
	body, exists, err := w.AWS.AgentShadow(ctx, thing)
	if err != nil || !exists {
		return nil, err
	}
	s, err := parseWatchShadow(body)
	return &s, err
}

// Thing adds a bounded check after projection, including unchanged metrics.
// It verifies the image independently of the shadow's claimed launch request.
func (w AgentWatcher) Thing(ctx context.Context, thing string) error {
	if !w.configured() {
		return errors.New("agent watch requires a scoped Frankfurt image ARN")
	}
	s, err := w.read(ctx, thing)
	if err != nil || s == nil || s.microvmID() == "" || !s.stopDue(w.now()) {
		return err
	}
	_, _, err = w.stopKnown(ctx, thing, *s)
	return err
}

func (w AgentWatcher) stopKnown(ctx context.Context, thing string, s watchShadow) (requested, pending bool, err error) {
	vm, err := w.AWS.Microvm(ctx, s.microvmID())
	if err != nil {
		return false, true, errors.New("agent watch VM read failed")
	}
	if vm.ID != s.microvmID() || vm.Image != w.Image {
		return false, true, errors.New("agent watch image or VM identity mismatch")
	}
	if !actionable(vm.State) {
		return false, vm.State != "TERMINATED", nil
	}
	latest, err := w.read(ctx, thing)
	if err != nil {
		return false, true, errors.New("agent watch assignment recheck failed")
	}
	if latest == nil || latest.Version < s.Version || latest.microvmID() != vm.ID || !latest.stopDue(w.now()) {
		return false, true, nil
	}
	if err := w.AWS.TerminateMicrovm(ctx, vm.ID); err != nil {
		return false, true, errors.New("agent watch termination failed")
	}
	log.Printf("agent watch requested termination of MicroVM %s", vm.ID)
	return true, true, nil
}

type watchAssignment struct {
	thing  string
	shadow watchShadow
}

func (w AgentWatcher) assignments(ctx context.Context) (map[string]watchAssignment, bool) {
	things, err := w.AWS.AgentThings(ctx)
	if err != nil {
		return nil, false
	}
	assigned := map[string]watchAssignment{}
	complete := true
	for _, thing := range things {
		s, err := w.read(ctx, thing)
		if err != nil {
			complete = false
			continue
		}
		if s == nil || s.microvmID() == "" {
			continue
		}
		if _, duplicate := assigned[s.microvmID()]; duplicate {
			complete = false
			assigned[s.microvmID()] = watchAssignment{}
			continue
		}
		assigned[s.microvmID()] = watchAssignment{thing, *s}
	}
	return assigned, complete
}

// Inventory pages are acted on before fetching the next page. Failed pages,
// reads and termination requests remain incomplete for the next minute pass.
func (w AgentWatcher) Sweep(ctx context.Context) (WatchResult, error) {
	var result WatchResult
	if !w.configured() {
		return result, errors.New("agent watch requires a scoped Frankfurt image ARN")
	}
	token := ""
	tokens, seen := map[string]bool{}, map[string]bool{}
	var failures []error
	assigned, complete := w.assignments(ctx)
	if !complete {
		result.Incomplete = true
		failures = append(failures, errors.New("agent watch assignment inventory incomplete"))
	}
	checkKnown := func(assignment watchAssignment) {
		requested, pending, err := w.stopKnown(ctx, assignment.thing, assignment.shadow)
		if requested {
			result.Requested++
		}
		result.Incomplete = result.Incomplete || pending
		if err != nil {
			failures = append(failures, err)
		}
	}
	for page := 0; page < 1000; page++ {
		items, next, err := w.AWS.MicrovmPage(ctx, w.Image, token)
		if err != nil {
			failures = append(failures, errors.New("agent watch inventory failed"))
			break
		}
		for _, item := range items {
			if ctx.Err() != nil {
				failures = append(failures, ctx.Err())
				break
			}
			if item.Image == w.Image && (item.State == "TERMINATING" || (item.State != "TERMINATED" && !actionable(item.State))) {
				result.Incomplete = true
			}
			if item.Image != w.Image || item.ID == "" || !actionable(item.State) || seen[item.ID] {
				continue
			}
			seen[item.ID] = true
			result.Checked++
			assignment, known := assigned[item.ID]
			if known && !assignment.shadow.stopDue(w.now()) {
				if assignment.shadow.needsShutdown(w.now()) {
					result.Incomplete = true
				}
				continue
			}
			if !known && !complete {
				continue
			}
			if known {
				checkKnown(assignment)
				continue
			}
			vm, err := w.AWS.Microvm(ctx, item.ID)
			if err != nil {
				failures = append(failures, errors.New("agent watch VM read failed"))
				continue
			}
			if vm.ID != item.ID || vm.Image != w.Image {
				failures = append(failures, errors.New("agent watch image or VM identity mismatch"))
				continue
			}
			if !actionable(vm.State) {
				if vm.State != "TERMINATED" {
					result.Incomplete = true
				}
				continue
			}
			if vm.StartedAt.IsZero() || w.now().Before(vm.StartedAt.Add(AgentWatchGrace)) {
				result.Incomplete = true
				continue
			}
			// A second current read prevents a stale off snapshot from killing a
			// repaired assignment. IDs identify immutable VM instances.
			fresh, freshComplete := w.assignments(ctx)
			if current, ok := fresh[vm.ID]; ok {
				if !current.shadow.stopDue(w.now()) {
					continue
				}
			} else if !freshComplete {
				result.Incomplete = true
				continue
			}
			result.Incomplete = true // A request is not terminal-state evidence.
			if err := w.AWS.TerminateMicrovm(ctx, vm.ID); err != nil {
				failures = append(failures, errors.New("agent watch termination failed"))
				continue
			}
			result.Requested++
			log.Printf("agent watch requested termination of MicroVM %s", vm.ID)
		}
		if next == "" {
			break
		}
		if tokens[next] || page == 999 {
			failures = append(failures, errors.New("agent watch inventory pagination did not finish"))
			break
		}
		tokens[next] = true
		token = next
	}
	// A listing omission or failure must not hide a known off assignment.
	for id, assignment := range assigned {
		if !seen[id] && assignment.shadow.stopDue(w.now()) {
			result.Checked++
			checkKnown(assignment)
		}
	}
	if len(failures) > 0 {
		result.Incomplete = true
		return result, fmt.Errorf("agent watch incomplete: %w", errors.Join(failures...))
	}
	return result, nil
}
