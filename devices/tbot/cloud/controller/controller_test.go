package controller

import (
	"context"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/mparkachov/txing/devices/tbot/cloud/agentstatus"
)

const thing = "tbot-test"

type memoryStore struct {
	mu        sync.Mutex
	state     agentstatus.Reported
	version   int64
	writes    int
	conflicts int
	onWrite   func(*memoryStore)
}

func (s *memoryStore) Read(context.Context) (agentstatus.Reported, int64, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.state, s.version, nil
}
func (s *memoryStore) Write(_ context.Context, next agentstatus.Reported, version int64) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.writes++
	if s.onWrite != nil {
		hook := s.onWrite
		s.onWrite = nil
		hook(s)
	}
	if s.conflicts > 0 {
		s.conflicts--
		s.version++
		return agentstatus.ErrVersionConflict
	}
	if version != s.version {
		return agentstatus.ErrVersionConflict
	}
	s.state = next
	s.version++
	return nil
}

type fakeCloud struct {
	store                                                                 *memoryStore
	life                                                                  Lifecycle
	typeName                                                              string
	typeErr, errorRun, errorStop, errorAddresses, errorTasks, errorThings error
	tasks                                                                 []Task
	names                                                                 []string
	runs, stops, reads                                                    int
	onRead                                                                func(*fakeCloud)
	onRun                                                                 func(*fakeCloud)
	ambiguous                                                             bool
	hideTasks                                                             bool
}

func (f *fakeCloud) Things(context.Context) ([]string, error)          { return f.names, f.errorThings }
func (f *fakeCloud) ThingType(context.Context, string) (string, error) { return f.typeName, f.typeErr }
func (f *fakeCloud) Lifecycle(context.Context, string) (Lifecycle, error) {
	f.reads++
	if f.onRead != nil {
		f.onRead(f)
	}
	return f.life, nil
}
func (f *fakeCloud) Store(string) agentstatus.Store { return f.store }
func (f *fakeCloud) Tasks(context.Context) ([]Task, error) {
	if f.hideTasks {
		return nil, f.errorTasks
	}
	return append([]Task(nil), f.tasks...), f.errorTasks
}
func (f *fakeCloud) Run(_ context.Context, name, id string) (Task, error) {
	f.runs++
	if f.errorRun != nil {
		return Task{}, f.errorRun
	}
	for _, task := range f.tasks {
		if task.ID == id {
			return task, nil
		}
	}
	task := Task{ARN: fmt.Sprintf("arn:task/%d", f.runs), Thing: name, ID: id, Status: "RUNNING", DesiredStatus: "RUNNING", ENI: "eni-1"}
	f.tasks = append(f.tasks, task)
	if f.onRun != nil {
		f.onRun(f)
	}
	if f.ambiguous {
		f.ambiguous = false
		return Task{}, errors.New("network response lost")
	}
	return task, nil
}
func (f *fakeCloud) Stop(_ context.Context, task Task, _ string) error {
	f.stops++
	if f.errorStop != nil {
		return f.errorStop
	}
	for i := range f.tasks {
		if f.tasks[i].ARN == task.ARN {
			f.tasks[i].DesiredStatus = "STOPPED"
		}
	}
	return nil
}
func (f *fakeCloud) Addresses(context.Context, Task) (string, string, error) {
	return "203.0.113.10", "2001:db8::10", f.errorAddresses
}
func lifecycle(redcon int, message string) Lifecycle {
	var s Lifecycle
	s.Topic.Namespace = "spBv1.0"
	s.Topic.DeviceID = thing
	s.Topic.MessageType = message
	s.Payload.Metrics.REDCON = redcon
	return s
}
func setup() (*Controller, *fakeCloud, *time.Time) {
	now := time.Unix(1800000000, 0)
	f := &fakeCloud{store: &memoryStore{state: agentstatus.Stopped(), version: 1}, life: lifecycle(2, "DBIRTH"), typeName: "tbot", names: []string{thing}}
	c := New(f, slog.New(slog.NewTextHandler(io.Discard, nil)))
	c.Now = func() time.Time { return now }
	sequence := 0
	c.NewID = func(t time.Time) (string, error) {
		sequence++
		return fmt.Sprintf("%08x%024x", t.Unix(), sequence), nil
	}
	return c, f, &now
}
func reconcile(t *testing.T, c *Controller) {
	t.Helper()
	if err := c.Handle(context.Background(), Event{Kind: "sparkplug", Thing: thing}); err != nil {
		t.Fatal(err)
	}
}
func report(t *testing.T, c *Controller, f *fakeCloud, udp bool, mavlink, video string) error {
	t.Helper()
	id := *f.store.state.Task.ID
	return c.Handle(context.Background(), Event{Kind: "readiness", Thing: thing, Readiness: &Readiness{ShadowVersion: f.store.version, ID: id, TaskARN: f.tasks[len(f.tasks)-1].ARN, UDPListening: udp, MAVLink: mavlink, Video: video}})
}
func stoppedTasks(f *fakeCloud) {
	for i := range f.tasks {
		if f.tasks[i].DesiredStatus == "STOPPED" {
			f.tasks[i].Status = "STOPPED"
		}
	}
}
func noEndpoint(t *testing.T, f *fakeCloud) {
	t.Helper()
	if f.store.state.Endpoint.IPv4 != nil || f.store.state.Endpoint.IPv6 != nil || f.store.state.Endpoint.UDPPort != nil {
		t.Fatal("stale usable endpoint", f.store.state)
	}
}

