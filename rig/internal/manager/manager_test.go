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

func powerSIInventory() protocol.InventoryDevice {
	return protocol.InventoryDevice{
		ThingName:           "power-si-1",
		ThingType:           "power-si",
		Capabilities:        []string{"sparkplug", "thread", "power"},
		RedconCommandLevels: []uint8{4, 3},
		RedconRules: map[uint8][]string{
			4: []string{"sparkplug", "thread"},
			3: []string{"sparkplug", "thread", "power"},
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

func tbotInventory() protocol.InventoryDevice {
	return protocol.InventoryDevice{
		ThingName:           "tbot-1",
		ThingType:           "tbot",
		Capabilities:        []string{"sparkplug", "thread", PowerCapability, BoardCapability, MCPCapability, VideoCapability},
		RedconCommandLevels: []uint8{4, 3, 2, 1},
		RedconRules: map[uint8][]string{
			4: {"sparkplug", "thread"},
			3: {"sparkplug", "thread", PowerCapability},
			2: {"sparkplug", "thread", PowerCapability, BoardCapability, MCPCapability},
			1: {"sparkplug", "thread", PowerCapability, BoardCapability, MCPCapability, VideoCapability},
		},
	}
}

func cyberbrickInventory() protocol.InventoryDevice {
	return protocol.InventoryDevice{
		ThingName:           "cyberbrick-1",
		ThingType:           "cyberbrick",
		Capabilities:        []string{"sparkplug", "ble", PowerCapability, BoardCapability, MAVLinkCapability, VideoCapability},
		RedconCommandLevels: []uint8{4, 3, 2, 1},
		RedconRules: map[uint8][]string{
			4: []string{"sparkplug", "ble"},
			3: []string{"sparkplug", "ble", PowerCapability},
			2: []string{"sparkplug", "ble", PowerCapability, BoardCapability, MAVLinkCapability},
			1: []string{"sparkplug", "ble", PowerCapability, BoardCapability, MAVLinkCapability, VideoCapability},
		},
		RedconMetricRules: map[uint8][]string{
			1: []string{protocol.MavlinkArmedMetric},
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

func TestCyberbrickMavlinkArmedMetricGatesRedconOneWithoutPublishingIt(t *testing.T) {
	state := NewDeviceRuntimeState(cyberbrickInventory())
	if err := state.ObserveState(capabilityState(
		"dev.txing.rig.BleConnectivity",
		"cyberbrick-1",
		map[string]bool{"sparkplug": true, "ble": true, PowerCapability: true},
		nil,
		1000,
		1,
	)); err != nil {
		t.Fatal(err)
	}
	if err := state.ObserveState(capabilityState(
		"dev.txing.cyberbrick.Daemon",
		"cyberbrick-1",
		map[string]bool{BoardCapability: true, MAVLinkCapability: true, VideoCapability: true},
		map[string]protocol.MetricValue{protocol.MavlinkArmedMetric: protocol.MetricBoolean(false)},
		1000,
		2,
	)); err != nil {
		t.Fatal(err)
	}
	first := state.Snapshot(1000)
	if got := redconValue(t, first.Redcon); got != 2 {
		t.Fatalf("disarmed Cyberbrick REDCON = %d, want 2", got)
	}
	publication, err := state.DecidePublication(1000)
	if err != nil {
		t.Fatal(err)
	}
	for _, metric := range publication.Metrics {
		if metric.Name == protocol.MavlinkArmedMetric {
			t.Fatal("mavlinkArmed must remain an internal REDCON input")
		}
	}

	if err := state.ObserveState(capabilityState(
		"dev.txing.cyberbrick.Daemon",
		"cyberbrick-1",
		map[string]bool{BoardCapability: true, MAVLinkCapability: true, VideoCapability: true},
		map[string]protocol.MetricValue{protocol.MavlinkArmedMetric: protocol.MetricBoolean(true)},
		1100,
		3,
	)); err != nil {
		t.Fatal(err)
	}
	if got := redconValue(t, state.Snapshot(1100).Redcon); got != 1 {
		t.Fatalf("armed Cyberbrick REDCON = %d, want 1", got)
	}
}

func TestCyberbrickMavlinkRedconMatrix(t *testing.T) {
	cases := []struct {
		name             string
		mavlinkAvailable bool
		videoAvailable   bool
		mavlinkArmed     bool
		wantRedcon       uint8
	}{
		{
			name:             "board powered with MAVLink unavailable",
			mavlinkAvailable: false,
			videoAvailable:   false,
			mavlinkArmed:     false,
			wantRedcon:       3,
		},
		{
			name:             "MAVLink ready without an Office peer and disarmed",
			mavlinkAvailable: true,
			videoAvailable:   false,
			mavlinkArmed:     false,
			wantRedcon:       2,
		},
		{
			name:             "MAVLink and video ready but disarmed",
			mavlinkAvailable: true,
			videoAvailable:   true,
			mavlinkArmed:     false,
			wantRedcon:       2,
		},
		{
			name:             "MAVLink armed without video",
			mavlinkAvailable: true,
			videoAvailable:   false,
			mavlinkArmed:     true,
			wantRedcon:       2,
		},
		{
			name:             "MAVLink armed with video",
			mavlinkAvailable: true,
			videoAvailable:   true,
			mavlinkArmed:     true,
			wantRedcon:       1,
		},
	}

	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			state := NewDeviceRuntimeState(cyberbrickInventory())
			if err := state.ObserveState(capabilityState(
				"dev.txing.rig.BleConnectivity",
				"cyberbrick-1",
				map[string]bool{"sparkplug": true, "ble": true, PowerCapability: true},
				nil,
				1000,
				1,
			)); err != nil {
				t.Fatal(err)
			}
			if err := state.ObserveState(capabilityState(
				"dev.txing.cyberbrick.Daemon",
				"cyberbrick-1",
				map[string]bool{
					BoardCapability:   true,
					MAVLinkCapability: testCase.mavlinkAvailable,
					VideoCapability:   testCase.videoAvailable,
				},
				map[string]protocol.MetricValue{
					protocol.MavlinkArmedMetric: protocol.MetricBoolean(testCase.mavlinkArmed),
				},
				1000,
				2,
			)); err != nil {
				t.Fatal(err)
			}

			if got := redconValue(t, state.Snapshot(1000).Redcon); got != testCase.wantRedcon {
				t.Fatalf("REDCON = %d, want %d", got, testCase.wantRedcon)
			}
		})
	}
}

func TestCyberbrickRedconFourClearsMavlinkStateAndArmingInput(t *testing.T) {
	state := NewDeviceRuntimeState(cyberbrickInventory())
	if err := state.ObserveState(capabilityState(
		"dev.txing.rig.BleConnectivity",
		"cyberbrick-1",
		map[string]bool{"sparkplug": true, "ble": true, PowerCapability: true},
		nil,
		1000,
		1,
	)); err != nil {
		t.Fatal(err)
	}
	if err := state.ObserveState(capabilityState(
		"dev.txing.cyberbrick.Daemon",
		"cyberbrick-1",
		map[string]bool{BoardCapability: true, MAVLinkCapability: true, VideoCapability: true},
		map[string]protocol.MetricValue{protocol.MavlinkArmedMetric: protocol.MetricBoolean(true)},
		1000,
		2,
	)); err != nil {
		t.Fatal(err)
	}
	if got := redconValue(t, state.Snapshot(1000).Redcon); got != 1 {
		t.Fatalf("armed MAVLink REDCON = %d, want 1", got)
	}

	if err := state.ObserveState(capabilityState(
		"dev.txing.rig.BleConnectivity",
		"cyberbrick-1",
		map[string]bool{"sparkplug": true, "ble": true, PowerCapability: false},
		map[string]protocol.MetricValue{protocol.BleRedconMetric: protocol.MetricInt32(4)},
		1100,
		3,
	)); err != nil {
		t.Fatal(err)
	}

	snapshot := state.Snapshot(1100)
	if got := redconValue(t, snapshot.Redcon); got != 4 {
		t.Fatalf("REDCON after shutdown state = %d, want 4", got)
	}
	for _, capability := range []string{PowerCapability, BoardCapability, MAVLinkCapability, VideoCapability} {
		assertCapability(t, snapshot.Capabilities, capability, false)
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

func TestThreadPowerSIStateSelectsRedconFromThreadCapabilities(t *testing.T) {
	state := NewDeviceRuntimeState(powerSIInventory())
	if err := state.ObserveState(capabilityState(
		"dev.txing.rig.ThreadConnectivity",
		"power-si-1",
		map[string]bool{"sparkplug": true, "thread": true, PowerCapability: false},
		map[string]protocol.MetricValue{protocol.TransportRedconMetric: protocol.MetricInt32(4)},
		1000,
		1,
	)); err != nil {
		t.Fatal(err)
	}
	snapshot := state.Snapshot(1000)
	if got := redconValue(t, snapshot.Redcon); got != 4 {
		t.Fatalf("redcon = %d, want 4", got)
	}
	assertCapability(t, snapshot.Capabilities, "thread", true)
	assertCapability(t, snapshot.Capabilities, PowerCapability, false)
	publication, err := state.DecidePublication(1000)
	if err != nil {
		t.Fatal(err)
	}
	assertPublication(t, publication, PublicationBirth, 4, []sparkplug.Metric{
		sparkplug.NewBooleanMetric("capability.power", false),
		sparkplug.NewBooleanMetric("capability.sparkplug", true),
		sparkplug.NewBooleanMetric("capability.thread", true),
	})

	if err := state.ObserveState(capabilityState(
		"dev.txing.rig.ThreadConnectivity",
		"power-si-1",
		map[string]bool{"sparkplug": true, "thread": true, PowerCapability: true},
		map[string]protocol.MetricValue{protocol.TransportRedconMetric: protocol.MetricInt32(3)},
		2000,
		2,
	)); err != nil {
		t.Fatal(err)
	}
	snapshot = state.Snapshot(2000)
	if got := redconValue(t, snapshot.Redcon); got != 3 {
		t.Fatalf("redcon = %d, want 3", got)
	}
	assertCapability(t, snapshot.Capabilities, "thread", true)
	assertCapability(t, snapshot.Capabilities, PowerCapability, true)
	publication, err = state.DecidePublication(2000)
	if err != nil {
		t.Fatal(err)
	}
	assertPublication(t, publication, PublicationData, 3, []sparkplug.Metric{
		sparkplug.NewBooleanMetric("capability.power", true),
		sparkplug.NewBooleanMetric("capability.sparkplug", true),
		sparkplug.NewBooleanMetric("capability.thread", true),
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

func TestTbotThreadLossForgetsBoardEvidenceAndRecoversOnlyAfterFreshState(t *testing.T) {
	state := NewDeviceRuntimeState(tbotInventory())
	threadAdapter := "dev.txing.rig.ThreadConnectivity"
	boardAdapter := "dev.txing.tbot.DaemonBoard"
	threadOnline := map[string]bool{"sparkplug": true, "thread": true, PowerCapability: true}
	threadOffline := map[string]bool{"sparkplug": false, "thread": false, PowerCapability: false}
	boardAndMCPReady := map[string]bool{BoardCapability: true, MCPCapability: true, VideoCapability: false}
	boardReady := map[string]bool{BoardCapability: true, MCPCapability: true, VideoCapability: true}

	if err := state.ObserveState(capabilityState(threadAdapter, "tbot-1", threadOnline,
		map[string]protocol.MetricValue{protocol.TransportRedconMetric: protocol.MetricInt32(3)}, 1000, 1)); err != nil {
		t.Fatal(err)
	}
	if err := state.ObserveState(capabilityState(boardAdapter, "tbot-1", boardReady, nil, 1100, 1)); err != nil {
		t.Fatal(err)
	}
	if got := redconValue(t, state.Snapshot(1100).Redcon); got != 1 {
		t.Fatalf("initial REDCON = %d, want 1", got)
	}
	if publication, err := state.DecidePublication(1100); err != nil || publication.Kind != PublicationBirth {
		t.Fatalf("initial publication = %#v, %v; want DBIRTH", publication, err)
	}

	if err := state.ObserveState(capabilityState(threadAdapter, "tbot-1", threadOffline, nil, 2000, 2)); err != nil {
		t.Fatal(err)
	}
	if snapshot := state.Snapshot(2000); snapshot.Redcon != nil || snapshot.Capabilities[BoardCapability] || snapshot.Capabilities[MCPCapability] || snapshot.Capabilities[VideoCapability] {
		t.Fatalf("Thread loss snapshot = %#v, want unavailable with board capabilities cleared", snapshot)
	}
	if publication, err := state.DecidePublication(2000); err != nil || publication.Kind != PublicationDeath {
		t.Fatalf("Thread loss publication = %#v, %v; want one DDEATH", publication, err)
	}
	if publication, err := state.DecidePublication(2001); err != nil || publication.Kind != PublicationNone {
		t.Fatalf("duplicate Thread loss publication = %#v, %v; want none", publication, err)
	}

	if err := state.ObserveState(capabilityState(threadAdapter, "tbot-1", threadOnline,
		map[string]protocol.MetricValue{protocol.TransportRedconMetric: protocol.MetricInt32(3)}, 3000, 3)); err != nil {
		t.Fatal(err)
	}
	if got := redconValue(t, state.Snapshot(3000).Redcon); got != 3 {
		t.Fatalf("recovered REDCON = %d, want 3 until fresh board evidence", got)
	}
	if publication, err := state.DecidePublication(3000); err != nil || publication.Kind != PublicationBirth || publication.Redcon != 3 {
		t.Fatalf("recovery publication = %#v, %v; want REDCON 3 DBIRTH", publication, err)
	}

	if err := state.ObserveState(capabilityState(boardAdapter, "tbot-1", boardAndMCPReady, nil, 3100, 2)); err != nil {
		t.Fatal(err)
	}
	if publication, err := state.DecidePublication(3100); err != nil || publication.Kind != PublicationData || publication.Redcon != 2 {
		t.Fatalf("fresh board/MCP publication = %#v, %v; want REDCON 2 DDATA", publication, err)
	}
	if err := state.ObserveState(capabilityState(boardAdapter, "tbot-1", boardReady, nil, 3200, 3)); err != nil {
		t.Fatal(err)
	}
	if publication, err := state.DecidePublication(3200); err != nil || publication.Kind != PublicationData || publication.Redcon != 1 {
		t.Fatalf("fresh video publication = %#v, %v; want REDCON 1 DDATA", publication, err)
	}
}

func TestTbotThreadRedconFourForgetsBoardEvidenceUntilFreshUpdate(t *testing.T) {
	state := NewDeviceRuntimeState(tbotInventory())
	threadAdapter := "dev.txing.rig.ThreadConnectivity"
	boardAdapter := "dev.txing.tbot.DaemonBoard"
	if err := state.ObserveState(capabilityState(threadAdapter, "tbot-1",
		map[string]bool{"sparkplug": true, "thread": true, PowerCapability: true},
		map[string]protocol.MetricValue{protocol.TransportRedconMetric: protocol.MetricInt32(3)}, 1000, 1)); err != nil {
		t.Fatal(err)
	}
	if err := state.ObserveState(capabilityState(boardAdapter, "tbot-1",
		map[string]bool{BoardCapability: true, MCPCapability: true, VideoCapability: true}, nil, 1100, 1)); err != nil {
		t.Fatal(err)
	}
	if err := state.ObserveState(capabilityState(threadAdapter, "tbot-1",
		map[string]bool{"sparkplug": true, "thread": true, PowerCapability: false},
		map[string]protocol.MetricValue{protocol.TransportRedconMetric: protocol.MetricInt32(4)}, 2000, 2)); err != nil {
		t.Fatal(err)
	}
	snapshot := state.Snapshot(2000)
	if got := redconValue(t, snapshot.Redcon); got != 4 || snapshot.Capabilities[BoardCapability] || snapshot.Capabilities[MCPCapability] || snapshot.Capabilities[VideoCapability] {
		t.Fatalf("REDCON 4 snapshot = %#v, want REDCON 4 with board capabilities cleared", snapshot)
	}
	if err := state.ObserveState(capabilityState(threadAdapter, "tbot-1",
		map[string]bool{"sparkplug": true, "thread": true, PowerCapability: true},
		map[string]protocol.MetricValue{protocol.TransportRedconMetric: protocol.MetricInt32(3)}, 3000, 3)); err != nil {
		t.Fatal(err)
	}
	if got := redconValue(t, state.Snapshot(3000).Redcon); got != 3 {
		t.Fatalf("wake REDCON = %d, want 3 until fresh board state", got)
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
	if got := NodeClientID("rig-1"); got != "rig-1" {
		t.Fatalf("node client id = %s, want rig-1", got)
	}
	node, err := NodeSessionSpec("town-1", "rig-1", NodeClientID("rig-1"), 11, 1000)
	if err != nil {
		t.Fatal(err)
	}
	if node.ClientID != "rig-1" || node.Will.Topic != "spBv1.0/town-1/NDEATH/rig-1" {
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
