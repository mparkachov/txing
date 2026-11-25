package controller

import (
	"context"
	"encoding/json"
	"errors"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/aws/aws-lambda-go/lambdacontext"
	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/service/iotdataplane"
	"github.com/aws/aws-sdk-go-v2/service/iotdataplane/types"
	"txing.dev/virtual-quad-lambda/internal/lifecycle"
	"txing.dev/virtual-quad-lambda/internal/session"
)

type lambdaShadow struct {
	mu           sync.Mutex
	version      int64
	state        session.State
	publications int
}

type fakeSimulator struct {
	done    chan struct{}
	stopped chan struct{}
}

func (f *fakeSimulator) Done() <-chan struct{} { return f.done }
func (f *fakeSimulator) Err() error            { return nil }
func (f *fakeSimulator) Stop() error           { close(f.stopped); return nil }
func (f *fakeSimulator) Health() session.Health {
	return session.Health{Heartbeat: true, Navigation: true, Mavlink: true, Video: true}
}

func TestStartInvocationOwnsWorkloadUntilStopNotification(t *testing.T) {
	client := &lambdaShadow{version: 1, state: session.State{Phase: "stopped"}}
	h := NewLambdaHandler(aws.Config{}, "example.test", testRegistry{awake: true}, client)
	events := make(chan session.Notification, 4)
	events <- session.Subscribed
	h.subscribe = func(context.Context, aws.Config, string, string, string, string) (<-chan session.Notification, func(), error) {
		return events, func() {}, nil
	}
	workload := &fakeSimulator{done: make(chan struct{}), stopped: make(chan struct{})}
	started := make(chan struct{})
	h.startWorkload = func(string, string) (simulator, error) { close(started); return workload, nil }
	ctx, cancel := context.WithTimeout(t.Context(), 900*time.Second)
	defer cancel()
	ctx = lambdacontext.NewContext(ctx, &lambdacontext.LambdaContext{AwsRequestID: "owner-1"})
	done := make(chan error, 1)
	go func() {
		done <- h.command(ctx, lambdaEvent{Topic: commandTopic, Payload: encodeTestCommand(1, startID, revisionMetric, "0")})
	}()
	select {
	case <-started:
	case <-time.After(time.Second):
		t.Fatal("workload did not start")
	}
	if err := h.command(ctx, lambdaEvent{Topic: commandTopic, Payload: encodeTestCommand(4, stopID, sessionMetric, startID)}); err != nil {
		t.Fatal(err)
	}
	events <- session.Updated
	select {
	case err := <-done:
		if err != nil {
			t.Fatal(err)
		}
	case <-time.After(time.Second):
		t.Fatal("Start invocation did not stop")
	}
	select {
	case <-workload.stopped:
	default:
		t.Fatal("supervisor was not stopped")
	}
	client.mu.Lock()
	defer client.mu.Unlock()
	if client.state.Phase != "stopped" || client.state.Run != nil || client.state.TerminalRevision != 1 || client.state.Receipt.Status != "succeeded" {
		t.Fatalf("unexpected terminal shadow: %+v", client.state)
	}
}

func TestStopDuringSubscriptionPreventsWorkloadLaunch(t *testing.T) {
	now := time.Now().UnixMilli()
	s := session.State{Phase: "stopped"}
	if err := s.Start(startID, "owner-1", "town-test", "cloud-test", 25, 0, now, now+900_000); err != nil {
		t.Fatal(err)
	}
	client := &lambdaShadow{version: 1, state: s}
	h := NewLambdaHandler(aws.Config{}, "example.test", testRegistry{awake: true}, client)
	events := make(chan session.Notification, 1)
	subscribing := make(chan struct{})
	h.subscribe = func(context.Context, aws.Config, string, string, string, string) (<-chan session.Notification, func(), error) {
		close(subscribing)
		return events, func() {}, nil
	}
	launched := false
	h.startWorkload = func(string, string) (simulator, error) { launched = true; return nil, errors.New("unexpected launch") }
	done := make(chan error, 1)
	go func() { done <- h.run(t.Context(), testAssignment, "owner-1") }()
	select {
	case <-subscribing:
	case <-time.After(time.Second):
		t.Fatal("subscription did not begin")
	}
	if err := h.command(t.Context(), lambdaEvent{Topic: commandTopic, Payload: encodeTestCommand(4, stopID, sessionMetric, startID)}); err != nil {
		t.Fatal(err)
	}
	events <- session.Subscribed
	select {
	case err := <-done:
		if err != nil {
			t.Fatal(err)
		}
	case <-time.After(time.Second):
		t.Fatal("startup did not stop")
	}
	if launched {
		t.Fatal("SITL was launched after Stop")
	}
	client.mu.Lock()
	defer client.mu.Unlock()
	if client.state.Phase != "stopped" || client.state.Receipt == nil || client.state.Receipt.Status != "succeeded" {
		t.Fatalf("unexpected terminal shadow: %+v", client.state)
	}
}