func TestLifecycleTransitionsAndReadiness(t *testing.T) {
	c, f, _ := setup()
	f.life = lifecycle(3, "DBIRTH")
	reconcile(t, c)
	if f.runs != 0 {
		t.Fatal("started REDCON 3")
	}
	f.life = lifecycle(2, "DDATA")
	reconcile(t, c)
	if f.runs != 1 || f.store.state.Task.Status != "starting" {
		t.Fatal("did not start")
	}
	noEndpoint(t, f)
	if err := report(t, c, f, false, "connected", "disconnected"); err != nil {
		t.Fatal(err)
	}
	noEndpoint(t, f)
	if err := report(t, c, f, true, "connected", "disconnected"); err != nil {
		t.Fatal(err)
	}
	if f.store.state.Task.Status != "ready" {
		t.Fatal("not ready")
	}
	id := *f.store.state.Task.ID
	for _, redcon := range []int{1, 2, 1, 2} {
		f.life = lifecycle(redcon, "DDATA")
		reconcile(t, c)
		if *f.store.state.Task.ID != id || f.runs != 1 {
			t.Fatal("REDCON 1/2 replaced MAVLink task")
		}
	}
	if err := report(t, c, f, true, "connected", "error"); err != nil {
		t.Fatal(err)
	}
	if f.store.state.Task.Status != "ready" || f.store.state.Video != "error" {
		t.Fatal("video error interrupted endpoint")
	}
	if err := report(t, c, f, true, "disconnected", "connected"); err != nil {
		t.Fatal(err)
	}
	noEndpoint(t, f)
	if err := report(t, c, f, true, "connected", "disconnected"); err != nil {
		t.Fatal(err)
	}
	f.life = lifecycle(3, "DDATA")
	reconcile(t, c)
	noEndpoint(t, f)
	if f.store.state.Task.ID != nil || f.stops != 1 {
		t.Fatal("did not fence and stop")
	}
	stoppedTasks(f)
	f.life = lifecycle(2, "DBIRTH")
	reconcile(t, c)
	if f.runs != 2 || *f.store.state.Task.ID == id {
		t.Fatal("rebirth reused fenced identity")
	}
	f.life = lifecycle(4, "DDATA")
	reconcile(t, c)
	noEndpoint(t, f)
	stoppedTasks(f)
	f.life = lifecycle(1, "DBIRTH")
	reconcile(t, c)
	f.life = lifecycle(1, "DDEATH")
	reconcile(t, c)
	noEndpoint(t, f)
	if f.store.state.Task.Status != "stopped" {
		t.Fatal("death retained task")
	}
}

func TestReplayAndConcurrentInvocationsUseLatestState(t *testing.T) {
	c, f, _ := setup()
	var wg sync.WaitGroup
	for i := 0; i < 20; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			if err := c.Handle(context.Background(), Event{Kind: "sparkplug", Thing: thing}); err != nil {
				t.Error(err)
			}
		}()
	}
	wg.Wait()
	if f.runs != 1 {
		t.Fatal("concurrent calls duplicated task", f.runs)
	}
	f.life = lifecycle(2, "DDEATH")
	for i := 0; i < 3; i++ {
		reconcile(t, c)
	} // Old birth envelopes carry no authoritative state.
	if f.runs != 1 {
		t.Fatal("delayed event resurrected dead task")
	}
	noEndpoint(t, f)
}

