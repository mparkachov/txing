package manager

import (
	"testing"

	"github.com/mparkachov/txing/rig/internal/protocol"
	"github.com/mparkachov/txing/rig/internal/sparkplug"
)

func powerInventory() protocol.InventoryDevice {
	return protocol.InventoryDevice{
		ThingName:           "power-1",
		ThingType:           "power",
		Capabilities:        []string{"sparkplug", "ble", "power"},
		RedconCommandLevels: []uint8{4, 3},
		RedconRules: map[uint8][]string{
			4: []string{"sparkplug", "ble"},
			3: []string{"sparkplug", "ble", "power"},
		},
	}
}

func weatherInventoryWithStaleRedcon3Rule() protocol.InventoryDevice {
	return protocol.InventoryDevice{
		ThingName:           "weather-1",
		ThingType:           "weather",
		Capabilities:        []string{"sparkplug", "ble", "power", "weather"},
		RedconCommandLevels: []uint8{4},
		RedconRules: map[uint8][]string{
			3: []string{"sparkplug", "ble", "power", "weather"},
			4: []string{"sparkplug", "ble", "power", "weather"},
		},
	}
}

func unitInventory() protocol.InventoryDevice {
	return protocol.InventoryDevice{
		ThingName:           "unit-1",
		ThingType:           "unit",
		Capabilities:        []string{"sparkplug", "ble", PowerCapability, BoardCapability, MCPCapability, VideoCapability},
		RedconCommandLevels: []uint8{4, 3, 2, 1},
		RedconRules: map[uint8][]string{
			4: []string{"sparkplug", "ble"},
			3: []string{"sparkplug", "ble", PowerCapability},
			2: []string{"sparkplug", "ble", PowerCapability, BoardCapability, MCPCapability},
			1: []string{"sparkplug", "ble", PowerCapability, BoardCapability, MCPCapability, VideoCapability},
		},
	}
}

func capabilityState(adapterID string, thingName string, capabilities map[string]bool, metrics map[string]protocol.MetricValue, observedAtMS uint64, seq uint64) protocol.CapabilityState {
	if metrics == nil {
		metrics = map[string]protocol.MetricValue{}
	}
	return protocol.CapabilityState{
		SchemaVersion: protocol.SchemaVersion,
		AdapterID:     adapterID,
		ThingName:     thingName,
		Capabilities:  capabilities,
		Metrics:       metrics,
		ObservedAtMS:  observedAtMS,
		Seq:           seq,
	}
}

func redconValue(t *testing.T, value *uint8) uint8 {
	t.Helper()
	if value == nil {
		t.Fatal("redcon = nil")
	}
	return *value
}

func TestRedconRuleSelectionUsesBestReadyLevel(t *testing.T) {
	inventory := powerInventory()
	capabilities := map[string]bool{"sparkplug": true, "ble": true, "power": false}

	if got := redconValue(t, SelectBestRedcon(inventory.RedconRules, inventory.RedconCommandLevels, capabilities)); got != 4 {
		t.Fatalf("redcon = %d, want 4", got)
	}

	capabilities["power"] = true
	if got := redconValue(t, SelectBestRedcon(inventory.RedconRules, inventory.RedconCommandLevels, capabilities)); got != 3 {
		t.Fatalf("redcon = %d, want 3", got)
	}
}

func TestRedconSelectionIgnoresRulesOutsideCommandLevels(t *testing.T) {
	inventory := weatherInventoryWithStaleRedcon3Rule()
	capabilities := map[string]bool{"sparkplug": true, "ble": true, "power": true, "weather": true}

	if got := redconValue(t, SelectBestRedcon(inventory.RedconRules, inventory.RedconCommandLevels, capabilities)); got != 4 {
		t.Fatalf("redcon = %d, want 4", got)
	}
}