func TestDisconnectedNotificationsStopRunningWorkload(t *testing.T) {
	now := time.Now().UnixMilli()
	s := session.State{Phase: "stopped"}
	if err := s.Start(startID, "owner-1", "town-test", "cloud-test", 25, 0, now, now+900_000); err != nil {
		t.Fatal(err)
	}
	client := &lambdaShadow{version: 1, state: s}
	h := NewLambdaHandler(aws.Config{}, "example.test", testRegistry{awake: true}, client)
	h.reconnectLimit = 100 * time.Millisecond
	events := make(chan session.Notification, 2)
	events <- session.Subscribed
	h.subscribe = func(context.Context, aws.Config, string, string, string, string) (<-chan session.Notification, func(), error) {
		return events, func() {}, nil
	}
	workload := &fakeSimulator{done: make(chan struct{}), stopped: make(chan struct{})}
	started := make(chan struct{})
	h.startWorkload = func(string, string) (simulator, error) { close(started); return workload, nil }
	done := make(chan error, 1)
	go func() { done <- h.run(t.Context(), testAssignment, "owner-1") }()
	select {
	case <-started:
	case <-time.After(time.Second):
		t.Fatal("workload did not start")
	}
	events <- session.Disconnected
	select {
	case err := <-done:
		if err == nil {
			t.Fatal("disconnect was not reported")
		}
	case <-time.After(time.Second):
		t.Fatal("disconnect did not stop workload")
	}
	select {
	case <-workload.stopped:
	default:
		t.Fatal("supervisor was not stopped")
	}
	client.mu.Lock()
	defer client.mu.Unlock()
	if client.state.Phase != "failed" || client.state.Run != nil {
		t.Fatalf("disconnect did not finalize session: %+v", client.state)
	}
}

func TestReconnectRechecksMissedStop(t *testing.T) {
	now := time.Now().UnixMilli()
	s := session.State{Phase: "stopped"}
	if err := s.Start(startID, "owner-1", "town-test", "cloud-test", 25, 0, now, now+900_000); err != nil {
		t.Fatal(err)
	}
	client := &lambdaShadow{version: 1, state: s}
	h := NewLambdaHandler(aws.Config{}, "example.test", testRegistry{awake: true}, client)
	h.reconnectLimit = time.Second
	events := make(chan session.Notification, 4)
	events <- session.Subscribed
	h.subscribe = func(context.Context, aws.Config, string, string, string, string) (<-chan session.Notification, func(), error) {
		return events, func() {}, nil
	}
	workload := &fakeSimulator{done: make(chan struct{}), stopped: make(chan struct{})}
	started := make(chan struct{})
	h.startWorkload = func(string, string) (simulator, error) { close(started); return workload, nil }
	done := make(chan error, 1)
	go func() { done <- h.run(t.Context(), testAssignment, "owner-1") }()
	select {
	case <-started:
	case <-time.After(time.Second):
		t.Fatal("workload did not start")
	}
	events <- session.Disconnected
	if err := h.command(t.Context(), lambdaEvent{Topic: commandTopic, Payload: encodeTestCommand(4, stopID, sessionMetric, startID)}); err != nil {
		t.Fatal(err)
	}
	// No update notification is delivered for the Stop while disconnected.
	events <- session.Subscribed
	select {
	case err := <-done:
		if err != nil {
			t.Fatal(err)
		}
	case <-time.After(time.Second):
		t.Fatal("reconnection did not observe the missed Stop")
	}
	select {
	case <-workload.stopped:
	default:
		t.Fatal("supervisor was not stopped")
	}
	client.mu.Lock()
	defer client.mu.Unlock()
	if client.state.Phase != "stopped" || client.state.Receipt == nil || client.state.Receipt.Status != "succeeded" {
		t.Fatalf("wrong terminal shadow: %+v", client.state)
	}
}

