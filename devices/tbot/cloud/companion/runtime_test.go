package companion

import (
	"bytes"
	"context"
	"errors"
	"sync"
	"testing"
	"time"

	"github.com/mparkachov/txing/devices/tbot/cloud/agentstatus"
	"github.com/mparkachov/txing/devices/tbot/cloud/controller"
)

const testThing = "tbot-test"
const testID = "12345678123456781234567812345678"

type memoryStore struct {
	mu        sync.Mutex
	state     agentstatus.Reported
	version   int64
	conflicts int
}

func (s *memoryStore) Read(ctx context.Context) (agentstatus.Reported, int64, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.state, s.version, ctx.Err()
}
func (s *memoryStore) Write(ctx context.Context, next agentstatus.Reported, version int64) error {
	s.mu.Lock()
	defer s.mu.Unlock()
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
	return ctx.Err()
}

type fakeCloud struct {
	mu       sync.Mutex
	life     controller.Lifecycle
	err      error
	store    *memoryStore
	reports  []controller.Readiness
	onReport func(context.Context, controller.Readiness) error
}

func (c *fakeCloud) Lifecycle(ctx context.Context) (controller.Lifecycle, error) {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.life, c.err
}
func (c *fakeCloud) Store() agentstatus.Store { return c.store }
func (c *fakeCloud) Readiness(ctx context.Context, r controller.Readiness) error {
	c.mu.Lock()
	c.reports = append(c.reports, r)
	hook := c.onReport
	c.mu.Unlock()
	if hook != nil {
		return hook(ctx, r)
	}
	return ctx.Err()
}
func (c *fakeCloud) level(level int, death bool) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.life.Payload.Metrics.REDCON = level
	if death {
		c.life.Topic.MessageType = "DDEATH"
	}
}

type fakeSession struct {
	mu     sync.Mutex
	events chan Event
	closed bool
	sends  int
}

func (s *fakeSession) Events() <-chan Event { return s.events }
func (s *fakeSession) Send(context.Context, byte, []byte) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.sends++
	return nil
}
func (s *fakeSession) emit(e Event) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if !s.closed {
		s.events <- e
	}
}
func (s *fakeSession) Close() error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if !s.closed {
		close(s.events)
		s.closed = true
	}
	return nil
}

type fakeFactory struct {
	mu       sync.Mutex
	sessions map[string][]*fakeSession
	fail     bool
}