func TestWeatherSnapshotStaysRedcon4WithStaleRedcon3Rule(t *testing.T) {
	state := NewDeviceRuntimeState(weatherInventoryWithStaleRedcon3Rule())
	err := state.ObserveState(capabilityState(
		"dev.txing.rig.BleConnectivity",
		"weather-1",
		map[string]bool{"sparkplug": true, "ble": true, "power": true, "weather": true},
		nil,
		1000,
		1,
	))
	if err != nil {
		t.Fatal(err)
	}

	if got := redconValue(t, state.Snapshot(1000).Redcon); got != 4 {
		t.Fatalf("redcon = %d, want 4", got)
	}
	publication, err := state.DecidePublication(1000)
	if err != nil {
		t.Fatal(err)
	}
	assertPublication(t, publication, PublicationBirth, 4, []sparkplug.Metric{
		sparkplug.NewBooleanMetric("capability.ble", true),
		sparkplug.NewBooleanMetric("capability.power", true),
		sparkplug.NewBooleanMetric("capability.sparkplug", true),
		sparkplug.NewBooleanMetric("capability.weather", true),
	})
}

func TestScannerOnlyStateDoesNotDowngradeFreshWeatherState(t *testing.T) {
	state := NewDeviceRuntimeState(weatherInventoryWithStaleRedcon3Rule())
	adapterID := "dev.txing.rig.BleConnectivity"
	if err := state.ObserveState(capabilityState(
		adapterID,
		"weather-1",
		map[string]bool{"sparkplug": true, "ble": true, "power": true, "weather": true},
		map[string]protocol.MetricValue{protocol.BleRedconMetric: protocol.MetricInt32(4)},
		1000,
		1,
	)); err != nil {
		t.Fatal(err)
	}
	first, err := state.DecidePublication(1000)
	if err != nil {
		t.Fatal(err)
	}
	assertPublication(t, first, PublicationBirth, 4, []sparkplug.Metric{
		sparkplug.NewBooleanMetric("capability.ble", true),
		sparkplug.NewBooleanMetric("capability.power", true),
		sparkplug.NewBooleanMetric("capability.sparkplug", true),
		sparkplug.NewBooleanMetric("capability.weather", true),
	})

	if err := state.ObserveState(capabilityState(
		adapterID,
		"weather-1",
		map[string]bool{"sparkplug": true, "ble": true, "power": false, "weather": false},
		nil,
		1100,
		2,
	)); err != nil {
		t.Fatal(err)
	}
	snapshot := state.Snapshot(1100)
	if got := redconValue(t, snapshot.Redcon); got != 4 {
		t.Fatalf("redcon = %d, want 4", got)
	}
	for _, capability := range []string{"sparkplug", "ble", "power", "weather"} {
		if !snapshot.Capabilities[capability] {
			t.Fatalf("capability %s false after scanner-only sample: %#v", capability, snapshot.Capabilities)
		}
	}
	second, err := state.DecidePublication(1100)
	if err != nil {
		t.Fatal(err)
	}
	if second.Kind != PublicationNone {
		t.Fatalf("publication = %#v, want none", second)
	}
}

func TestScannerOnlyStateStillRefreshesScannerOnlyAvailability(t *testing.T) {
	state := NewDeviceRuntimeState(weatherInventoryWithStaleRedcon3Rule())
	adapterID := "dev.txing.rig.BleConnectivity"
	if err := state.ObserveState(capabilityState(
		adapterID,
		"weather-1",
		map[string]bool{"sparkplug": true, "ble": true, "power": false, "weather": false},
		nil,
		1000,
		1,
	)); err != nil {
		t.Fatal(err)
	}
	if err := state.ObserveState(capabilityState(
		adapterID,
		"weather-1",
		map[string]bool{"sparkplug": true, "ble": true, "power": false, "weather": false},
		nil,
		1000+StateTTLMS+1,
		2,
	)); err != nil {
		t.Fatal(err)
	}

	snapshot := state.Snapshot(1000 + StateTTLMS + 1)
	if !snapshot.SparkplugAvailable || !snapshot.Capabilities["ble"] {
		t.Fatalf("scanner-only availability was not refreshed: %#v", snapshot.Capabilities)
	}
	if snapshot.Capabilities["power"] || snapshot.Capabilities["weather"] {
		t.Fatalf("scanner-only state raised device-domain capabilities: %#v", snapshot.Capabilities)
	}
}

