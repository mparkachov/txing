package ble

import (
	"testing"

	"github.com/mparkachov/txing/rig/internal/protocol"
)

func inventoryDevice(thingName string, capabilities []string) protocol.InventoryDevice {
	return protocol.InventoryDevice{
		ThingName:           thingName,
		ThingType:           "test",
		Capabilities:        capabilities,
		RedconCommandLevels: []uint8{4, 3},
		RedconRules: map[uint8][]string{
			4: []string{"sparkplug", "ble"},
			3: []string{"sparkplug", "ble", "power"},
		},
	}
}

func TestInventoryFilterSelectsPowerAndWeatherOnly(t *testing.T) {
	if spec := DeviceSpecFromInventory(inventoryDevice("power-1", []string{"sparkplug", "ble", "power"})); spec == nil || spec.Kind != DeviceKindPower {
		t.Fatalf("power spec = %#v", spec)
	}
	if spec := DeviceSpecFromInventory(inventoryDevice("weather-1", []string{"sparkplug", "ble", "power", "weather"})); spec == nil || spec.Kind != DeviceKindWeather {
		t.Fatalf("weather spec = %#v", spec)
	}
	if spec := DeviceSpecFromInventory(inventoryDevice("board-1", []string{"sparkplug", "board"})); spec != nil {
		t.Fatalf("board spec = %#v, want nil", spec)
	}
	if spec := DeviceSpecFromInventory(inventoryDevice("ble-1", []string{"sparkplug", "ble"})); spec != nil {
		t.Fatalf("ble-only spec = %#v, want nil", spec)
	}
}

func TestUnitInventoryWithBlePowerUsesPowerProfile(t *testing.T) {
	spec := DeviceSpecFromInventory(inventoryDevice("unit-1", []string{"sparkplug", "ble", "power", "board", "mcp", "video"}))
	if spec == nil || spec.Kind != DeviceKindPower || spec.ThingName != "unit-1" {
		t.Fatalf("unit spec = %#v", spec)
	}
}

func TestPendingShadowUpdatesCoalesceByTopicAndRetryAfterOtherTopics(t *testing.T) {
	pending := NewPendingShadowUpdates()
	pending.Push(ShadowUpdate{Topic: "a", Payload: []byte("old-a")})
	pending.Push(ShadowUpdate{Topic: "b", Payload: []byte("b")})
	pending.Push(ShadowUpdate{Topic: "a", Payload: []byte("new-a")})

	if pending.Len() != 2 {
		t.Fatalf("len = %d, want 2", pending.Len())
	}
	first := pending.Pop()
	if first == nil || first.Topic != "a" || string(first.Payload) != "new-a" {
		t.Fatalf("first = %#v", first)
	}
	pending.Push(*first)
	second := pending.Pop()
	if second == nil || second.Topic != "b" {
		t.Fatalf("second = %#v", second)
	}
	third := pending.Pop()
	if third == nil || third.Topic != "a" || string(third.Payload) != "new-a" {
		t.Fatalf("third = %#v", third)
	}
	if !pending.Empty() {
		t.Fatal("pending should be empty")
	}
}

func TestWeatherCommandRejectsRedconThreeBeforeBleWrite(t *testing.T) {
	command, err := protocol.NewCapabilityCommand("cmd-1", "weather-1", 3, "test", 1000, 1, nil)
	if err != nil {
		t.Fatal(err)
	}
	reason := WeatherCommandRejectReason(command, DeviceSpec{ThingName: "weather-1", Kind: DeviceKindWeather})
	if reason == nil {
		t.Fatal("expected rejection reason")
	}
	command.Target.Redcon = 4
	if reason := WeatherCommandRejectReason(command, DeviceSpec{ThingName: "weather-1", Kind: DeviceKindWeather}); reason != nil {
		t.Fatalf("unexpected rejection reason %q", *reason)
	}
}