func TestDeathDuringStartAndBeforeShadowCommit(t *testing.T) {
	for _, at := range []string{"run", "begin-write", "ready-write"} {
		t.Run(at, func(t *testing.T) {
			c, f, _ := setup()
			switch at {
			case "run":
				f.onRun = func(f *fakeCloud) { f.life = lifecycle(2, "DDEATH") }
			case "begin-write":
				f.store.onWrite = func(*memoryStore) { f.life = lifecycle(2, "DDEATH") }
			case "ready-write":
				reconcile(t, c)
				f.store.onWrite = func(*memoryStore) { f.life = lifecycle(2, "DDEATH") }
			}
			if at == "ready-write" {
				if err := report(t, c, f, true, "connected", "disconnected"); err != nil {
					t.Fatal(err)
				}
			} else {
				reconcile(t, c)
			}
			noEndpoint(t, f)
			if f.store.state.Task.ID != nil {
				t.Fatal("death failed to fence launch")
			}
			if at == "begin-write" && f.runs != 0 {
				t.Fatal("started after observed death")
			}
		})
	}
}

func TestAmbiguousStartRecoveryAndCrashBackoff(t *testing.T) {
	c, f, now := setup()
	f.ambiguous = true
	if err := c.Handle(context.Background(), Event{Kind: "sparkplug", Thing: thing}); err == nil {
		t.Fatal("expected lost response")
	}
	id := *f.store.state.Task.ID
	// Hide the task to reproduce eventual consistency. Replay must use the same token.
	f.hideTasks = true
	reconcile(t, c)
	if *f.store.state.Task.ID != id || len(f.tasks) != 1 {
		t.Fatal("ambiguous start duplicated identity")
	}
	f.hideTasks = false
	if err := report(t, c, f, true, "connected", "disconnected"); err != nil {
		t.Fatal(err)
	}
	f.tasks[0].Status = "STOPPED"
	f.tasks[0].DesiredStatus = "STOPPED"
	if err := c.Handle(context.Background(), Event{Kind: "sweep"}); err != nil {
		t.Fatal(err)
	}
	noEndpoint(t, f)
	if f.store.state.Task.Status != "error" {
		t.Fatal("crash not recorded")
	}
	for i := 0; i < 10; i++ {
		reconcile(t, c)
	}
	if f.runs != 2 {
		t.Fatal("crash loop bypassed backoff")
	}
	*now = now.Add(RestartDelay)
	reconcile(t, c)
	if *f.store.state.Task.ID == id || f.runs != 3 {
		t.Fatal("crash did not recover")
	}
}

func TestDuplicateAndSupersededTasksCannotRestoreEndpoint(t *testing.T) {
	c, f, _ := setup()
	reconcile(t, c)
	id := *f.store.state.Task.ID
	if err := report(t, c, f, true, "connected", "disconnected"); err != nil {
		t.Fatal(err)
	}
	old := Task{ARN: "arn:task/old", Thing: thing, ID: "old", Status: "RUNNING", DesiredStatus: "RUNNING"}
	f.tasks = append(f.tasks, old)
	reconcile(t, c)
	noEndpoint(t, f)
	if f.stops != 1 || f.runs != 1 {
		t.Fatal("duplicate not stopped")
	}
	err := c.Handle(context.Background(), Event{Kind: "readiness", Thing: thing, Readiness: &Readiness{ID: "old", TaskARN: old.ARN, UDPListening: true, MAVLink: "connected", Video: "disconnected"}})
	if err != nil && !errors.Is(err, agentstatus.ErrStaleTask) && !errors.Is(err, ErrNotReady) {
		t.Fatal(err)
	}
	noEndpoint(t, f)
	stoppedTasks(f)
	if err := c.Handle(context.Background(), Event{Kind: "readiness", Thing: thing, Readiness: &Readiness{ShadowVersion: f.store.version, ID: id, TaskARN: f.tasks[0].ARN, UDPListening: true, MAVLink: "connected", Video: "disconnected"}}); err != nil {
		t.Fatal(err)
	}
	if f.store.state.Task.Status != "ready" {
		t.Fatal("survivor did not regain readiness")
	}
}