func (f *fakeFactory) Start(ctx context.Context, channel string) (Session, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	if f.fail {
		return nil, errors.New("worker failed")
	}
	s := &fakeSession{events: make(chan Event, 256)}
	f.sessions[channel] = append(f.sessions[channel], s)
	s.events <- Event{'S', []byte("connected")}
	return s, nil
}
func (f *fakeFactory) count(channel string) int {
	f.mu.Lock()
	defer f.mu.Unlock()
	return len(f.sessions[channel])
}
func (f *fakeFactory) current(channel string) *fakeSession {
	f.mu.Lock()
	defer f.mu.Unlock()
	all := f.sessions[channel]
	if len(all) == 0 {
		return nil
	}
	return all[len(all)-1]
}
func setup() (*Runtime, *fakeCloud, *fakeFactory) {
	s, _ := agentstatus.Begin(agentstatus.Stopped(), testID)
	cloud := &fakeCloud{store: &memoryStore{state: s, version: 1}}
	cloud.life.Topic.Namespace = "spBv1.0"
	cloud.life.Topic.DeviceID = testThing
	cloud.life.Topic.MessageType = "DBIRTH"
	cloud.level(2, false)
	factory := &fakeFactory{sessions: make(map[string][]*fakeSession)}
	r := New(testThing, testID, "arn:aws:ecs:r:a:task/c/test", cloud, factory)
	r.Limits = Limits{5 * time.Millisecond, 70 * time.Millisecond, 50 * time.Millisecond, 20 * time.Millisecond, 200 * time.Millisecond, 5 * time.Millisecond, 60 * time.Millisecond, 50 * time.Millisecond}
	return r, cloud, factory
}
func until(t *testing.T, condition func() bool) {
	t.Helper()
	deadline := time.Now().Add(time.Second)
	for !condition() {
		if time.Now().After(deadline) {
			t.Fatal("condition did not converge")
		}
		time.Sleep(time.Millisecond)
	}
}
func begin(t *testing.T, r *Runtime) (context.CancelFunc, <-chan error) {
	t.Helper()
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	finished := make(chan struct{})
	go func() { defer close(finished); done <- r.Run(ctx) }()
	t.Cleanup(func() {
		cancel()
		select {
		case <-finished:
		case <-time.After(time.Second):
			t.Error("runtime did not stop")
		}
	})
	return cancel, done
}
func TestLifecycleIndependentVideoAndObserver(t *testing.T) {
	r, c, f := setup()
	_, _ = begin(t, r)
	until(t, func() bool { return r.Snapshot().MAVLink == "connected" })
	mav := f.current("mavlink")
	signed := []byte{0xfd, 0, 1, 0, 42, 1, 1, 0x12, 0x34, 0x56, 0, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13}
	mav.emit(Event{'B', signed})
	select {
	case e := <-r.Messages:
		if !bytes.Equal(e.Payload, signed) {
			t.Fatal("binary frame altered")
		}
	case <-time.After(time.Second):
		t.Fatal("no observer telemetry")
	}
	mav.mu.Lock()
	sends := mav.sends
	mav.mu.Unlock()
	if sends != 0 {
		t.Fatal("observer acquired lease or transmitted uplink")
	}
	if f.count("video") != 0 {
		t.Fatal("REDCON 2 started video")
	}
	c.level(1, false)
	until(t, func() bool { return r.Snapshot().Video == "connected" })
	f.current("video").emit(Event{'E', []byte("video failed")})
	until(t, func() bool { return f.count("video") >= 2 && r.Snapshot().Video == "connected" })
	if f.current("mavlink") != mav || r.Snapshot().MAVLink != "connected" {
		t.Fatal("video reconnect disrupted MAVLink")
	}
	c.level(2, false)
	until(t, func() bool { return r.Snapshot().Video == "disconnected" })
	if f.count("mavlink") != 1 {
		t.Fatal("REDCON 1->2 restarted MAVLink")
	}
	until(t, func() bool { c.mu.Lock(); defer c.mu.Unlock(); return len(c.reports) > 0 })
	c.mu.Lock()
	defer c.mu.Unlock()
	for _, report := range c.reports {
		if report.UDPListening {
			t.Fatal("observer falsely published UDP readiness")
		}
	}
}
func TestInactiveAndFencedBoundedShutdown(t *testing.T) {
	for _, kind := range []string{"redcon3", "redcon4", "death", "fenced"} {
		t.Run(kind, func(t *testing.T) {
			r, c, f := setup()
			_, done := begin(t, r)
			until(t, func() bool { return r.Snapshot().MAVLink == "connected" })
			switch kind {
			case "redcon3":
				c.level(3, false)
			case "redcon4":
				c.level(4, false)
			case "death":
				c.level(2, true)
			case "fenced":
				c.store.mu.Lock()
				c.store.state = agentstatus.Stopped()
				c.store.version++
				c.store.mu.Unlock()
			}
			select {
			case err := <-done:
				if !errors.Is(err, agentstatus.ErrStaleTask) {
					t.Fatalf("unexpected shutdown: %v", err)
				}
			case <-time.After(time.Second):
				t.Fatal("unbounded inactive shutdown")
			}
			mav := f.current("mavlink")
			mav.mu.Lock()
			closed := mav.closed
			mav.mu.Unlock()
			if !closed {
				t.Fatal("worker survived lifecycle shutdown")
			}
		})
	}
}
func TestAuthorityOutageAndBlockedReporterDoNotBlockSessions(t *testing.T) {
	r, c, f := setup()
	c.onReport = func(ctx context.Context, _ controller.Readiness) error { <-ctx.Done(); return ctx.Err() }
	_, done := begin(t, r)
	until(t, func() bool { return r.Snapshot().MAVLink == "connected" })
	f.current("mavlink").emit(Event{'J', []byte(`{"op":"control.status"}`)})
	select {
	case <-r.Messages:
	case <-time.After(time.Second):
		t.Fatal("reporting blocked MAVLink")
	}
	c.mu.Lock()
	c.err = errors.New("shadow unavailable")
	c.mu.Unlock()
	select {
	case err := <-done:
		if err == nil {
			t.Fatal("unverified task stayed live")
		}
	case <-time.After(time.Second):
		t.Fatal("unverified deadline not enforced")
	}
}
func TestNoViewerStartsWithoutAuthority(t *testing.T) {
	for _, level := range []int{0, 3, 4} {
		r, c, f := setup()
		c.level(level, false)
		if err := r.Run(context.Background()); !errors.Is(err, agentstatus.ErrStaleTask) {
			t.Fatal(err)
		}
		if f.count("mavlink") != 0 || f.count("video") != 0 {
			t.Fatal("inactive task started viewer")
		}
	}
}
func TestFreshReadinessAfterConflictAndVideoError(t *testing.T) {
	r, c, _ := setup()
	r.state("mavlink", "connected", "")
	r.state("video", "connected", "")
	calls := 0
	c.onReport = func(_ context.Context, report controller.Readiness) error {
		calls++
		if calls == 1 {
			c.store.mu.Lock()
			c.store.version++
			c.store.mu.Unlock()
			r.state("video", "error", "video failure")
			return agentstatus.ErrVersionConflict
		}
		if report.Video != "error" {
			t.Fatal("retried obsolete snapshot")
		}
		_, version, _ := c.store.Read(context.Background())
		if report.ShadowVersion != version {
			t.Fatal("reused stale shadow version")
		}
		return nil
	}
	if err := r.report(context.Background()); err != nil {
		t.Fatal(err)
	}
	if calls != 2 {
		t.Fatal("missing bounded fresh retry")
	}
	// A connection update never converts a healthy MAVLink task to task error.
	if err := r.report(context.Background()); err != nil {
		t.Fatal(err)
	}
	state, _, _ := c.store.Read(context.Background())
	if state.Task.Status == "error" || state.MAVLink != "connected" || state.LastError == nil {
		t.Fatalf("video failure disturbed MAVLink status: %+v", state)
	}
}
func TestRetryCooldownAndQueueBounds(t *testing.T) {
	limits := DefaultLimits()
	for _, failure := range []int{3, 4, 100} {
		if retryDelay(failure, limits) != time.Minute {
			t.Fatal("missing reconnect cooldown")
		}
	}
	r, _, f := setup()
	_, _ = begin(t, r)
	until(t, func() bool { return r.Snapshot().MAVLink == "connected" })
	mav := f.current("mavlink")
	for i := 0; i < 65; i++ {
		mav.emit(Event{'B', []byte{0xfd}})
	}
	until(t, func() bool { return f.count("mavlink") >= 2 })
	if len(r.Messages) > 64 {
		t.Fatal("receive queue exceeded bound")
	}
}