func TestAdvertisementCapabilityStateIsPublishedForManagedDevices(t *testing.T) {
	if !AdvertisementPublishesCapabilityState(DeviceSpec{ThingName: "unit-1", Kind: DeviceKindPower}) {
		t.Fatal("power advertisements should publish BLE reachability state")
	}
	if !AdvertisementPublishesCapabilityState(DeviceSpec{ThingName: "weather-1", Kind: DeviceKindWeather}) {
		t.Fatal("weather advertisements should publish BLE reachability state")
	}
}

func TestTransientBleCommandConnectErrorsAreRetryable(t *testing.T) {
	retryable := []string{
		"operation already in progress",
		"No discovery started",
		"resource temporarily unavailable",
		"peripheral not found",
		"no BLE advertisement has been observed for unit-1",
		"last BLE advertisement for unit-1 is stale",
		"BLE peripheral AA:BB:CC:DD:EE:FF is not visible",
		"connect BLE peripheral: le-connection-abort-by-local",
	}
	for _, message := range retryable {
		if !BLECommandConnectErrorIsRetryable(message) {
			t.Fatalf("expected retryable: %s", message)
		}
	}
	if BLECommandConnectErrorIsRetryable("permission denied") {
		t.Fatal("permission denied should not be command retryable")
	}
}

func TestBluezInProgressUsesExtendedRetryDelay(t *testing.T) {
	if !BLEErrorIndicatesInProgress("Operation already in progress") {
		t.Fatal("expected in-progress detection")
	}
	if got := BoundedRetryDelayMS(BluezInProgressReconnectDelayMS, 0, BLERetryMaxDelayMS); got != BluezInProgressReconnectDelayMS {
		t.Fatalf("delay = %d", got)
	}
}

func TestBleResourceExhaustionUsesSlowRetryDelay(t *testing.T) {
	if !BLEErrorIndicatesHostResourceExhaustion("Resource temporarily unavailable") {
		t.Fatal("expected resource exhaustion detection")
	}
	if got := BoundedRetryDelayMS(BLUEResourceExhaustedReconnectDelayMS, 0, BLERetryMaxDelayMS); got != BLUEResourceExhaustedReconnectDelayMS {
		t.Fatalf("delay = %d", got)
	}
}

func TestConnectFailuresBackOffExponentially(t *testing.T) {
	if got := BoundedRetryDelayMS(1_000, 0, 120_000); got != 1_000 {
		t.Fatalf("delay0 = %d", got)
	}
	if got := BoundedRetryDelayMS(1_000, 1, 120_000); got != 2_000 {
		t.Fatalf("delay1 = %d", got)
	}
	if got := BoundedRetryDelayMS(1_000, 7, 120_000); got != 120_000 {
		t.Fatalf("delay7 = %d", got)
	}
	if StableJitterMS("thing-1", 1_000) > 1_000 {
		t.Fatal("jitter exceeded max")
	}
}

func TestScannerRetryClassifiers(t *testing.T) {
	if !BLEErrorIndicatesInProgress("scan already in progress") {
		t.Fatal("expected scan already active to be in-progress")
	}
	if !BLEErrorIndicatesNoDiscovery("No discovery started") {
		t.Fatal("expected no discovery detection")
	}
}

func TestScannerAdvertisementFilterOnlyPublishesTargetNamesOnInterval(t *testing.T) {
	name := "power-1"
	rssi := int16(-42)
	advertisement := Advertisement{
		Address:      "AA:BB:CC:DD:EE:FF",
		IdentityName: &name,
		Services:     []string{TxingBLEServiceUUID},
		RSSI:         &rssi,
		ObservedAtMS: 1,
		Seq:          1,
	}
	targets := map[string]struct{}{"power-1": struct{}{}}
	last := map[string]uint64{}
	if !ShouldPublishScannerAdvertisement(targets, advertisement, 1000, last, 1000) {
		t.Fatal("expected first publish")
	}
	if ShouldPublishScannerAdvertisement(targets, advertisement, 1500, last, 1000) {
		t.Fatal("expected second publish to be throttled")
	}
	if !ShouldPublishScannerAdvertisement(targets, advertisement, 2000, last, 1000) {
		t.Fatal("expected publish at interval boundary")
	}
	other := "other"
	advertisement.IdentityName = &other
	if ShouldPublishScannerAdvertisement(targets, advertisement, 3000, last, 1000) {
		t.Fatal("unexpected unmanaged target publish")
	}
}