func TestReconnectStopsBeforeReadinessExpires(t *testing.T) {
	now := time.Now()
	s := session.State{Phase: "stopped"}
	if err := s.Start(startID, "owner-1", "town-test", "cloud-test", 25, 0, now.UnixMilli(), now.Add(15*time.Minute).UnixMilli()); err != nil {
		t.Fatal(err)
	}
	if err := s.UpdateHealth("owner-1", session.Health{Heartbeat: true, Navigation: true, Mavlink: true, Video: true}, now.UnixMilli()+1); err != nil {
		t.Fatal(err)
	}
	expiry := now.Add(1200 * time.Millisecond).UnixMilli()
	s.AvailabilityExpires = &expiry
	client := &lambdaShadow{version: 1, state: s}
	h := NewLambdaHandler(aws.Config{}, "example.test", testRegistry{awake: true}, client)
	h.reconnectLimit = 2 * time.Second
	events := make(chan session.Notification, 2)
	events <- session.Subscribed
	h.subscribe = func(context.Context, aws.Config, string, string, string, string) (<-chan session.Notification, func(), error) {
		return events, func() {}, nil
	}
	workload := &fakeSimulator{done: make(chan struct{}), stopped: make(chan struct{})}
	started := make(chan struct{})
	h.startWorkload = func(string, string) (simulator, error) { close(started); return workload, nil }
	done := make(chan error, 1)
	go func() { done <- h.run(t.Context(), testAssignment, "owner-1") }()
	select {
	case <-started:
	case <-time.After(time.Second):
		t.Fatal("workload did not start")
	}
	events <- session.Disconnected
	select {
	case err := <-done:
		if err == nil {
			t.Fatal("expired reconnect was not reported")
		}
	case <-time.After(900 * time.Millisecond):
		t.Fatal("reconnect waited beyond the readiness safety margin")
	}
	select {
	case <-workload.stopped:
	default:
		t.Fatal("supervisor was not stopped")
	}
}

func TestReconnectCannotFinishReplacementSession(t *testing.T) {
	now := time.Now().UnixMilli()
	s := session.State{Phase: "stopped"}
	if err := s.Start(startID, "owner-1", "town-test", "cloud-test", 25, 0, now, now+900_000); err != nil {
		t.Fatal(err)
	}
	client := &lambdaShadow{version: 1, state: s}
	h := NewLambdaHandler(aws.Config{}, "example.test", testRegistry{awake: true}, client)
	h.reconnectLimit = time.Second
	events := make(chan session.Notification, 4)
	events <- session.Subscribed
	h.subscribe = func(context.Context, aws.Config, string, string, string, string) (<-chan session.Notification, func(), error) {
		return events, func() {}, nil
	}
	workload := &fakeSimulator{done: make(chan struct{}), stopped: make(chan struct{})}
	started := make(chan struct{})
	h.startWorkload = func(string, string) (simulator, error) { close(started); return workload, nil }
	done := make(chan error, 1)
	go func() { done <- h.run(t.Context(), testAssignment, "owner-1") }()
	select {
	case <-started:
	case <-time.After(time.Second):
		t.Fatal("workload did not start")
	}
	events <- session.Disconnected
	client.mu.Lock()
	if err := client.state.Finish("owner-1", "failed", "owner expired", now+1); err != nil {
		client.mu.Unlock()
		t.Fatal(err)
	}
	if err := client.state.Start("replacement", "owner-2", "town-test", "cloud-test", 26, 1, now+2, now+900_002); err != nil {
		client.mu.Unlock()
		t.Fatal(err)
	}
	client.version++
	client.mu.Unlock()
	events <- session.Subscribed
	select {
	case err := <-done:
		if !errors.Is(err, session.ErrNotOwner) {
			t.Fatalf("old owner did not stop after replacement: %v", err)
		}
	case <-time.After(time.Second):
		t.Fatal("old owner did not observe replacement")
	}
	client.mu.Lock()
	defer client.mu.Unlock()
	if client.state.Phase != "starting" || client.state.Run == nil || client.state.Run.Owner != "owner-2" || client.state.TerminalRevision != 1 {
		t.Fatalf("old invocation changed replacement: %+v", client.state)
	}
	select {
	case <-workload.stopped:
	default:
		t.Fatal("old supervisor was not stopped")
	}
}

