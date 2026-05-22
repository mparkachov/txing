package main

import (
	"context"
	"testing"
	"time"
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