func TestScannerPrefersAdvertisedNameAsIdentity(t *testing.T) {
	name := "weather-1"
	advertisement := Advertisement{Address: "AA:BB:CC:DD:EE:FF", IdentityName: &name}
	if got := ScannerReportedIdentityName(advertisement); got != "weather-1" {
		t.Fatalf("identity = %q", got)
	}
}

func TestUnmanagedTxingAdvertisementWarningIsThrottledByName(t *testing.T) {
	name := "rogue"
	advertisement := Advertisement{IdentityName: &name, Services: []string{TxingBLEServiceUUID}}
	last := map[string]uint64{}
	if !ShouldLogUnmanagedTxingAdvertisement(advertisement, 1000, last) {
		t.Fatal("expected first warning")
	}
	if ShouldLogUnmanagedTxingAdvertisement(advertisement, 2000, last) {
		t.Fatal("expected warning throttled")
	}
	if !ShouldLogUnmanagedTxingAdvertisement(advertisement, 31_000, last) {
		t.Fatal("expected warning after throttle interval")
	}
}

func TestMacOSPlaceholderBleAddressIsNotMatchableIdentity(t *testing.T) {
	for _, address := range []string{"", "00:00:00:00:00:00", "ff:ff:ff:ff:ff:ff", "unknown"} {
		if BLEAddressIsMatchable(address) {
			t.Fatalf("address %q should not be matchable", address)
		}
	}
	if !BLEAddressIsMatchable("AA:BB:CC:DD:EE:FF") {
		t.Fatal("expected real address to be matchable")
	}
}

func TestBleConnectSessionTimeoutIsBoundedBelowStateTTLWindow(t *testing.T) {
	if got := ConnectSessionTimeoutMS(8_000); got != 10_000 {
		t.Fatalf("timeout = %d, want 10000", got)
	}
	if got := ConnectSessionTimeoutMS(30_000); got != BLEConnectSessionMaxTimeoutMS {
		t.Fatalf("timeout = %d, want max", got)
	}
}

func TestScannerEventsAreFreshAdvertisementEvidence(t *testing.T) {
	rssi := int16(-55)
	if !ScannerAdvertisementHasFreshSignal(&rssi) {
		t.Fatal("expected RSSI event to be fresh")
	}
	if ScannerAdvertisementHasFreshSignal(nil) {
		t.Fatal("nil RSSI should not be fresh evidence")
	}
}

func TestCommandResultTopicsUseComponentAdapterID(t *testing.T) {
	command, err := protocol.NewCapabilityCommand("cmd-1", "unit-1", 3, "test", 1000, 1, nil)
	if err != nil {
		t.Fatal(err)
	}
	target := uint8(3)
	message := "ok"
	topic, payload, err := PublishCommandResult(AdapterID, command, protocol.CommandSucceeded, &message, &target, 2000, 2)
	if err != nil {
		t.Fatal(err)
	}
	if topic != "dev/txing/rig/v2/capability/command-result/unit-1/dev.txing.rig.BleConnectivity" {
		t.Fatalf("topic = %s", topic)
	}
	decoded, err := protocol.DecodeCapabilityCommandResult(payload)
	if err != nil {
		t.Fatal(err)
	}
	if decoded.AdapterID != AdapterID || decoded.Status != protocol.CommandSucceeded || decoded.Target.Redcon == nil || *decoded.Target.Redcon != 3 {
		t.Fatalf("decoded result = %#v", decoded)
	}
}

func TestStateTopicBuilderAllowsComponentAdapterID(t *testing.T) {
	topic, err := protocol.BuildCapabilityStateTopic("unit-1", AdapterID)
	if err != nil {
		t.Fatal(err)
	}
	if topic != "dev/txing/rig/v2/capability/state/unit-1/dev.txing.rig.BleConnectivity" {
		t.Fatalf("topic = %s", topic)
	}
}