func TestReconnectPausesAndResumesHealth(t *testing.T) {
	now := time.Now().UnixMilli()
	s := session.State{Phase: "stopped"}
	if err := s.Start(startID, "owner-1", "town-test", "cloud-test", 25, 0, now, now+900_000); err != nil {
		t.Fatal(err)
	}
	client := &lambdaShadow{version: 1, state: s}
	h := NewLambdaHandler(aws.Config{}, "example.test", testRegistry{awake: true}, client)
	h.reconnectLimit, h.healthInterval = 700*time.Millisecond, 20*time.Millisecond
	events := make(chan session.Notification, 4)
	events <- session.Subscribed
	h.subscribe = func(context.Context, aws.Config, string, string, string, string) (<-chan session.Notification, func(), error) {
		return events, func() {}, nil
	}
	workload := &fakeSimulator{done: make(chan struct{}), stopped: make(chan struct{})}
	started := make(chan struct{})
	h.startWorkload = func(string, string) (simulator, error) { close(started); return workload, nil }
	done := make(chan error, 1)
	go func() { done <- h.run(t.Context(), testAssignment, "owner-1") }()
	select {
	case <-started:
	case <-time.After(time.Second):
		t.Fatal("workload did not start")
	}
	time.Sleep(80 * time.Millisecond)
	events <- session.Disconnected
	time.Sleep(80 * time.Millisecond)
	client.mu.Lock()
	version := client.version
	client.mu.Unlock()
	time.Sleep(100 * time.Millisecond)
	client.mu.Lock()
	pausedVersion := client.version
	client.mu.Unlock()
	if pausedVersion != version {
		t.Fatal("health was renewed while notifications were disconnected")
	}
	events <- session.Subscribed
	time.Sleep(100 * time.Millisecond)
	client.mu.Lock()
	resumedVersion, phase := client.version, client.state.Phase
	client.mu.Unlock()
	if resumedVersion <= pausedVersion || phase != "operational" {
		t.Fatalf("health did not resume after revalidation: version %d -> %d, phase %s", pausedVersion, resumedVersion, phase)
	}
	if err := h.command(t.Context(), lambdaEvent{Topic: commandTopic, Payload: encodeTestCommand(4, stopID, sessionMetric, startID)}); err != nil {
		t.Fatal(err)
	}
	events <- session.Updated
	select {
	case err := <-done:
		if err != nil {
			t.Fatal(err)
		}
	case <-time.After(time.Second):
		t.Fatal("reconnected invocation did not stop")
	}
}