func TestBoardOwnedCapabilitiesImplyPowerWhenBlePowerIsUnconfirmed(t *testing.T) {
	state := NewDeviceRuntimeState(unitInventory())
	if err := state.ObserveState(capabilityState(
		"dev.txing.rig.BleConnectivity",
		"unit-1",
		map[string]bool{"sparkplug": true, "ble": true, PowerCapability: false},
		nil,
		2000,
		1,
	)); err != nil {
		t.Fatal(err)
	}
	if err := state.ObserveState(capabilityState(
		"dev.txing.board",
		"unit-1",
		map[string]bool{BoardCapability: true, MCPCapability: true, VideoCapability: false},
		nil,
		1900,
		2,
	)); err != nil {
		t.Fatal(err)
	}

	snapshot := state.Snapshot(2000)
	if got := redconValue(t, snapshot.Redcon); got != 2 {
		t.Fatalf("redcon = %d, want 2", got)
	}
	assertCapability(t, snapshot.Capabilities, PowerCapability, true)
	assertCapability(t, snapshot.Capabilities, BoardCapability, true)
	assertCapability(t, snapshot.Capabilities, MCPCapability, true)
	assertCapability(t, snapshot.Capabilities, VideoCapability, false)
	publication, err := state.DecidePublication(2000)
	if err != nil {
		t.Fatal(err)
	}
	assertPublication(t, publication, PublicationBirth, 2, []sparkplug.Metric{
		sparkplug.NewBooleanMetric("capability.ble", true),
		sparkplug.NewBooleanMetric("capability.board", true),
		sparkplug.NewBooleanMetric("capability.mcp", true),
		sparkplug.NewBooleanMetric("capability.power", true),
		sparkplug.NewBooleanMetric("capability.sparkplug", true),
		sparkplug.NewBooleanMetric("capability.video", false),
	})
}

func TestBleRedcon4EvidenceClearsBoardOwnedCapabilities(t *testing.T) {
	state := NewDeviceRuntimeState(unitInventory())
	if err := state.ObserveState(capabilityState(
		"dev.txing.rig.BleConnectivity",
		"unit-1",
		map[string]bool{"sparkplug": true, "ble": true, PowerCapability: false},
		map[string]protocol.MetricValue{protocol.BleRedconMetric: protocol.MetricInt32(4)},
		2000,
		1,
	)); err != nil {
		t.Fatal(err)
	}
	if err := state.ObserveState(capabilityState(
		"dev.txing.board",
		"unit-1",
		map[string]bool{BoardCapability: true, MCPCapability: true, VideoCapability: true},
		nil,
		1900,
		2,
	)); err != nil {
		t.Fatal(err)
	}

	snapshot := state.Snapshot(2000)
	if got := redconValue(t, snapshot.Redcon); got != 4 {
		t.Fatalf("redcon = %d, want 4", got)
	}
	assertCapability(t, snapshot.Capabilities, PowerCapability, false)
	assertCapability(t, snapshot.Capabilities, BoardCapability, false)
	assertCapability(t, snapshot.Capabilities, MCPCapability, false)
	assertCapability(t, snapshot.Capabilities, VideoCapability, false)
	publication, err := state.DecidePublication(2000)
	if err != nil {
		t.Fatal(err)
	}
	assertPublication(t, publication, PublicationBirth, 4, []sparkplug.Metric{
		sparkplug.NewBooleanMetric("capability.ble", true),
		sparkplug.NewBooleanMetric("capability.board", false),
		sparkplug.NewBooleanMetric("capability.mcp", false),
		sparkplug.NewBooleanMetric("capability.power", false),
		sparkplug.NewBooleanMetric("capability.sparkplug", true),
		sparkplug.NewBooleanMetric("capability.video", false),
	})
}

