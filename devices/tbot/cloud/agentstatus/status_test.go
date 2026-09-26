package agentstatus

import (
	"context"
	"errors"
	"testing"
)

func TestLifecycleFencesOldTaskAndClearsEndpoint(t *testing.T) {
	state, err := Begin(Stopped(), "task-a")
	if err != nil {
		t.Fatal(err)
	}
	if _, err := Ready(state, "task-a", "203.0.113.1", "2001:db8::1", true); err == nil {
		t.Fatal("ready without MAVLink connection")
	}
	state, err = Connection(state, "task-a", "mavlink", "connected")
	if err != nil {
		t.Fatal(err)
	}
	state, err = Ready(state, "task-a", "203.0.113.1", "2001:db8::1", true)
	if err != nil {
		t.Fatal(err)
	}
	if state.Task.Status != "ready" || state.Endpoint.UDPPort == nil || *state.Endpoint.UDPPort != UDPPort {
		t.Fatalf("bad ready state: %+v", state)
	}
	state, err = Connection(state, "task-a", "video", "error")
	if err != nil || state.Task.Status != "ready" {
		t.Fatalf("video error interrupted MAVLink: %+v, %v", state, err)
	}
	state, err = Begin(state, "task-b")
	if err != nil {
		t.Fatal(err)
	}
	if state.Endpoint.IPv4 != nil || state.Endpoint.IPv6 != nil {
		t.Fatal("replacement retained old endpoint")
	}
	if _, err := Ready(state, "task-a", "203.0.113.1", "2001:db8::1", true); !errors.Is(err, ErrStaleTask) {
		t.Fatalf("superseded task restored endpoint: %v", err)
	}
	if _, err := Stop(state, "task-a"); !errors.Is(err, ErrStaleTask) {
		t.Fatalf("superseded task stopped replacement: %v", err)
	}
	state, err = Stop(state, "task-b")
	if err != nil || state.Task.Status != "stopped" || state.Endpoint.UDPPort != nil {
		t.Fatalf("stop did not clear endpoint: %+v, %v", state, err)
	}
}

func TestMAVLinkLossAndFailureClearEndpoint(t *testing.T) {
	state, _ := Begin(Stopped(), "task-a")
	state, _ = Connection(state, "task-a", "mavlink", "connected")
	state, _ = Ready(state, "task-a", "203.0.113.1", "2001:db8::1", true)
	state, err := Connection(state, "task-a", "mavlink", "disconnected")
	if err != nil || state.Task.Status != "starting" || state.Endpoint.IPv4 != nil {
		t.Fatalf("MAVLink loss left endpoint ready: %+v, %v", state, err)
	}
	state, _ = Connection(state, "task-a", "mavlink", "connected")
	state, _ = Ready(state, "task-a", "203.0.113.1", "2001:db8::1", true)
	state, err = Fail(state, "task-a", "task exited")
	if err != nil || state.Task.Status != "error" || state.Endpoint.IPv6 != nil {
		t.Fatalf("failure left endpoint ready: %+v, %v", state, err)
	}
}

type conflictStore struct {
	state    Reported
	version  int64
	conflict bool
}

func (s *conflictStore) Read(context.Context) (Reported, int64, error) {
	return s.state, s.version, nil
}

func (s *conflictStore) Write(_ context.Context, next Reported, version int64) error {
	if s.conflict {
		s.conflict = false
		s.state, _ = Begin(s.state, "task-b")
		s.version++
		return ErrVersionConflict
	}
	if version != s.version {
		return ErrVersionConflict
	}
	s.state = next
	s.version++
	return nil
}

func TestVersionConflictRechecksTaskIdentity(t *testing.T) {
	state, _ := Begin(Stopped(), "task-a")
	store := &conflictStore{state: state, version: 1, conflict: true}
	err := Update(context.Background(), store, func(current Reported) (Reported, error) {
		return Connection(current, "task-a", "mavlink", "connected")
	})
	if !errors.Is(err, ErrStaleTask) || store.state.MAVLink != "disconnected" {
		t.Fatalf("stale write passed after conflict: %+v, %v", store.state, err)
	}
}