func TestStartupDeadlineStopsWorkloadWithoutWaitingForHealthTick(t *testing.T) {
	now := time.Now()
	s := session.State{Phase: "stopped"}
	if err := s.Start(startID, "owner-1", "town-test", "cloud-test", 25, 0, now.UnixMilli(), now.Add(15*time.Minute).UnixMilli()); err != nil {
		t.Fatal(err)
	}
	cutoff := now.Add(100 * time.Millisecond).UnixMilli()
	s.StartupDeadline = &cutoff
	client := &lambdaShadow{version: 1, state: s}
	h := NewLambdaHandler(aws.Config{}, "example.test", testRegistry{awake: true}, client)
	events := make(chan session.Notification, 1)
	events <- session.Subscribed
	h.subscribe = func(context.Context, aws.Config, string, string, string, string) (<-chan session.Notification, func(), error) {
		return events, func() {}, nil
	}
	workload := &fakeSimulator{done: make(chan struct{}), stopped: make(chan struct{})}
	h.startWorkload = func(string, string) (simulator, error) { return workload, nil }
	done := make(chan error, 1)
	go func() { done <- h.run(t.Context(), testAssignment, "owner-1") }()
	select {
	case err := <-done:
		if err != nil {
			t.Fatal(err)
		}
	case <-time.After(time.Second):
		t.Fatal("startup cutoff waited for the five-second health tick")
	}
	select {
	case <-workload.stopped:
	default:
		t.Fatal("supervisor was not stopped")
	}
	client.mu.Lock()
	defer client.mu.Unlock()
	if client.state.Phase != "failed" || client.state.LastReason == nil || *client.state.LastReason != "startup deadline exceeded" {
		t.Fatalf("wrong terminal outcome: %+v", client.state)
	}
}

func TestFlightDeadlineStopsWorkloadWithoutWaitingForHealthTick(t *testing.T) {
	now := time.Now()
	s := session.State{Phase: "stopped"}
	if err := s.Start(startID, "owner-1", "town-test", "cloud-test", 25, 0, now.UnixMilli(), now.Add(15*time.Minute).UnixMilli()); err != nil {
		t.Fatal(err)
	}
	if err := s.UpdateHealth("owner-1", session.Health{Heartbeat: true, Navigation: true, Mavlink: true, Video: true}, now.UnixMilli()+1); err != nil {
		t.Fatal(err)
	}
	cutoff := now.Add(100 * time.Millisecond).UnixMilli()
	s.FlightDeadline = &cutoff
	client := &lambdaShadow{version: 1, state: s}
	h := NewLambdaHandler(aws.Config{}, "example.test", testRegistry{awake: true}, client)
	events := make(chan session.Notification, 1)
	events <- session.Subscribed
	h.subscribe = func(context.Context, aws.Config, string, string, string, string) (<-chan session.Notification, func(), error) {
		return events, func() {}, nil
	}
	workload := &fakeSimulator{done: make(chan struct{}), stopped: make(chan struct{})}
	h.startWorkload = func(string, string) (simulator, error) { return workload, nil }
	done := make(chan error, 1)
	go func() { done <- h.run(t.Context(), testAssignment, "owner-1") }()
	select {
	case err := <-done:
		if err != nil {
			t.Fatal(err)
		}
	case <-time.After(time.Second):
		t.Fatal("flight cutoff waited for the five-second health tick")
	}
	select {
	case <-workload.stopped:
	default:
		t.Fatal("supervisor was not stopped")
	}
	client.mu.Lock()
	defer client.mu.Unlock()
	if client.state.Phase != "stopped" || client.state.LastReason == nil || *client.state.LastReason != "flight deadline reached" {
		t.Fatalf("wrong terminal outcome: %+v", client.state)
	}
}

type deadlineRegistry struct {
	calls   atomic.Int32
	blocked chan struct{}
}

func (r *deadlineRegistry) Assignment(ctx context.Context, _ string) (lifecycle.Assignment, bool, error) {
	if r.calls.Add(1) == 1 {
		return testAssignment, true, nil
	}
	close(r.blocked)
	<-ctx.Done()
	return lifecycle.Assignment{}, false, ctx.Err()
}

