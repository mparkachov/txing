package main

import (
	"context"
	"errors"
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

func TestBackgroundConnectContextIsBounded(t *testing.T) {
	state := &runtimeState{
		cfg: rigconfig.Config{ConnectTimeout: 8 * time.Second},
	}
	ctx, cancel := state.backgroundConnectContext(context.Background())
	defer cancel()
	deadline, ok := ctx.Deadline()
	if !ok {
		t.Fatal("background connect context has no deadline")
	}
	remaining := time.Until(deadline)
	if remaining < 8500*time.Millisecond || remaining > 11*time.Second {
		t.Fatalf("background deadline remaining = %s, want about 10s", remaining)
	}
}

func TestConsumeScanStoppedForConnectOnlyOnce(t *testing.T) {
	state := &runtimeState{scanStoppedForConnect: true}
	if !state.consumeScanStoppedForConnect() {
		t.Fatal("expected scan stop flag")
	}
	if state.consumeScanStoppedForConnect() {
		t.Fatal("scan stop flag should be cleared")
	}
}

func TestScanRetryDecisionRecoversBluezAlreadyActiveDiscovery(t *testing.T) {
	decision := scanRetryDecision(errors.New("Operation already in progress"), 7)
	if decision.delayMS != rigble.BluezInProgressScanRetryDelayMS {
		t.Fatalf("delay = %d, want %d", decision.delayMS, rigble.BluezInProgressScanRetryDelayMS)
	}
	if decision.nextFailures != 0 {
		t.Fatalf("nextFailures = %d, want 0", decision.nextFailures)
	}
	if !decision.resetDiscovery {
		t.Fatal("expected stale discovery reset")
	}
}

func TestScanRetryDecisionKeepsGenericBackoff(t *testing.T) {
	decision := scanRetryDecision(errors.New("adapter unavailable"), 2)
	wantDelay := rigble.BoundedRetryDelayMS(rigble.BLERetryMinDelayMS, 2, rigble.BLERetryMaxDelayMS)
	if decision.delayMS != wantDelay {
		t.Fatalf("delay = %d, want %d", decision.delayMS, wantDelay)
	}
	if decision.nextFailures != 3 {
		t.Fatalf("nextFailures = %d, want 3", decision.nextFailures)
	}
	if decision.resetDiscovery {
		t.Fatal("generic failures must not reset discovery")
	}
}

func TestAdvertisementCapabilityStateSuppressedAfterRecentPowerStateRead(t *testing.T) {
	state := &runtimeState{}
	spec := rigble.DeviceSpec{ThingName: "unit-1", Kind: rigble.DeviceKindPower}
	now := time.Unix(100, 0)

	if !state.shouldPublishAdvertisementCapabilityState(spec, now) {
		t.Fatal("first advertisement should publish BLE reachability state")
	}

	state.recordStateRead(spec.ThingName, now)
	if state.shouldPublishAdvertisementCapabilityState(spec, now.Add(time.Second)) {
		t.Fatal("recent connected state read should suppress advertisement-only capability state")
	}

	staleAt := now.Add(time.Duration(rigble.BLEActiveMeasurementStaleMS) * time.Millisecond)
	if !state.shouldPublishAdvertisementCapabilityState(spec, staleAt) {
		t.Fatal("advertisement-only capability state should resume once the connected state read is stale")
	}
}

func TestWeatherAdvertisementCapabilityStateBypassesRecentStateRead(t *testing.T) {
	state := &runtimeState{}
	spec := rigble.DeviceSpec{ThingName: "weather-1", Kind: rigble.DeviceKindWeather}
	now := time.Unix(100, 0)

	state.recordStateRead(spec.ThingName, now)
	if !state.shouldPublishAdvertisementCapabilityState(spec, now.Add(time.Second)) {
		t.Fatal("weather advertisements should continue publishing idle capability state")
	}
}

func TestLooksLikeTxingThingName(t *testing.T) {
	for _, name := range []string{"unit-wrd8ti", "power-asw355", "weather-ebkwfx"} {
		if !looksLikeTxingThingName(name) {
			t.Fatalf("%s should be treated as txing-like", name)
		}
	}
	for _, name := range []string{"", "Phone", "my-unit-1", "sensor-weather"} {
		if looksLikeTxingThingName(name) {
			t.Fatalf("%s should not be treated as txing-like", name)
		}
	}
}

func TestDebugScanCandidateRequiresDebugAndRelevance(t *testing.T) {
	state := &runtimeState{cfg: rigconfig.Config{Debug: true}}
	if !state.shouldDebugScanCandidate("unit-wrd8ti", false, false) {
		t.Fatal("txing-like names should be logged in debug mode")
	}
	if !state.shouldDebugScanCandidate("Phone", true, false) {
		t.Fatal("txing service candidates should be logged in debug mode")
	}
	if !state.shouldDebugScanCandidate("managed-thing", false, true) {
		t.Fatal("known inventory targets should be logged in debug mode")
	}
	if state.shouldDebugScanCandidate("Phone", false, false) {
		t.Fatal("irrelevant candidates should not be logged")
	}

	state.cfg.Debug = false
	if state.shouldDebugScanCandidate("unit-wrd8ti", true, true) {
		t.Fatal("scan candidate logs must be disabled when debug is false")
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
