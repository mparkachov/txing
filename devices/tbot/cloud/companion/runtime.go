// Package companion manages independent, receive-only KVS viewer sessions.
package companion

import (
	"context"
	"errors"
	"fmt"
	"sync"
	"time"

	"github.com/mparkachov/txing/devices/tbot/cloud/agentstatus"
	"github.com/mparkachov/txing/devices/tbot/cloud/controller"
)

type Event struct {
	Kind    byte
	Payload []byte
}

// Session supports the future UDP/control bridge. The observer runtime never calls Send.
type Session interface {
	Events() <-chan Event
	Send(context.Context, byte, []byte) error
	Close() error
}
type Factory interface {
	Start(context.Context, string) (Session, error)
}
type Cloud interface {
	Lifecycle(context.Context) (controller.Lifecycle, error)
	Store() agentstatus.Store
	Readiness(context.Context, controller.Readiness) error
}
type Snapshot struct{ MAVLink, Video, LastError string }
type Limits struct{ Poll, Unverified, Negotiate, Report, Shutdown, Backoff, Cooldown, Stable time.Duration }

func DefaultLimits() Limits {
	return Limits{2 * time.Second, 15 * time.Second, 45 * time.Second, 30 * time.Second, 10 * time.Second, time.Second, time.Minute, 30 * time.Second}
}

type Runtime struct {
	Thing, ID, ARN string
	Cloud          Cloud
	Factory        Factory
	Limits         Limits
	// Messages receives binary MAVLink frames and JSON lease envelopes unchanged.
	// Consumers must drain it; saturation fails only the MAVLink session.
	Messages chan Event
	mu       sync.Mutex
	states   map[string]string
	errs     map[string]string
	sessions map[string]Session
	changed  chan struct{}
}

func New(thing, id, arn string, c Cloud, f Factory) *Runtime {
	return &Runtime{Thing: thing, ID: id, ARN: arn, Cloud: c, Factory: f, Limits: DefaultLimits(), Messages: make(chan Event, 64), states: map[string]string{"mavlink": "disconnected", "video": "disconnected"}, errs: make(map[string]string), sessions: make(map[string]Session), changed: make(chan struct{}, 1)}
}
func (r *Runtime) Snapshot() Snapshot {
	r.mu.Lock()
	defer r.mu.Unlock()
	// MAVLink failures take precedence, while video errors remain visible.
	err := r.errs["mavlink"]
	if err == "" {
		err = r.errs["video"]
	}
	if err == "" {
		err = r.errs["lifecycle"]
	}
	return Snapshot{r.states["mavlink"], r.states["video"], err}
}
func (r *Runtime) state(channel, state, message string) {
	r.mu.Lock()
	r.states[channel] = state
	r.errs[channel] = message
	r.mu.Unlock()
	select {
	case r.changed <- struct{}{}:
	default:
	}
}
func (r *Runtime) Send(ctx context.Context, kind byte, payload []byte) error {
	if kind != 'B' && kind != 'J' {
		return errors.New("unsupported data-channel message type")
	}
	r.mu.Lock()
	s := r.sessions["mavlink"]
	connected := r.states["mavlink"] == "connected"
	r.mu.Unlock()
	if s == nil || !connected {
		return errors.New("MAVLink viewer is not connected")
	}
	return s.Send(ctx, kind, payload)
}
func wait(ctx context.Context, d time.Duration) bool {
	t := time.NewTimer(d)
	defer t.Stop()
	select {
	case <-ctx.Done():
		return false
	case <-t.C:
		return true
	}
}