func TestFlightDeadlineCancelsBlockedRigRead(t *testing.T) {
	now := time.Now()
	s := session.State{Phase: "stopped"}
	if err := s.Start(startID, "owner-1", "town-test", "cloud-test", 25, 0, now.UnixMilli(), now.Add(15*time.Minute).UnixMilli()); err != nil {
		t.Fatal(err)
	}
	if err := s.UpdateHealth("owner-1", session.Health{Heartbeat: true, Navigation: true, Mavlink: true, Video: true}, now.UnixMilli()+1); err != nil {
		t.Fatal(err)
	}
	cutoff := now.Add(200 * time.Millisecond).UnixMilli()
	s.FlightDeadline = &cutoff
	client := &lambdaShadow{version: 1, state: s}
	registry := &deadlineRegistry{blocked: make(chan struct{})}
	h := NewLambdaHandler(aws.Config{}, "example.test", registry, client)
	events := make(chan session.Notification, 2)
	events <- session.Subscribed
	h.subscribe = func(context.Context, aws.Config, string, string, string, string) (<-chan session.Notification, func(), error) {
		return events, func() {}, nil
	}
	workload := &fakeSimulator{done: make(chan struct{}), stopped: make(chan struct{})}
	started := make(chan struct{})
	h.startWorkload = func(string, string) (simulator, error) { close(started); return workload, nil }
	done := make(chan error, 1)
	go func() { done <- h.run(t.Context(), testAssignment, "owner-1") }()
	select {
	case <-started:
	case <-time.After(time.Second):
		t.Fatal("workload did not start")
	}
	events <- session.RigUpdated
	select {
	case <-registry.blocked:
	case <-time.After(time.Second):
		t.Fatal("rig read did not start")
	}
	select {
	case err := <-done:
		if err != nil {
			t.Fatal(err)
		}
	case <-time.After(time.Second):
		t.Fatal("flight cutoff did not cancel the blocked rig read")
	}
	select {
	case <-workload.stopped:
	default:
		t.Fatal("supervisor was not stopped")
	}
	client.mu.Lock()
	defer client.mu.Unlock()
	if client.state.Phase != "stopped" || client.state.LastReason == nil || *client.state.LastReason != "flight deadline reached" {
		t.Fatalf("wrong terminal outcome: %+v", client.state)
	}
}

func (s *lambdaShadow) GetThingShadow(_ context.Context, in *iotdataplane.GetThingShadowInput, _ ...func(*iotdataplane.Options)) (*iotdataplane.GetThingShadowOutput, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	var payload []byte
	if aws.ToString(in.ShadowName) == "sparkplug" {
		payload, _ = json.Marshal(map[string]any{"version": 1, "state": map[string]any{"reported": map[string]any{
			"topic":   map[string]any{"namespace": "spBv1.0", "messageType": "DBIRTH", "groupId": "town-test", "edgeNodeId": "cloud-test", "deviceId": "virtual-quad-test"},
			"payload": map[string]any{"timestamp": 1},
		}}})
	} else {
		payload, _ = json.Marshal(map[string]any{"version": s.version, "state": map[string]any{"reported": s.state}})
	}
	return &iotdataplane.GetThingShadowOutput{Payload: payload}, nil
}

