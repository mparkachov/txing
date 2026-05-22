package main

import (
	"context"
	"testing"
	"time"

	rigble "github.com/mparkachov/txing/rig/internal/ble"
	"github.com/mparkachov/txing/rig/internal/protocol"
	"github.com/mparkachov/txing/rig/internal/rigconfig"
	"tinygo.org/x/bluetooth"
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

func TestCommandContextUsesCommandDeadlineInsteadOfBleAttemptTimeout(t *testing.T) {
	now := time.Now()
	nowMS := uint64(now.UnixMilli())
	deadlineMS := uint64(now.Add(2 * time.Second).UnixMilli())
	command, err := protocol.NewCapabilityCommand("cmd-1", "unit-1", 3, "test", nowMS, 1, &deadlineMS)
	if err != nil {
		t.Fatal(err)
	}
	state := &runtimeState{
		cfg: rigconfig.Config{
			CommandTimeout:  10 * time.Millisecond,
			CommandDeadline: 5 * time.Second,
		},
	}
	ctx, cancel := state.commandContext(context.Background(), command)
	defer cancel()
	deadline, ok := ctx.Deadline()
	if !ok {
		t.Fatal("command context has no deadline")
	}
	if remaining := deadline.Sub(now); remaining < time.Second {
		t.Fatalf("deadline remaining = %s, command context was capped by BLE attempt timeout", remaining)
	}
}

func TestDiscoveryUUIDsOnlyRequireWeatherForWeatherDevices(t *testing.T) {
	state := testRuntimeStateWithUUIDs(t)
	powerUUIDs := state.discoveryUUIDs(rigble.DeviceSpec{ThingName: "unit-1", Kind: rigble.DeviceKindPower})
	if len(powerUUIDs) != 3 {
		t.Fatalf("power discovery UUID count = %d, want 3", len(powerUUIDs))
	}
	for _, uuid := range powerUUIDs {
		if uuid.String() == rigble.WeatherMeasurementUUID {
			t.Fatal("power discovery requested weather measurement characteristic")
		}
	}

	weatherUUIDs := state.discoveryUUIDs(rigble.DeviceSpec{ThingName: "weather-1", Kind: rigble.DeviceKindWeather})
	if len(weatherUUIDs) != 4 {
		t.Fatalf("weather discovery UUID count = %d, want 4", len(weatherUUIDs))
	}
	if weatherUUIDs[3].String() != rigble.WeatherMeasurementUUID {
		t.Fatalf("last weather discovery UUID = %s, want %s", weatherUUIDs[3].String(), rigble.WeatherMeasurementUUID)
	}
}

func testRuntimeStateWithUUIDs(t *testing.T) *runtimeState {
	t.Helper()
	parse := func(value string) bluetooth.UUID {
		uuid, err := bluetooth.ParseUUID(value)
		if err != nil {
			t.Fatalf("parse UUID %s: %v", value, err)
		}
		return uuid
	}
	return &runtimeState{
		commandUUID: parse(rigble.TxingBLECommandUUID),
		stateUUID:   parse(rigble.TxingBLEStateUUID),
		powerUUID:   parse(rigble.PowerMeasurementUUID),
		weatherUUID: parse(rigble.WeatherMeasurementUUID),
	}
}