func TestSupersededReportAfterCASConflict(t *testing.T) {
	c, f, _ := setup()
	reconcile(t, c)
	f.store.onWrite = func(s *memoryStore) { s.state = agentstatus.Stopped(); s.version++ }
	err := report(t, c, f, true, "connected", "disconnected")
	if !errors.Is(err, agentstatus.ErrStaleTask) {
		t.Fatal("stale report passed conflict", err)
	}
	noEndpoint(t, f)
}

func TestMinuteSweepRepairsMissingEventAndStaleAddress(t *testing.T) {
	c, f, _ := setup()
	if err := c.Handle(context.Background(), Event{Kind: "sweep"}); err != nil {
		t.Fatal(err)
	}
	if f.runs != 1 {
		t.Fatal("missed birth not repaired")
	}
	if err := report(t, c, f, true, "connected", "disconnected"); err != nil {
		t.Fatal(err)
	}
	wrong := "203.0.113.99"
	f.store.state.Endpoint.IPv4 = &wrong
	if err := c.Handle(context.Background(), Event{Kind: "sweep"}); err != nil {
		t.Fatal(err)
	}
	noEndpoint(t, f)
	f.life = lifecycle(2, "DDEATH")
	if err := c.Handle(context.Background(), Event{Kind: "sweep"}); err != nil {
		t.Fatal(err)
	}
	noEndpoint(t, f)
	if f.stops != 1 {
		t.Fatal("missed death not repaired")
	}
}

func TestTypeIsolationRemovedThingAndInvalidLifecycle(t *testing.T) {
	for _, typeName := range []string{"unit", "cyberbrick", ""} {
		t.Run(typeName, func(t *testing.T) {
			c, f, _ := setup()
			f.typeName = typeName
			reconcile(t, c)
			if f.runs != 0 || f.reads != 0 || f.store.writes != 0 {
				t.Fatal("non-TBot was modified")
			}
		})
	}
	c, f, _ := setup()
	reconcile(t, c)
	if err := report(t, c, f, true, "connected", "disconnected"); err != nil {
		t.Fatal(err)
	}
	f.typeErr = ErrNotFound
	f.names = nil
	if err := c.Handle(context.Background(), Event{Kind: "sweep"}); err != nil {
		t.Fatal(err)
	}
	if f.stops != 1 {
		t.Fatal("deleted Thing left orphan task")
	}
	noEndpoint(t, f)
	for _, message := range []string{"NDEATH", "NBIRTH", "NDATA", "DDEATH", ""} {
		c, f, _ := setup()
		f.life = lifecycle(1, message)
		reconcile(t, c)
		if f.runs != 0 {
			t.Fatal("invalid lifecycle started", message)
		}
	}
}

func TestFailureBoundsAndStopFailureStillClears(t *testing.T) {
	c, f, now := setup()
	f.errorRun = ErrStartRejected
	if err := c.Handle(context.Background(), Event{Kind: "sparkplug", Thing: thing}); !errors.Is(err, ErrStartRejected) {
		t.Fatal(err)
	}
	for i := 0; i < 20; i++ {
		reconcile(t, c)
	}
	if f.runs != 1 || f.store.state.LastError == nil {
		t.Fatal("failed start storm")
	}
	*now = now.Add(RestartDelay)
	f.errorRun = nil
	reconcile(t, c)
	f.life = lifecycle(3, "DDATA")
	f.errorStop = errors.New("ECS unavailable")
	if err := c.Handle(context.Background(), Event{Kind: "sparkplug", Thing: thing}); err == nil {
		t.Fatal("stop error not returned")
	}
	noEndpoint(t, f)
	if f.store.state.Task.ID != nil {
		t.Fatal("failed stop left identity active")
	}
	c, f, _ = setup()
	f.store.conflicts = 20
	if err := c.Handle(context.Background(), Event{Kind: "sparkplug", Thing: thing}); !errors.Is(err, agentstatus.ErrVersionConflict) {
		t.Fatal(err)
	}
	if f.store.writes != 3 || f.runs != 0 {
		t.Fatal("shadow retries unbounded")
	}
}