func (s *lambdaShadow) UpdateThingShadow(_ context.Context, in *iotdataplane.UpdateThingShadowInput, _ ...func(*iotdataplane.Options)) (*iotdataplane.UpdateThingShadowOutput, error) {
	var doc struct {
		Version int64 `json:"version"`
		State   struct {
			Reported session.State `json:"reported"`
		} `json:"state"`
	}
	if err := json.Unmarshal(in.Payload, &doc); err != nil {
		return nil, err
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	if doc.Version != s.version {
		return nil, &types.ConflictException{}
	}
	s.version++
	s.state = doc.State.Reported
	return &iotdataplane.UpdateThingShadowOutput{}, nil
}

func (s *lambdaShadow) Publish(_ context.Context, in *iotdataplane.PublishInput, _ ...func(*iotdataplane.Options)) (*iotdataplane.PublishOutput, error) {
	if aws.ToString(in.Topic) != "spBv1.0/town-test/DDATA/cloud-test/virtual-quad-test" {
		panic("wrong projection topic")
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	s.publications++
	return &iotdataplane.PublishOutput{}, nil
}

func TestStopAndFailureEventsAreFencedBySessionOwner(t *testing.T) {
	now := time.Now().UnixMilli()
	s := session.State{Phase: "stopped"}
	if err := s.Start(startID, "owner-1", "town-test", "cloud-test", 25, 0, now, now+900_000); err != nil {
		t.Fatal(err)
	}
	client := &lambdaShadow{version: 1, state: s}
	h := NewLambdaHandler(aws.Config{}, "example.test", testRegistry{awake: true}, client)
	stop := lambdaEvent{Topic: commandTopic, Payload: encodeTestCommand(4, stopID, sessionMetric, startID)}
	if err := h.command(t.Context(), stop); err != nil {
		t.Fatal(err)
	}
	if client.state.Phase != "stopping" || client.state.Run.Owner != "owner-1" {
		t.Fatalf("Stop did not preserve owner: %+v", client.state)
	}
	if err := h.command(t.Context(), stop); err != nil {
		t.Fatalf("duplicate Stop: %v", err)
	}
	var failure lambdaEvent
	failure.Detail.RequestPayload.Topic = commandTopic
	failure.Detail.RequestPayload.Payload = encodeTestCommand(1, startID, revisionMetric, "0")
	failure.Detail.RequestContext.RequestID = "different-owner"
	if err := h.failure(t.Context(), failure); err != nil {
		t.Fatal(err)
	}
	if client.state.Phase != "stopping" {
		t.Fatal("unrelated failure finalized active session")
	}
	failure.Detail.RequestContext.RequestID = "owner-1"
	if err := h.failure(t.Context(), failure); err != nil {
		t.Fatal(err)
	}
	if client.state.Phase != "failed" || client.state.Run != nil || client.state.TerminalRevision != 1 {
		t.Fatalf("failure did not finalize owner: %+v", client.state)
	}
	if err := h.report(t.Context(), testAssignment.DeviceID); err != nil || client.publications != 1 {
		t.Fatalf("terminal projection: publications=%d error=%v", client.publications, err)
	}
}

func TestDelayedStopCannotChangeReplacement(t *testing.T) {
	now := time.Now().UnixMilli()
	s := session.State{Phase: "stopped", TerminalRevision: 1}
	if err := s.Start("new-session", "owner-new", "town-test", "cloud-test", 26, 1, now, now+900_000); err != nil {
		t.Fatal(err)
	}
	client := &lambdaShadow{version: 1, state: s}
	h := NewLambdaHandler(aws.Config{}, "example.test", testRegistry{awake: true}, client)
	old := lambdaEvent{Topic: commandTopic, Payload: encodeTestCommand(4, stopID, sessionMetric, "old-session")}
	if err := h.command(t.Context(), old); err != nil {
		t.Fatal(err)
	}
	if client.version != 1 || client.state.Run.Owner != "owner-new" || client.state.Phase != "starting" {
		t.Fatalf("old Stop changed replacement: version=%d state=%+v", client.version, client.state)
	}
}

func TestDelayedRejectionCannotChangeReplacement(t *testing.T) {
	now := time.Now().UnixMilli()
	s := session.State{Phase: "stopped", TerminalRevision: 1}
	if err := s.Start("new-session", "owner-new", "town-test", "cloud-test", 26, 1, now, now+900_000); err != nil {
		t.Fatal(err)
	}
	client := &lambdaShadow{version: 1, state: s}
	h := NewLambdaHandler(aws.Config{}, "example.test", testRegistry{awake: true}, client)
	oldStart, err := decodeCommand(commandTopic, encodeTestCommand(1, startID, revisionMetric, "0"))
	if err != nil {
		t.Fatal(err)
	}
	if err := h.reject(t.Context(), oldStart, errors.New("busy")); err != nil {
		t.Fatal(err)
	}
	oldStop, err := decodeCommand(commandTopic, encodeTestCommand(4, stopID, sessionMetric, "old-session"))
	if err != nil {
		t.Fatal(err)
	}
	if err := h.reject(t.Context(), oldStop, errors.New("busy")); err != nil {
		t.Fatal(err)
	}
	if client.version != 1 || client.state.Receipt.RequestID != "new-session" || client.state.Receipt.Status != "accepted" {
		t.Fatalf("stale rejection changed replacement: version=%d state=%+v", client.version, client.state)
	}
}