func TestBleRedcon4TransitionPublishesDataEvenWithRetainedBoardState(t *testing.T) {
	state := NewDeviceRuntimeState(unitInventory())
	if err := state.ObserveState(capabilityState(
		"dev.txing.rig.BleConnectivity",
		"unit-1",
		map[string]bool{"sparkplug": true, "ble": true, PowerCapability: true},
		map[string]protocol.MetricValue{protocol.BleRedconMetric: protocol.MetricInt32(3)},
		1000,
		1,
	)); err != nil {
		t.Fatal(err)
	}
	if err := state.ObserveState(capabilityState(
		"dev.txing.board",
		"unit-1",
		map[string]bool{BoardCapability: true, MCPCapability: true, VideoCapability: true},
		nil,
		1000,
		2,
	)); err != nil {
		t.Fatal(err)
	}
	first, err := state.DecidePublication(1000)
	if err != nil {
		t.Fatal(err)
	}
	assertPublicationKind(t, first, PublicationBirth)

	if err := state.ObserveState(capabilityState(
		"dev.txing.rig.BleConnectivity",
		"unit-1",
		map[string]bool{"sparkplug": true, "ble": true, PowerCapability: false},
		map[string]protocol.MetricValue{protocol.BleRedconMetric: protocol.MetricInt32(4)},
		2000,
		3,
	)); err != nil {
		t.Fatal(err)
	}
	second, err := state.DecidePublication(2000)
	if err != nil {
		t.Fatal(err)
	}
	assertPublication(t, second, PublicationData, 4, []sparkplug.Metric{
		sparkplug.NewBooleanMetric("capability.ble", true),
		sparkplug.NewBooleanMetric("capability.board", false),
		sparkplug.NewBooleanMetric("capability.mcp", false),
		sparkplug.NewBooleanMetric("capability.power", false),
		sparkplug.NewBooleanMetric("capability.sparkplug", true),
		sparkplug.NewBooleanMetric("capability.video", false),
	})
}

func TestNewerBoardCapabilitiesSupersedeOlderBleRedcon4Evidence(t *testing.T) {
	state := NewDeviceRuntimeState(unitInventory())
	if err := state.ObserveState(capabilityState(
		"dev.txing.rig.BleConnectivity",
		"unit-1",
		map[string]bool{"sparkplug": true, "ble": true, PowerCapability: false},
		map[string]protocol.MetricValue{protocol.BleRedconMetric: protocol.MetricInt32(4)},
		2000,
		1,
	)); err != nil {
		t.Fatal(err)
	}
	if err := state.ObserveState(capabilityState(
		"dev.txing.board",
		"unit-1",
		map[string]bool{BoardCapability: true, MCPCapability: true, VideoCapability: true},
		nil,
		2100,
		2,
	)); err != nil {
		t.Fatal(err)
	}
	snapshot := state.Snapshot(2100)
	if got := redconValue(t, snapshot.Redcon); got != 1 {
		t.Fatalf("redcon = %d, want 1", got)
	}
	assertCapability(t, snapshot.Capabilities, PowerCapability, true)
}

func TestBleRedcon4ForgetsOlderBoardCapabilitiesUntilFreshBoardUpdate(t *testing.T) {
	state := NewDeviceRuntimeState(unitInventory())
	if err := state.ObserveState(capabilityState(
		"dev.txing.board",
		"unit-1",
		map[string]bool{BoardCapability: true, MCPCapability: true, VideoCapability: true},
		nil,
		1000,
		1,
	)); err != nil {
		t.Fatal(err)
	}
	if err := state.ObserveState(capabilityState(
		"dev.txing.rig.BleConnectivity",
		"unit-1",
		map[string]bool{"sparkplug": true, "ble": true, PowerCapability: false},
		map[string]protocol.MetricValue{protocol.BleRedconMetric: protocol.MetricInt32(4)},
		2000,
		2,
	)); err != nil {
		t.Fatal(err)
	}

	snapshot := state.Snapshot(2000)
	if got := redconValue(t, snapshot.Redcon); got != 4 {
		t.Fatalf("redcon = %d, want 4", got)
	}
	assertCapability(t, snapshot.Capabilities, BoardCapability, false)

	if err := state.ObserveState(capabilityState(
		"dev.txing.board",
		"unit-1",
		map[string]bool{BoardCapability: true, MCPCapability: true, VideoCapability: true},
		nil,
		3000,
		3,
	)); err != nil {
		t.Fatal(err)
	}
	snapshot = state.Snapshot(3000)
	if got := redconValue(t, snapshot.Redcon); got != 1 {
		t.Fatalf("redcon = %d, want 1", got)
	}
}

