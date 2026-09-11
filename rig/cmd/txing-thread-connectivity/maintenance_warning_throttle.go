package main

import (
	"fmt"
	"sync"
	"time"
)

const maintenanceWarningRepeatInterval = 10 * time.Minute

// maintenanceWarningThrottle retains one bounded failure series. Production
// uses time.Now, whose Time values carry a monotonic clock reading, so wall
// clock adjustments cannot release duplicate warnings early.
type maintenanceWarningThrottle struct {
	mu       sync.Mutex
	interval time.Duration
	now      func() time.Time

	active                 bool
	errorText              string
	startedAt              time.Time
	lastWarningAt          time.Time
	suppressedSinceWarning uint64
	totalSuppressed        uint64
}

type maintenanceLogDecision struct {
	message string
	emit    bool
}

func newMaintenanceWarningThrottle(interval time.Duration, now func() time.Time) *maintenanceWarningThrottle {
	return &maintenanceWarningThrottle{interval: interval, now: now}
}

func (t *maintenanceWarningThrottle) failure(err error) maintenanceLogDecision {
	t.mu.Lock()
	defer t.mu.Unlock()

	now := t.now()
	errorText := err.Error()
	if !t.active || errorText != t.errorText {
		t.active = true
		t.errorText = errorText
		t.startedAt = now
		t.lastWarningAt = now
		t.suppressedSinceWarning = 0
		t.totalSuppressed = 0
		return maintenanceLogDecision{
			message: fmt.Sprintf("Thread maintenance failed error=%q", errorText),
			emit:    true,
		}
	}

	if now.Sub(t.lastWarningAt) < t.interval {
		t.suppressedSinceWarning++
		t.totalSuppressed++
		return maintenanceLogDecision{}
	}

	message := fmt.Sprintf(
		"Thread maintenance still failing duration=%s suppressed=%d error=%q",
		logDuration(now.Sub(t.startedAt)),
		t.suppressedSinceWarning,
		errorText,
	)
	t.lastWarningAt = now
	t.suppressedSinceWarning = 0
	return maintenanceLogDecision{message: message, emit: true}
}

func (t *maintenanceWarningThrottle) success() maintenanceLogDecision {
	t.mu.Lock()
	defer t.mu.Unlock()

	if !t.active {
		return maintenanceLogDecision{}
	}
	message := fmt.Sprintf(
		"Thread maintenance recovered outage=%s suppressed=%d lastError=%q",
		logDuration(t.now().Sub(t.startedAt)),
		t.totalSuppressed,
		t.errorText,
	)
	t.active = false
	t.errorText = ""
	t.startedAt = time.Time{}
	t.lastWarningAt = time.Time{}
	t.suppressedSinceWarning = 0
	t.totalSuppressed = 0
	return maintenanceLogDecision{message: message, emit: true}
}

func logDuration(duration time.Duration) time.Duration {
	if duration < 0 {
		return 0
	}
	return duration.Round(time.Second)
}