// retryDelay bounds connection churn independently for each viewer.
func retryDelay(failures int, l Limits) time.Duration {
	if failures >= 3 {
		return l.Cooldown
	}
	return min(l.Backoff*time.Duration(1<<uint(max(0, failures-1))), 30*time.Second)
}
func (r *Runtime) supervise(ctx context.Context, channel string) {
	failures := 0
	defer r.state(channel, "disconnected", "")
	for ctx.Err() == nil {
		r.state(channel, "connecting", "")
		session, err := r.Factory.Start(ctx, channel)
		connectedAt := time.Time{}
		if err == nil {
			r.mu.Lock()
			r.sessions[channel] = session
			r.mu.Unlock()
			deadline := time.NewTimer(r.Limits.Negotiate)
		loop:
			for {
				select {
				case <-ctx.Done():
					break loop
				case <-deadline.C:
					err = errors.New("viewer negotiation timed out")
					break loop
				case e, ok := <-session.Events():
					if !ok {
						err = errors.New("viewer worker exited")
						break loop
					}
					switch e.Kind {
					case 'S':
						if string(e.Payload) == "connected" {
							if connectedAt.IsZero() {
								connectedAt = time.Now()
							}
							deadline.Stop()
							r.state(channel, "connected", "")
						} else {
							err = errors.New("viewer disconnected")
							break loop
						}
					case 'E':
						err = fmt.Errorf("viewer: %s", e.Payload)
						break loop
					case 'B', 'J':
						if channel != "mavlink" {
							err = errors.New("unexpected video data channel")
							break loop
						}
						select {
						case r.Messages <- e:
						default:
							err = errors.New("MAVLink receive queue full")
							break loop
						}
					}
				}
			}
			deadline.Stop()
			// Fence sends before releasing the native resources.
			r.mu.Lock()
			delete(r.sessions, channel)
			r.mu.Unlock()
			r.state(channel, "disconnected", "")
			_ = session.Close()
		}
		if ctx.Err() != nil {
			return
		}
		if !connectedAt.IsZero() && time.Since(connectedAt) >= r.Limits.Stable {
			failures = 0
		}
		failures++
		message := channel + " connection failed"
		if err != nil {
			message = channel + ": " + err.Error()
		}
		r.state(channel, "error", message)
		if !wait(ctx, retryDelay(failures, r.Limits)) {
			return
		}
		if failures >= 3 {
			failures = 0
		}
	}
}
func (r *Runtime) verify(ctx context.Context) (int, error) {
	// Reads are bounded by the caller; no session exists until both authorities agree.
	state, err := r.Cloud.Lifecycle(ctx)
	if err != nil {
		return 0, err
	}
	if !state.Active(r.Thing) {
		return 0, agentstatus.ErrStaleTask
	}
	shadow, _, err := r.Cloud.Store().Read(ctx)
	if err != nil {
		return 0, err
	}
	if shadow.Task.ID == nil || *shadow.Task.ID != r.ID || (shadow.Task.Status != "starting" && shadow.Task.Status != "ready") {
		return 0, agentstatus.ErrStaleTask
	}
	return state.Payload.Metrics.REDCON, nil
}
func (r *Runtime) report(ctx context.Context) error {
	// Update resamples after every conflict. Only connection/error fields belong to the task.
	err := agentstatus.Update(ctx, r.Cloud.Store(), func(current agentstatus.Reported) (agentstatus.Reported, error) {
		s := r.Snapshot()
		var err error
		current, err = agentstatus.Connection(current, r.ID, "mavlink", s.MAVLink)
		if err != nil {
			return current, err
		}
		current, err = agentstatus.Connection(current, r.ID, "video", s.Video)
		if err != nil {
			return current, err
		}
		current.LastError = nil
		if s.LastError != "" {
			message := s.LastError
			current.LastError = &message
		}
		return current, nil
	})
	if err != nil {
		return err
	}
	for attempt := 0; attempt < 3; attempt++ {
		shadow, version, err := r.Cloud.Store().Read(ctx)
		if err != nil {
			return err
		}
		if shadow.Task.ID == nil || *shadow.Task.ID != r.ID || shadow.Task.Status == "stopped" {
			return agentstatus.ErrStaleTask
		}
		s := r.Snapshot() // Fresh snapshot AFTER reading its version, including on every retry.
		err = r.Cloud.Readiness(ctx, controller.Readiness{ID: r.ID, TaskARN: r.ARN, ShadowVersion: version, UDPListening: false, MAVLink: s.MAVLink, Video: s.Video})
		if err == nil || errors.Is(err, agentstatus.ErrStaleTask) {
			return err
		}
	}
	return errors.New("readiness reporting failed after three fresh attempts")
}
func (r *Runtime) Run(parent context.Context) error {
	ctx, cancel := context.WithCancel(parent)
	defer cancel()
	verifyCtx, stop := context.WithTimeout(ctx, 4*time.Second)
	level, err := r.verify(verifyCtx)
	stop()
	if err != nil {
		return err
	}
	var wg sync.WaitGroup
	launch := func(fn func()) { wg.Add(1); go func() { defer wg.Done(); fn() }() }
	launch(func() { r.supervise(ctx, "mavlink") })
	var videoCancel context.CancelFunc
	var videoDone <-chan struct{}
	startVideo := func() {
		if videoCancel != nil {
			return
		}
		vc, cc := context.WithCancel(ctx)
		videoCancel = cc
		done := make(chan struct{})
		videoDone = done
		launch(func() { defer close(done); r.supervise(vc, "video") })
	}
	stopVideo := func() {
		if videoCancel != nil {
			videoCancel()
		}
	}
	if level == 1 {
		startVideo()
	}
	levels := make(chan int, 1)
	fatal := make(chan error, 2)
	lastGood := time.Now()
	var verifiedMu sync.Mutex
	launch(func() {
		tick := time.NewTicker(r.Limits.Poll)
		defer tick.Stop()
		for {
			select {
			case <-ctx.Done():
				return
			case <-tick.C:
				call, cc := context.WithTimeout(ctx, 4*time.Second)
				next, e := r.verify(call)
				cc()
				if errors.Is(e, agentstatus.ErrStaleTask) {
					select {
					case fatal <- e:
					default:
					}
					return
				}
				if e != nil {
					r.mu.Lock()
					r.errs["lifecycle"] = "lifecycle or assigned task identity cannot be verified"
					r.mu.Unlock()
					select {
					case r.changed <- struct{}{}:
					default:
					}
				}
				if e == nil {
					verifiedMu.Lock()
					lastGood = time.Now()
					verifiedMu.Unlock()
					r.mu.Lock()
					delete(r.errs, "lifecycle")
					r.mu.Unlock()
					select {
					case levels <- next:
					default:
					}
				}
			}
		}
	})
	launch(func() {
		tick := time.NewTicker(r.Limits.Report)
		defer tick.Stop()
		for {
			select {
			case <-ctx.Done():
				return
			case <-r.changed:
			case <-tick.C:
			}
			call, cc := context.WithTimeout(ctx, 8*time.Second)
			e := r.report(call)
			cc()
			if errors.Is(e, agentstatus.ErrStaleTask) {
				select {
				case fatal <- e:
				default:
				}
				return
			}
		}
	})
	watchdog := time.NewTicker(min(r.Limits.Poll, 100*time.Millisecond))
	defer watchdog.Stop()
run:
	for {
		select {
		case <-parent.Done():
			err = parent.Err()
			break run
		case err = <-fatal:
			break run
		case level = <-levels:
			if level == 1 {
				if videoCancel == nil {
					startVideo()
				}
			} else {
				stopVideo()
			}
		case <-videoDone:
			videoCancel = nil
			videoDone = nil
			if level == 1 {
				startVideo()
			}
		case <-watchdog.C:
			verifiedMu.Lock()
			stale := time.Since(lastGood) >= r.Limits.Unverified
			verifiedMu.Unlock()
			if stale {
				err = errors.New("lifecycle or task identity unverified for its deadline")
				break run
			}
		}
	}
	shutdown, shutdownCancel := context.WithTimeout(context.Background(), r.Limits.Shutdown)
	defer shutdownCancel()
	cancel()
	stopVideo()
	done := make(chan struct{})
	go func() { wg.Wait(); close(done) }()
	select {
	case <-done:
	case <-shutdown.Done():
		return errors.New("companion shutdown exceeded deadline")
	}
	// Connection cleanup is still fenced. A stopped/replaced task cannot restore state.
	final, cc := context.WithTimeout(shutdown, 2*time.Second)
	defer cc()
	_ = agentstatus.Update(final, r.Cloud.Store(), func(current agentstatus.Reported) (agentstatus.Reported, error) {
		current, e := agentstatus.Connection(current, r.ID, "mavlink", "disconnected")
		if e != nil {
			return current, e
		}
		return agentstatus.Connection(current, r.ID, "video", "disconnected")
	})
	return err
}