func TestStaleStateRemovesCapabilityAvailability(t *testing.T) {
	state := NewDeviceRuntimeState(powerInventory())
	if err := state.ObserveState(capabilityState(
		"dev.txing.rig.BleConnectivity",
		"power-1",
		map[string]bool{"sparkplug": true, "ble": true, "power": true},
		nil,
		1000,
		1,
	)); err != nil {
		t.Fatal(err)
	}
	if got := redconValue(t, state.Snapshot(1000+StateTTLMS).Redcon); got != 3 {
		t.Fatalf("redcon before ttl = %d, want 3", got)
	}
	if got := state.Snapshot(1000 + StateTTLMS + 1).Redcon; got != nil {
		t.Fatalf("redcon after ttl = %#v, want nil", got)
	}
}

func TestInitiallyUnavailableDevicePublishesDeathOnce(t *testing.T) {
	state := NewDeviceRuntimeState(powerInventory())
	first, err := state.DecidePublication(1000)
	if err != nil {
		t.Fatal(err)
	}
	assertPublicationKind(t, first, PublicationDeath)
	second, err := state.DecidePublication(1001)
	if err != nil {
		t.Fatal(err)
	}
	assertPublicationKind(t, second, PublicationNone)
}

func TestPublicationLifecycleBirthDataAndDeath(t *testing.T) {
	state := NewDeviceRuntimeState(powerInventory())
	if err := state.ObserveState(capabilityState(
		"dev.txing.rig.BleConnectivity",
		"power-1",
		map[string]bool{"sparkplug": true, "ble": true, "power": false},
		nil,
		1000,
		1,
	)); err != nil {
		t.Fatal(err)
	}
	first, err := state.DecidePublication(1000)
	if err != nil {
		t.Fatal(err)
	}
	assertPublicationKind(t, first, PublicationBirth)

	if err := state.ObserveState(capabilityState(
		"dev.txing.rig.BleConnectivity",
		"power-1",
		map[string]bool{"sparkplug": true, "ble": true, "power": true},
		nil,
		2000,
		2,
	)); err != nil {
		t.Fatal(err)
	}
	second, err := state.DecidePublication(2000)
	if err != nil {
		t.Fatal(err)
	}
	assertPublicationKind(t, second, PublicationData)

	if err := state.ObserveState(capabilityState(
		"dev.txing.rig.BleConnectivity",
		"power-1",
		map[string]bool{"sparkplug": false, "ble": false, "power": false},
		nil,
		2000+StateTTLMS+1,
		3,
	)); err != nil {
		t.Fatal(err)
	}
	third, err := state.DecidePublication(2000 + StateTTLMS + 1)
	if err != nil {
		t.Fatal(err)
	}
	assertPublicationKind(t, third, PublicationDeath)
	fourth, err := state.DecidePublication(2000 + StateTTLMS + 2)
	if err != nil {
		t.Fatal(err)
	}
	assertPublicationKind(t, fourth, PublicationNone)
}

func TestExplicitBleUnavailablePublishesDeathEvenWithFreshPriorState(t *testing.T) {
	state := NewDeviceRuntimeState(powerInventory())
	if err := state.ObserveState(capabilityState(
		"dev.txing.rig.BleConnectivity",
		"power-1",
		map[string]bool{"sparkplug": true, "ble": true, "power": true},
		nil,
		1000,
		1,
	)); err != nil {
		t.Fatal(err)
	}
	first, err := state.DecidePublication(1000)
	if err != nil {
		t.Fatal(err)
	}
	assertPublicationKind(t, first, PublicationBirth)

	if err := state.ObserveState(capabilityState(
		"dev.txing.rig.BleConnectivity",
		"power-1",
		map[string]bool{"sparkplug": false, "ble": false, "power": false},
		nil,
		30_000,
		2,
	)); err != nil {
		t.Fatal(err)
	}
	second, err := state.DecidePublication(30_000)
	if err != nil {
		t.Fatal(err)
	}
	assertPublicationKind(t, second, PublicationDeath)
	if got := state.Snapshot(30_000).Redcon; got != nil {
		t.Fatalf("redcon after explicit unavailable = %#v, want nil", got)
	}

	third, err := state.DecidePublication(1000 + StateTTLMS + 1)
	if err != nil {
		t.Fatal(err)
	}
	assertPublicationKind(t, third, PublicationNone)
}

