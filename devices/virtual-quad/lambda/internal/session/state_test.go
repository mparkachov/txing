package session

import (
	"errors"
	"testing"
	"time"
)

const startTime = int64(1_800_000_000_000)

func newSession(t *testing.T) State {
	t.Helper()
	s := State{Phase: "stopped"}
	if err := s.Start("session-1", "invocation-1", "town", "cloud-rig", 17, 0,
		startTime, startTime+900_000); err != nil {
		t.Fatal(err)
	}
	return s
}

func TestStartStopAndFinish(t *testing.T) {
	s := newSession(t)
	if err := s.Start("session-2", "invocation-2", "town", "cloud-rig", 18, 0,
		startTime+1, startTime+900_000); !errors.Is(err, ErrBusy) {
		t.Fatalf("concurrent start: %v", err)
	}
	ready := Health{Heartbeat: true, Navigation: true, Mavlink: true, Video: true}
	if err := s.UpdateHealth("invocation-1", ready, startTime+40_000); err != nil {
		t.Fatal(err)
	}
	if s.Phase != "operational" || *s.FlightDeadline != startTime+40_000+FlightLimit.Milliseconds() ||
		*s.AvailabilityExpires != startTime+55_000 {
		t.Fatalf("unexpected readiness: %+v", s)
	}
	if err := s.Stop("session-1", "stop-1", 19, startTime+60_000); err != nil {
		t.Fatal(err)
	}
	if s.Phase != "stopping" || s.Run.Simulation || s.AvailabilityExpires != nil {
		t.Fatalf("stop did not revoke readiness: %+v", s)
	}
	if err := s.Finish("invocation-1", "stopped", "operator stop", startTime+61_000); err != nil {
		t.Fatal(err)
	}
	if s.Phase != "stopped" || s.TerminalRevision != 1 || s.SessionID != nil || *s.LastSessionID != "session-1" {
		t.Fatalf("unexpected terminal state: %+v", s)
	}
	if err := s.Start("session-2", "invocation-2", "town", "cloud-rig", 20, 0,
		startTime+62_000, startTime+962_000); !errors.Is(err, ErrStale) {
		t.Fatalf("old terminal revision accepted: %v", err)
	}
}

func TestExpiredInvocationCanBeReplacedAndCannotOverwriteReplacement(t *testing.T) {
	s := newSession(t)
	replacementTime := startTime + int64((900 * time.Second).Milliseconds())
	if err := s.Start("session-1", "replayed-owner", "town", "cloud-rig", 17, 0,
		replacementTime, replacementTime+900_000); !errors.Is(err, ErrDuplicate) {
		t.Fatalf("expired invocation was restarted by a duplicate command: %v", err)
	}
	if err := s.Start("session-2", "invocation-2", "town", "cloud-rig", 18, 0,
		replacementTime, replacementTime+900_000); err != nil {
		t.Fatal(err)
	}
	if s.TerminalRevision != 1 || *s.LastSessionID != "session-1" || *s.SessionID != "session-2" {
		t.Fatalf("unexpected replacement: %+v", s)
	}
	if err := s.Finish("invocation-1", "failed", "late failure", replacementTime+1); !errors.Is(err, ErrNotOwner) {
		t.Fatalf("old failure changed replacement: %v", err)
	}
	if err := s.Stop("session-1", "stop-old", 19, replacementTime+1); !errors.Is(err, ErrStale) {
		t.Fatalf("old stop changed replacement: %v", err)
	}
}

func TestHealthDoesNotReviveExpiredSession(t *testing.T) {
	s := newSession(t)
	health := Health{Heartbeat: true, Navigation: true, Mavlink: true, Video: true}
	if err := s.UpdateHealth("invocation-1", health, startTime+StartupLimit.Milliseconds()); !errors.Is(err, ErrExpired) {
		t.Fatalf("expired startup became ready: %v", err)
	}
	if s.Phase != "starting" {
		t.Fatalf("expired health changed phase: %s", s.Phase)
	}
}

func TestReadinessExpiresAndMediaRecoveryIsBounded(t *testing.T) {
	s := newSession(t)
	ready := Health{Heartbeat: true, Navigation: true, Mavlink: true, Video: true}
	if err := s.UpdateHealth("invocation-1", ready, startTime+40_000); err != nil {
		t.Fatal(err)
	}
	if availability := s.Availability(startTime + 40_001); availability.REDCON != 1 || !availability.Video {
		t.Fatalf("ready session: %+v", availability)
	}
	if availability := s.Availability(startTime + 55_000); availability.REDCON != 3 || availability.Simulation {
		t.Fatalf("expired session still ready: %+v", availability)
	}
	unavailable := Health{Heartbeat: true, Navigation: true, Mavlink: true}
	for _, offset := range []int64{45_000, 50_000, 55_000, 60_000, 65_000, 70_000} {
		if err := s.UpdateHealth("invocation-1", unavailable, startTime+offset); err != nil {
			t.Fatalf("recovering at %d: %v", offset, err)
		}
	}
	if err := s.UpdateHealth("invocation-1", ready, startTime+75_000); !errors.Is(err, ErrExpired) {
		t.Fatalf("late recovery accepted: %v", err)
	}
}
