package main

import (
	"context"
	"errors"
	"fmt"
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

func TestScanFreshnessHoldCoversActiveAndRecentConnects(t *testing.T) {
	state := &runtimeState{
		cfg:            rigconfig.Config{PresenceTimeout: 20 * time.Second},
		activeConnects: map[string]chan struct{}{},
	}
	release, err := state.acquireDeviceConnect(context.Background(), "unit-1")
	if err != nil {
		t.Fatalf("acquire failed: %v", err)
	}
	state.scanFreshnessHoldStart = time.Now()
	ad := testAdvertisement("unit-1", time.Now().Add(-5*time.Second))
	if !state.scanFreshnessHeldFor(ad, time.Now()) {
		t.Fatal("active connect should hold scanner freshness")
	}

	release()
	if !state.scanFreshnessHeldFor(ad, time.Now()) {
		t.Fatal("recent connect release should hold scanner freshness")
	}

	state.mu.Lock()
	state.scanFreshnessHoldUntil = time.Now().Add(-time.Second)
	state.mu.Unlock()
	if state.scanFreshnessHeldFor(ad, time.Now()) {
		t.Fatal("expired connect freshness hold should not remain active")
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

func TestAdvertisementAddressCachedBeforeInventory(t *testing.T) {
	state := &runtimeState{}
	advertisement := testAdvertisement("weather-1", time.Now())
	state.recordAdvertisement("weather-1", bluetooth.Address{}, advertisement)

	if _, ok := state.addresses["weather-1"]; !ok {
		t.Fatal("pre-inventory advertisement address was not cached")
	}
	if cached, ok := state.cachedAdvertisements["weather-1"]; !ok || cached.Address != advertisement.Address {
		t.Fatalf("cached advertisement = %#v, want %#v", cached, advertisement)
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

func TestInventorySessionsStartStopAndReplayCachedAdvertisement(t *testing.T) {
	state := testSessionRuntime(t)
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	ad := testAdvertisement("unit-1", time.Now())
	state.cachedAdvertisements["unit-1"] = ad
	state.cachedAdvertisements["weather-1"] = testAdvertisement("weather-1", time.Now().Add(-30*time.Second))
	deliveries := state.updateInventorySessions(ctx, map[string]rigble.DeviceSpec{
		"unit-1":    {ThingName: "unit-1", Kind: rigble.DeviceKindPower},
		"weather-1": {ThingName: "weather-1", Kind: rigble.DeviceKindWeather},
	})
	if len(state.sessions) != 2 || state.sessions["unit-1"] == nil || state.sessions["weather-1"] == nil {
		t.Fatalf("sessions = %#v, want unit-1 session", state.sessions)
	}
	if len(deliveries) != 1 || deliveries[0].advertisement.Address != ad.Address {
		t.Fatalf("deliveries = %#v, want cached unit advertisement", deliveries)
	}
	if _, ok := state.cachedAdvertisements["weather-1"]; ok {
		t.Fatal("stale cached weather advertisement should be discarded during inventory reconciliation")
	}

	state.updateInventorySessions(ctx, map[string]rigble.DeviceSpec{
		"weather-1": {ThingName: "weather-1", Kind: rigble.DeviceKindWeather},
	})
	if _, ok := state.sessions["unit-1"]; ok {
		t.Fatal("removed inventory device still has a session")
	}
	if _, ok := state.sessions["weather-1"]; !ok {
		t.Fatal("new inventory device did not get a session")
	}
}

func TestConnectedSessionIgnoresAdvertisementState(t *testing.T) {
	state := testSessionRuntime(t)
	samples := []rigble.CapabilitySample{}
	state.sampleSink = func(sample rigble.CapabilitySample, includeShadow bool, includeCapabilityState bool) {
		samples = append(samples, sample)
	}
	session := newDeviceSession(state, rigble.DeviceSpec{ThingName: "unit-1", Kind: rigble.DeviceKindPower})
	session.connected = &fakeBLEConnection{connected: true, address: "AA:BB:CC:DD:EE:FF"}

	session.handleAdvertisement(context.Background(), testAdvertisement("unit-1", time.Now()))

	if len(samples) != 0 {
		t.Fatalf("connected advertisement published %d samples, want none", len(samples))
	}
	if session.lastAdvertisement == nil {
		t.Fatal("connected advertisements should still refresh last advertisement evidence")
	}
}

func TestSessionIgnoresStaleAdvertisement(t *testing.T) {
	state := testSessionRuntime(t)
	connector := &fakeBLEConnector{}
	state.connector = connector
	published := 0
	state.sampleSink = func(sample rigble.CapabilitySample, includeShadow bool, includeCapabilityState bool) {
		published++
	}
	session := newDeviceSession(state, rigble.DeviceSpec{ThingName: "unit-1", Kind: rigble.DeviceKindPower})
	session.offlinePublished = true

	session.handleAdvertisement(context.Background(), testAdvertisement("unit-1", time.Now().Add(-30*time.Second)))

	if session.lastAdvertisement != nil {
		t.Fatal("stale advertisement should not refresh last advertisement")
	}
	if !session.offlinePublished {
		t.Fatal("stale advertisement should not clear offline publication state")
	}
	if published != 0 {
		t.Fatalf("published samples = %d, want none", published)
	}
	if connector.calls != 0 {
		t.Fatalf("connector calls = %d, want no connect from stale advertisement", connector.calls)
	}
}

func TestBackgroundConnectFailureLogLevelFollowsPresenceImpact(t *testing.T) {
	state := testSessionRuntime(t)
	session := newDeviceSession(state, rigble.DeviceSpec{ThingName: "unit-1", Kind: rigble.DeviceKindPower})

	if got := session.backgroundConnectFailureLogLevel(fmt.Errorf("last BLE advertisement for unit-1 is stale")); got != "debug" {
		t.Fatalf("stale advertisement log level = %s, want debug", got)
	}
	if got := session.backgroundConnectFailureLogLevel(fmt.Errorf("no BLE advertisement has been observed for unit-1")); got != "debug" {
		t.Fatalf("missing advertisement log level = %s, want debug", got)
	}

	session.lastAdvertisement = cloneAdvertisement(testAdvertisement("unit-1", time.Now()))
	if got := session.backgroundConnectFailureLogLevel(fmt.Errorf("timeout on DiscoverServices")); got != "debug" {
		t.Fatalf("fresh-advertisement connect timeout log level = %s, want debug", got)
	}

	session.lastAdvertisement = nil
	if got := session.backgroundConnectFailureLogLevel(fmt.Errorf("permission denied")); got != "warning" {
		t.Fatalf("non-presence failure log level = %s, want warning", got)
	}
}

func TestSessionCommandReusesConnectedDevice(t *testing.T) {
	state := testSessionRuntime(t)
	connector := &fakeBLEConnector{}
	state.connector = connector
	statuses := []string{}
	state.commandResultSink = func(command protocol.CapabilityCommand, status string, message *string, redcon *uint8) {
		statuses = append(statuses, status)
	}
	conn := &fakeBLEConnection{connected: true, address: "AA:BB:CC:DD:EE:FF", powerState: rigble.PowerState{Redcon: rigble.RedconActive}}
	session := newDeviceSession(state, rigble.DeviceSpec{ThingName: "unit-1", Kind: rigble.DeviceKindPower})
	session.connected = conn

	session.handleCommand(context.Background(), testCommand(t, "unit-1", 3))

	if connector.calls != 0 {
		t.Fatalf("connector calls = %d, want reuse of existing connection", connector.calls)
	}
	if len(conn.writes) != 1 || conn.writes[0] != rigble.RedconActive {
		t.Fatalf("writes = %#v, want REDCON 3 write", conn.writes)
	}
	assertStatuses(t, statuses, []string{protocol.CommandAccepted, protocol.CommandSucceeded})
}

func TestCommandWaitsForFreshAdvertisementBeforeConnectRetry(t *testing.T) {
	state := testSessionRuntime(t)
	connector := &fakeBLEConnector{
		results: []fakeConnectResult{{
			connection: &fakeBLEConnection{connected: true, address: "AA:BB:CC:DD:EE:FF", powerState: rigble.PowerState{Redcon: rigble.RedconActive}},
			outcome:    connectOutcomeConnected,
		}},
	}
	state.connector = connector
	statuses := []string{}
	state.commandResultSink = func(command protocol.CapabilityCommand, status string, message *string, redcon *uint8) {
		statuses = append(statuses, status)
	}
	session := newDeviceSession(state, rigble.DeviceSpec{ThingName: "unit-1", Kind: rigble.DeviceKindPower})

	done := make(chan struct{})
	go func() {
		defer close(done)
		session.handleCommand(context.Background(), testCommand(t, "unit-1", 3))
	}()

	select {
	case <-done:
		t.Fatal("command completed before a fresh advertisement arrived")
	case <-time.After(20 * time.Millisecond):
	}
	session.enqueueAdvertisement(context.Background(), testAdvertisement("unit-1", time.Now()))
	select {
	case <-done:
	case <-time.After(time.Second):
		t.Fatal("command did not complete after fresh advertisement")
	}

	if connector.calls != 1 {
		t.Fatalf("connector calls = %d, want one connect after advertisement", connector.calls)
	}
	if len(connector.waitForCapacity) != 1 || !connector.waitForCapacity[0] {
		t.Fatalf("waitForCapacity = %#v, want command connect to wait for capacity", connector.waitForCapacity)
	}
	assertStatuses(t, statuses, []string{protocol.CommandAccepted, protocol.CommandSucceeded})
}

func TestConnectedSessionAgesMeasurementsByRedcon(t *testing.T) {
	state := testSessionRuntime(t)
	published := 0
	state.sampleSink = func(sample rigble.CapabilitySample, includeShadow bool, includeCapabilityState bool) {
		published++
	}
	session := newDeviceSession(state, rigble.DeviceSpec{ThingName: "unit-1", Kind: rigble.DeviceKindPower})
	session.connected = &fakeBLEConnection{connected: true, address: "AA:BB:CC:DD:EE:FF"}
	battery := uint16(3900)

	session.setLastRedcon(rigble.RedconActive)
	session.lastPowerMeasurement = &timedMeasurement[rigble.PowerMeasurement]{
		value:        rigble.PowerMeasurement{BatteryMV: &battery},
		observedAtMS: uint64(time.Now().Add(-25 * time.Second).UnixMilli()),
	}
	session.checkStale(context.Background())
	if session.lastPowerMeasurement != nil {
		t.Fatal("active REDCON measurement older than 20s should be cleared")
	}
	if published == 0 {
		t.Fatal("stale measurement clear should publish aggregate state")
	}

	published = 0
	session.setLastRedcon(rigble.RedconIdle)
	session.lastPowerMeasurement = &timedMeasurement[rigble.PowerMeasurement]{
		value:        rigble.PowerMeasurement{BatteryMV: &battery},
		observedAtMS: uint64(time.Now().Add(-30 * time.Second).UnixMilli()),
	}
	session.checkStale(context.Background())
	if session.lastPowerMeasurement == nil {
		t.Fatal("idle REDCON measurement newer than 120s should be retained")
	}
	if published != 0 {
		t.Fatal("fresh idle measurement should not publish a stale-clear sample")
	}
}

func TestStaleAdvertisementDoesNotPublishOfflineWhileScanFreshnessHeld(t *testing.T) {
	state := testSessionRuntime(t)
	published := 0
	state.sampleSink = func(sample rigble.CapabilitySample, includeShadow bool, includeCapabilityState bool) {
		published++
	}
	holdStart := time.Now().Add(-10 * time.Second)
	state.scanFreshnessHoldStart = holdStart
	state.scanFreshnessHoldUntil = time.Now().Add(time.Second)
	session := newDeviceSession(state, rigble.DeviceSpec{ThingName: "unit-1", Kind: rigble.DeviceKindPower})
	session.lastAdvertisement = cloneAdvertisement(testAdvertisement("unit-1", holdStart.Add(-15*time.Second)))

	session.checkStale(context.Background())

	if session.offlinePublished {
		t.Fatal("offline should not publish while scanner freshness is held for connect recovery")
	}
	if published != 0 {
		t.Fatalf("published samples = %d, want none", published)
	}
}

func TestStaleAdvertisementPublishesOfflineWhenStaleBeforeScanHold(t *testing.T) {
	state := testSessionRuntime(t)
	published := 0
	state.sampleSink = func(sample rigble.CapabilitySample, includeShadow bool, includeCapabilityState bool) {
		published++
	}
	holdStart := time.Now().Add(-10 * time.Second)
	state.scanFreshnessHoldStart = holdStart
	state.scanFreshnessHoldUntil = time.Now().Add(time.Second)
	session := newDeviceSession(state, rigble.DeviceSpec{ThingName: "unit-1", Kind: rigble.DeviceKindPower})
	session.lastAdvertisement = cloneAdvertisement(testAdvertisement("unit-1", holdStart.Add(-25*time.Second)))

	session.checkStale(context.Background())

	if !session.offlinePublished {
		t.Fatal("offline should publish when advertisement was already stale before scanner freshness hold")
	}
	if published != 1 {
		t.Fatalf("published samples = %d, want one offline sample", published)
	}
}

func TestStaleAdvertisementPublishesOfflineAfterScanFreshnessHoldExpires(t *testing.T) {
	state := testSessionRuntime(t)
	published := 0
	state.sampleSink = func(sample rigble.CapabilitySample, includeShadow bool, includeCapabilityState bool) {
		published++
	}
	state.scanFreshnessHoldStart = time.Now().Add(-30 * time.Second)
	state.scanFreshnessHoldUntil = time.Now().Add(-time.Second)
	session := newDeviceSession(state, rigble.DeviceSpec{ThingName: "unit-1", Kind: rigble.DeviceKindPower})
	session.lastAdvertisement = cloneAdvertisement(testAdvertisement("unit-1", time.Now().Add(-30*time.Second)))

	session.checkStale(context.Background())

	if !session.offlinePublished {
		t.Fatal("offline should publish after scanner freshness hold expires")
	}
	if published != 1 {
		t.Fatalf("published samples = %d, want one offline sample", published)
	}
}

func TestBackgroundAdvertisementConnectDefersWithoutCapacity(t *testing.T) {
	state := testSessionRuntime(t)
	connector := &fakeBLEConnector{
		results: []fakeConnectResult{{outcome: connectOutcomeDeferredNoCapacity}},
	}
	state.connector = connector
	session := newDeviceSession(state, rigble.DeviceSpec{ThingName: "unit-1", Kind: rigble.DeviceKindPower})

	session.handleAdvertisement(context.Background(), testAdvertisement("unit-1", time.Now()))

	if connector.calls != 1 {
		t.Fatalf("connector calls = %d, want one background attempt", connector.calls)
	}
	if len(connector.waitForCapacity) != 1 || connector.waitForCapacity[0] {
		t.Fatalf("waitForCapacity = %#v, want background connect to avoid waiting for capacity", connector.waitForCapacity)
	}
	if session.nextConnectAfter.IsZero() {
		t.Fatal("deferred background connect should set reconnect backoff")
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

func testSessionRuntime(t *testing.T) *runtimeState {
	t.Helper()
	state := testRuntimeStateWithUUIDs(t)
	state.cfg = rigconfig.Config{
		PresenceTimeout: 20 * time.Second,
		ReconnectDelay:  2 * time.Second,
		ConnectTimeout:  8 * time.Second,
		CommandDeadline: 5 * time.Second,
	}
	state.specs = map[string]rigble.DeviceSpec{}
	state.sessions = map[string]*deviceSession{}
	state.addresses = map[string]bluetooth.Address{}
	state.cachedAdvertisements = map[string]rigble.Advertisement{}
	state.scannerLastPublished = map[string]uint64{}
	state.lastStateRead = map[string]time.Time{}
	state.activeConnects = map[string]chan struct{}{}
	state.connector = &fakeBLEConnector{}
	state.sampleSink = func(rigble.CapabilitySample, bool, bool) {}
	return state
}

func testAdvertisement(thingName string, observedAt time.Time) rigble.Advertisement {
	name := thingName
	rssi := int16(-50)
	return rigble.Advertisement{
		Address:      "AA:BB:CC:DD:EE:FF",
		IdentityName: &name,
		Services:     []string{rigble.TxingBLEServiceUUID},
		RSSI:         &rssi,
		ObservedAtMS: uint64(observedAt.UnixMilli()),
		Seq:          1,
	}
}

func testCommand(t *testing.T, thingName string, redcon uint8) protocol.CapabilityCommand {
	t.Helper()
	now := uint64(time.Now().UnixMilli())
	deadline := uint64(time.Now().Add(2 * time.Second).UnixMilli())
	command, err := protocol.NewCapabilityCommand("cmd-1", thingName, redcon, "test", now, 1, &deadline)
	if err != nil {
		t.Fatal(err)
	}
	return command
}

func assertStatuses(t *testing.T, got []string, want []string) {
	t.Helper()
	if len(got) != len(want) {
		t.Fatalf("statuses = %#v, want %#v", got, want)
	}
	for i := range want {
		if got[i] != want[i] {
			t.Fatalf("statuses = %#v, want %#v", got, want)
		}
	}
}

type fakeConnectResult struct {
	connection bleConnection
	outcome    connectOutcome
	err        error
}

type fakeBLEConnector struct {
	calls           int
	waitForCapacity []bool
	results         []fakeConnectResult
}

func (f *fakeBLEConnector) ConnectBLE(ctx context.Context, spec rigble.DeviceSpec, advertisement rigble.Advertisement, waitForCapacity bool) (bleConnection, connectOutcome, error) {
	f.calls++
	f.waitForCapacity = append(f.waitForCapacity, waitForCapacity)
	if len(f.results) == 0 {
		return nil, connectOutcomeConnected, fmt.Errorf("not found")
	}
	result := f.results[0]
	f.results = f.results[1:]
	return result.connection, result.outcome, result.err
}

type fakeBLEConnection struct {
	connected          bool
	address            string
	powerState         rigble.PowerState
	weatherState       rigble.WeatherState
	powerMeasurement   rigble.PowerMeasurement
	weatherMeasurement rigble.WeatherMeasurement
	writes             []uint8
	notifications      []bleNotification
	disconnects        int
}

func (f *fakeBLEConnection) Address() string {
	return f.address
}

func (f *fakeBLEConnection) Connected() bool {
	return f.connected
}

func (f *fakeBLEConnection) Disconnect() {
	f.disconnects++
	f.connected = false
}

func (f *fakeBLEConnection) WriteRedcon(redcon uint8) error {
	f.writes = append(f.writes, redcon)
	return nil
}

func (f *fakeBLEConnection) ReadPowerState() (rigble.PowerState, error) {
	if f.powerState.Redcon == 0 {
		return rigble.PowerState{Redcon: rigble.RedconIdle}, nil
	}
	return f.powerState, nil
}

func (f *fakeBLEConnection) ReadWeatherState() (rigble.WeatherState, error) {
	if f.weatherState.Redcon == 0 {
		return rigble.WeatherState{Redcon: rigble.RedconIdle}, nil
	}
	return f.weatherState, nil
}

func (f *fakeBLEConnection) ReadPowerMeasurement() (rigble.PowerMeasurement, error) {
	return f.powerMeasurement, nil
}

func (f *fakeBLEConnection) ReadWeatherMeasurement() (rigble.WeatherMeasurement, error) {
	return f.weatherMeasurement, nil
}

func (f *fakeBLEConnection) DrainNotifications() []bleNotification {
	notifications := f.notifications
	f.notifications = nil
	return notifications
}
