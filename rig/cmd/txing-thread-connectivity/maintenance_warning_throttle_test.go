package main

import (
	"errors"
	"sync"
	"testing"
	"time"
)

func TestMaintenanceWarningThrottleReportsFirstReminderAndRecovery(t *testing.T) {
	clock := newThrottleClock()
	throttle := newMaintenanceWarningThrottle(10*time.Minute, clock.now)
	err := errors.New("ot-ctl unavailable")

	assertThrottleLog(t, throttle.failure(err), `Thread maintenance failed error="ot-ctl unavailable"`)
	clock.advance(time.Minute)
	assertThrottleSuppressed(t, throttle.failure(err))
	clock.advance(9 * time.Minute)
	assertThrottleLog(t, throttle.failure(err), `Thread maintenance still failing duration=10m0s suppressed=1 error="ot-ctl unavailable"`)
	clock.advance(time.Minute)
	assertThrottleSuppressed(t, throttle.failure(err))
	clock.advance(10 * time.Minute)
	assertThrottleLog(t, throttle.failure(err), `Thread maintenance still failing duration=21m0s suppressed=1 error="ot-ctl unavailable"`)
	clock.advance(30 * time.Second)
	assertThrottleLog(t, throttle.success(), `Thread maintenance recovered outage=21m30s suppressed=2 lastError="ot-ctl unavailable"`)
	assertThrottleSuppressed(t, throttle.success())
}

func TestMaintenanceWarningThrottleReportsDistinctErrorImmediately(t *testing.T) {
	clock := newThrottleClock()
	throttle := newMaintenanceWarningThrottle(10*time.Minute, clock.now)

	assertThrottleLog(t, throttle.failure(errors.New("connection refused")), `Thread maintenance failed error="connection refused"`)
	clock.advance(time.Minute)
	assertThrottleSuppressed(t, throttle.failure(errors.New("connection refused")))
	clock.advance(time.Minute)
	assertThrottleLog(t, throttle.failure(errors.New("permission denied")), `Thread maintenance failed error="permission denied"`)
	clock.advance(2 * time.Minute)
	assertThrottleLog(t, throttle.success(), `Thread maintenance recovered outage=2m0s suppressed=0 lastError="permission denied"`)
}

func TestMaintenanceWarningThrottleDoesNotLogCleanSteadyState(t *testing.T) {
	clock := newThrottleClock()
	throttle := newMaintenanceWarningThrottle(10*time.Minute, clock.now)

	assertThrottleSuppressed(t, throttle.success())
	clock.advance(time.Hour)
	assertThrottleSuppressed(t, throttle.success())
}

func TestMaintenanceWarningThrottleSerializesConcurrentFailures(t *testing.T) {
	clock := newThrottleClock()
	throttle := newMaintenanceWarningThrottle(10*time.Minute, clock.now)
	const failures = 100

	logs := make(chan string, failures)
	var workers sync.WaitGroup
	for range failures {
		workers.Add(1)
		go func() {
			defer workers.Done()
			if decision := throttle.failure(errors.New("connection refused")); decision.emit {
				logs <- decision.message
			}
		}()
	}
	workers.Wait()
	close(logs)

	var messages []string
	for message := range logs {
		messages = append(messages, message)
	}
	if len(messages) != 1 || messages[0] != `Thread maintenance failed error="connection refused"` {
		t.Fatalf("concurrent warning messages = %#v", messages)
	}
	assertThrottleLog(t, throttle.success(), `Thread maintenance recovered outage=0s suppressed=99 lastError="connection refused"`)
}

type throttleClock struct {
	current time.Time
}

func newThrottleClock() *throttleClock {
	return &throttleClock{current: time.Unix(1_800_000_000, 0)}
}

func (c *throttleClock) now() time.Time {
	return c.current
}

func (c *throttleClock) advance(duration time.Duration) {
	c.current = c.current.Add(duration)
}

func assertThrottleLog(t *testing.T, decision maintenanceLogDecision, expected string) {
	t.Helper()
	if !decision.emit || decision.message != expected {
		t.Fatalf("throttle result = (%q, %t), want (%q, true)", decision.message, decision.emit, expected)
	}
}

func assertThrottleSuppressed(t *testing.T, decision maintenanceLogDecision) {
	t.Helper()
	if decision.emit || decision.message != "" {
		t.Fatalf("throttle result = (%q, %t), want suppressed", decision.message, decision.emit)
	}
}