func TestDCMDPayloadTranslatesToV2RedconCommand(t *testing.T) {
	payload, err := sparkplug.BuildRedconPayload(3, 9, 1714380000000)
	if err != nil {
		t.Fatal(err)
	}
	deadline := uint64(3000)
	command, err := CommandFromDCMD("power-1", payload, "cmd-1", 2000, &deadline)
	if err != nil {
		t.Fatal(err)
	}
	if command == nil {
		t.Fatal("expected command")
	}
	if command.Target.Redcon != 3 || command.Seq != 9 || command.IssuedAtMS != 2000 || command.DeadlineMS == nil || *command.DeadlineMS != 3000 {
		t.Fatalf("command = %#v", command)
	}
}

func TestCommandResultProjectsToSparkplugMetrics(t *testing.T) {
	target := uint8(3)
	message := "ok"
	result := protocol.NewCapabilityCommandResult("dev.txing.rig.BleConnectivity", "cmd-1", "power-1", protocol.CommandSucceeded, 2000, 7)
	result.Target.Redcon = &target
	result.Message = &message

	metrics, err := CommandResultMetrics(result)
	if err != nil {
		t.Fatal(err)
	}
	want := []sparkplug.Metric{
		sparkplug.NewStringMetric("redconCommandStatus", protocol.CommandSucceeded),
		sparkplug.NewInt32Metric("redconCommandSeq", 7),
		sparkplug.NewStringMetric("redconCommandId", "cmd-1"),
		sparkplug.NewInt32Metric("redconCommandTarget", 3),
		sparkplug.NewStringMetric("redconCommandMessage", "ok"),
	}
	if len(metrics) != len(want) {
		t.Fatalf("metric count = %d, want %d", len(metrics), len(want))
	}
	for index := range want {
		if metrics[index] != want[index] {
			t.Fatalf("metric %d = %#v, want %#v", index, metrics[index], want[index])
		}
	}
}

func TestMqttSessionSpecsUseExpectedLWTTopics(t *testing.T) {
	node, err := NodeSessionSpec("town-1", "rig-1", "rig-1-sparkplug-manager", 11, 1000)
	if err != nil {
		t.Fatal(err)
	}
	if node.ClientID != "rig-1-sparkplug-manager" || node.Will.Topic != "spBv1.0/town-1/NDEATH/rig-1" {
		t.Fatalf("node session = %#v", node)
	}
	device, err := DeviceSessionSpec("town-1", "rig-1", "unit-1", 1000)
	if err != nil {
		t.Fatal(err)
	}
	if device.ClientID != "unit-1" || device.Will.Topic != "spBv1.0/town-1/DDEATH/rig-1/unit-1" {
		t.Fatalf("device session = %#v", device)
	}
}

func assertCapability(t *testing.T, capabilities map[string]bool, name string, want bool) {
	t.Helper()
	got, ok := capabilities[name]
	if !ok {
		t.Fatalf("missing capability %s", name)
	}
	if got != want {
		t.Fatalf("capability %s = %t, want %t", name, got, want)
	}
}

func assertPublicationKind(t *testing.T, publication DevicePublication, kind DevicePublicationKind) {
	t.Helper()
	if publication.Kind != kind {
		t.Fatalf("publication kind = %d, want %d; publication=%#v", publication.Kind, kind, publication)
	}
}

func assertPublication(t *testing.T, publication DevicePublication, kind DevicePublicationKind, redcon uint8, metrics []sparkplug.Metric) {
	t.Helper()
	assertPublicationKind(t, publication, kind)
	if publication.Redcon != redcon {
		t.Fatalf("publication redcon = %d, want %d", publication.Redcon, redcon)
	}
	if len(publication.Metrics) != len(metrics) {
		t.Fatalf("metric count = %d, want %d: %#v", len(publication.Metrics), len(metrics), publication.Metrics)
	}
	for index := range metrics {
		if publication.Metrics[index] != metrics[index] {
			t.Fatalf("metric %d = %#v, want %#v", index, publication.Metrics[index], metrics[index])
		}
	}
}
