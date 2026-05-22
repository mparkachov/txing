package main

import (
	"context"
	"testing"
	"time"

	rigble "github.com/mparkachov/txing/rig/internal/ble"
)

func TestAcquireConnectSlotHonorsLimit(t *testing.T) {
	state := &runtimeState{connectSlots: make(chan struct{}, 1)}
	release, err := state.acquireConnectSlot(context.Background())
	if err != nil {
		t.Fatalf("first acquire failed: %v", err)
	}
	defer release()

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Millisecond)
	defer cancel()
	if _, err := state.acquireConnectSlot(ctx); err == nil {
		t.Fatal("second acquire succeeded while slot was full")
	}
}

func TestAcquireDeviceConnectSerializesSameThing(t *testing.T) {
	state := &runtimeState{}
	release, err := state.acquireDeviceConnect(context.Background(), "unit-1")
	if err != nil {
		t.Fatalf("first acquire failed: %v", err)
	}

	blockedCtx, cancelBlocked := context.WithTimeout(context.Background(), 10*time.Millisecond)
	defer cancelBlocked()
	if _, err := state.acquireDeviceConnect(blockedCtx, "unit-1"); err == nil {
		t.Fatal("second acquire for same thing succeeded while active")
	}

	otherRelease, err := state.acquireDeviceConnect(context.Background(), "unit-2")
	if err != nil {
		t.Fatalf("acquire for different thing failed: %v", err)
	}
	otherRelease()

	release()
	nextRelease, err := state.acquireDeviceConnect(context.Background(), "unit-1")
	if err != nil {
		t.Fatalf("acquire after release failed: %v", err)
	}
	nextRelease()
}

func TestBleCommandRetryDelayClassifiesBluezInProgress(t *testing.T) {
	delay := bleCommandRetryDelayMS("unit-1", "bluetooth: failed to connect: In Progress", 0)
	if delay < rigble.BluezInProgressReconnectDelayMS {
		t.Fatalf("delay = %d, want at least %d", delay, rigble.BluezInProgressReconnectDelayMS)
	}
	if delay > rigble.BluezInProgressReconnectDelayMS+250 {
		t.Fatalf("delay = %d, want bounded jitter above %d", delay, rigble.BluezInProgressReconnectDelayMS)
	}
}
