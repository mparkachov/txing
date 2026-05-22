package protocol

import (
	"encoding/json"
	"testing"
)

func TestCommandRequiresRedconTarget(t *testing.T) {
	if _, err := NewCapabilityCommand("cmd-1", "weather-1", 0, "test", 1000, 1, nil); err == nil {
		t.Fatal("expected invalid redcon to fail")
	}

	deadline := uint64(2000)
	command, err := NewCapabilityCommand("cmd-1", "weather-1", 4, "test", 1000, 1, &deadline)
	if err != nil {
		t.Fatal(err)
	}
	payload, err := command.Marshal()
	if err != nil {
		t.Fatal(err)
	}
	decoded, err := DecodeCapabilityCommand(payload)
	if err != nil {
		t.Fatal(err)
	}
	if decoded.Target.Redcon != 4 || decoded.DeadlineMS == nil || *decoded.DeadlineMS != 2000 {
		t.Fatalf("decoded command = %#v", decoded)
	}
}

func TestTopicParsingUsesV2Root(t *testing.T) {
	stateTopic, err := BuildCapabilityStateTopic("weather-1", "dev.txing.rig.BleConnectivity")
	if err != nil {
		t.Fatal(err)
	}
	if stateTopic != "dev/txing/rig/v2/capability/state/weather-1/dev.txing.rig.BleConnectivity" {
		t.Fatalf("state topic = %s", stateTopic)
	}
	thingName, ok := ParseCapabilityCommandTopic("dev/txing/rig/v2/capability/command/weather-1")
	if !ok || thingName != "weather-1" {
		t.Fatalf("command topic parse = %q %v", thingName, ok)
	}
	parsedThing, parsedAdapter, ok := ParseCapabilityStateTopic(stateTopic)
	if !ok || parsedThing != "weather-1" || parsedAdapter != "dev.txing.rig.BleConnectivity" {
		t.Fatalf("state topic parse = %q %q %v", parsedThing, parsedAdapter, ok)
	}
	heartbeat, ok := ParseCapabilityHeartbeatTopic("dev/txing/rig/v2/capability/heartbeat/dev.txing.rig.BleConnectivity")
	if !ok || heartbeat != "dev.txing.rig.BleConnectivity" {
		t.Fatalf("heartbeat topic parse = %q %v", heartbeat, ok)
	}
}

func TestHeartbeatRoundTrips(t *testing.T) {
	active := "unit-1"
	heartbeat := NewCapabilityHeartbeat("dev.txing.rig.BleConnectivity", HeartbeatRunning, &active, 1000, 5)
	payload, err := heartbeat.Marshal()
	if err != nil {
		t.Fatal(err)
	}
	decoded, err := DecodeCapabilityHeartbeat(payload)
	if err != nil {
		t.Fatal(err)
	}
	if decoded.ActiveThingName == nil || *decoded.ActiveThingName != "unit-1" {
		t.Fatalf("decoded heartbeat = %#v", decoded)
	}
}

func TestInventoryDeviceCapabilityLookupUsesCapabilityList(t *testing.T) {
	device := InventoryDevice{
		ThingName:           "unit-1",
		ThingType:           "unit",
		Capabilities:        []string{"sparkplug", "ble", "power"},
		RedconCommandLevels: []uint8{4, 3},
		RedconRules: map[uint8][]string{
			4: []string{"sparkplug", "ble"},
			3: []string{"sparkplug", "ble", "power"},
		},
	}
	if !device.HasCapability("power") {
		t.Fatal("expected power capability")
	}
	if device.HasCapability("weather") {
		t.Fatal("did not expect weather capability")
	}

	payload, err := json.Marshal(device)
	if err != nil {
		t.Fatal(err)
	}
	var raw map[string]any
	if err := json.Unmarshal(payload, &raw); err != nil {
		t.Fatal(err)
	}
	if _, ok := raw["redconRules"].(map[string]any)["4"]; !ok {
		t.Fatalf("redconRules not serialized with string key 4: %s", string(payload))
	}
	var decoded InventoryDevice
	if err := json.Unmarshal(payload, &decoded); err != nil {
		t.Fatal(err)
	}
	if got := decoded.RedconRules[3][2]; got != "power" {
		t.Fatalf("decoded redcon rule = %q", got)
	}
}