func TestStuckStartAndMalformedReadiness(t *testing.T) {
	c, f, now := setup()
	reconcile(t, c)
	*now = now.Add(StartGrace)
	reconcile(t, c)
	if f.stops != 1 || f.store.state.Task.Status != "error" {
		t.Fatal("stuck start retained")
	}
	for _, body := range []string{`{"kind":"sparkplug","readiness":{}}`, `garbage`} {
		if _, err := DecodeEvent([]byte(body)); err == nil {
			t.Fatal("invalid event accepted")
		}
	}
	c, f, _ = setup()
	reconcile(t, c)
	f.errorAddresses = errors.New("no dual stack addresses")
	if err := report(t, c, f, true, "connected", "disconnected"); err == nil || !strings.Contains(err.Error(), "dual stack") {
		t.Fatal(err)
	}
	noEndpoint(t, f)
}

func TestOutOfOrderReadinessCannotRestoreLostLink(t *testing.T) {
	c, f, _ := setup()
	reconcile(t, c)
	stale := Readiness{ShadowVersion: f.store.version, ID: *f.store.state.Task.ID, TaskARN: f.tasks[0].ARN, UDPListening: true, MAVLink: "connected", Video: "disconnected"}
	if err := report(t, c, f, false, "disconnected", "disconnected"); err != nil {
		t.Fatal(err)
	}
	if err := c.Handle(context.Background(), Event{Kind: "readiness", Thing: thing, Readiness: &stale}); !errors.Is(err, agentstatus.ErrVersionConflict) {
		t.Fatal("old readiness passed", err)
	}
	noEndpoint(t, f)
	if f.store.state.MAVLink != "disconnected" {
		t.Fatal("old connection state restored")
	}
}

func TestSweepStillStopsTasksWhenFleetIndexFails(t *testing.T) {
	c, f, _ := setup()
	reconcile(t, c)
	f.errorThings = errors.New("index unavailable")
	f.life = lifecycle(2, "DDEATH")
	err := c.Handle(context.Background(), Event{Kind: "sweep"})
	if err == nil || f.stops != 1 {
		t.Fatal("index failure prevented orphan cleanup", err)
	}
	noEndpoint(t, f)
}

type fleetCloud struct {
	*fakeCloud
	stores map[string]*memoryStore
	lives  map[string]Lifecycle
}

func (f *fleetCloud) Store(name string) agentstatus.Store { return f.stores[name] }
func (f *fleetCloud) Lifecycle(_ context.Context, name string) (Lifecycle, error) {
	return f.lives[name], nil
}

func TestFleetSweepKeepsTaskAndEndpointOwnershipSeparate(t *testing.T) {
	c, base, _ := setup()
	f := &fleetCloud{fakeCloud: base, stores: map[string]*memoryStore{}, lives: map[string]Lifecycle{}}
	f.names = []string{"tbot-a", "tbot-b"}
	for _, name := range f.names {
		f.stores[name] = &memoryStore{state: agentstatus.Stopped(), version: 1}
		life := lifecycle(2, "DBIRTH")
		life.Topic.DeviceID = name
		f.lives[name] = life
	}
	c.Cloud = f
	if err := c.Handle(context.Background(), Event{Kind: "sweep"}); err != nil {
		t.Fatal(err)
	}
	if f.runs != 2 || *f.stores["tbot-a"].state.Task.ID == *f.stores["tbot-b"].state.Task.ID {
		t.Fatal("fleet did not get distinct tasks")
	}
	for _, task := range f.tasks {
		r := &Readiness{ID: task.ID, TaskARN: task.ARN, ShadowVersion: f.stores[task.Thing].version, UDPListening: true, MAVLink: "connected", Video: "disconnected"}
		if err := c.Handle(context.Background(), Event{Kind: "readiness", Thing: task.Thing, Readiness: r}); err != nil {
			t.Fatal(err)
		}
	}
	f.lives["tbot-a"] = Lifecycle{}
	if err := c.Handle(context.Background(), Event{Kind: "sweep"}); err != nil {
		t.Fatal(err)
	}
	if f.stores["tbot-a"].state.Task.ID != nil || f.stores["tbot-a"].state.Endpoint.IPv4 != nil {
		t.Fatal("inactive TBot retained endpoint")
	}
	if f.stores["tbot-b"].state.Task.Status != "ready" || f.stores["tbot-b"].state.Endpoint.IPv4 == nil {
		t.Fatal("one TBot's death disturbed another endpoint")
	}
	if f.stops != 1 || f.runs != 2 {
		t.Fatal("incorrect fleet task actions", f.stops, f.runs)
	}
}
