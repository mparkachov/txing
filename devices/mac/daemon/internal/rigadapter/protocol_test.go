package rigadapter

import (
	"encoding/json"
	"reflect"
	"testing"
)

// Golden wire-format tests. The JSON below is the rig schema-2.0
// contract as produced/consumed by rig/internal/protocol; if these
// fail after a protocol change, re-sync protocol.go with the rig
// source rather than adjusting the goldens to the local behavior.

func TestCapabilityStateGoldenWireFormat(t *testing.T) {
	state := CapabilityState{
		SchemaVersion: SchemaVersion,
		AdapterID:     "dev.txing.mac.Daemon",
		ThingName:     "mac-ab12cd",
		Capabilities:  map[string]bool{"sparkplug": true, "power": false},
		Metrics: map[string]MetricValue{
			"transportRedcon": MetricInt32(4),
		},
		ObservedAtMS: 1776000000000,
		Seq:          3,
	}
	payload, err := state.Marshal()
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	golden := `{"schemaVersion":"2.0","adapterId":"dev.txing.mac.Daemon","thingName":"mac-ab12cd","capabilities":{"power":false,"sparkplug":true},"metrics":{"transportRedcon":{"datatype":"Int32","value":4}},"observedAtMs":1776000000000,"seq":3}`
	assertJSONEqual(t, payload, golden)
}

func TestCapabilityCommandGoldenDecode(t *testing.T) {
	golden := `{"schemaVersion":"2.0","commandId":"dcmd-12","thingName":"mac-ab12cd","target":{"redcon":1},"reason":"sparkplug DCMD redcon","issuedAtMs":1776000000000,"deadlineMs":1776000060000,"seq":12}`
	command, err := DecodeCapabilityCommand([]byte(golden))
	if err != nil {
		t.Fatalf("decode: %v", err)
	}
	if command.CommandID != "dcmd-12" || command.ThingName != "mac-ab12cd" || command.Target.Redcon != 1 {
		t.Fatalf("unexpected command: %+v", command)
	}
	if command.DeadlineMS == nil || *command.DeadlineMS != 1776000060000 {
		t.Fatalf("unexpected deadline: %+v", command.DeadlineMS)
	}
	if CommandDeadlineExpired(command, 1776000060000) {
		t.Fatal("deadline at boundary must not be expired")
	}
	if !CommandDeadlineExpired(command, 1776000060001) {
		t.Fatal("deadline past boundary must be expired")
	}
}

func TestCapabilityCommandResultGoldenWireFormat(t *testing.T) {
	result := NewCapabilityCommandResult("dev.txing.mac.Daemon", "dcmd-12", "mac-ab12cd", CommandSucceeded, 1776000000500, 4)
	redcon := uint8(1)
	result.Target.Redcon = &redcon
	payload, err := result.Marshal()
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	golden := `{"schemaVersion":"2.0","adapterId":"dev.txing.mac.Daemon","commandId":"dcmd-12","thingName":"mac-ab12cd","status":"succeeded","target":{"redcon":1},"message":null,"observedAtMs":1776000000500,"seq":4}`
	assertJSONEqual(t, payload, golden)
}

func TestCapabilityHeartbeatGoldenWireFormat(t *testing.T) {
	thing := "mac-ab12cd"
	heartbeat := NewCapabilityHeartbeat("dev.txing.mac.Daemon", HeartbeatRunning, &thing, 1776000000000, 9)
	payload, err := heartbeat.Marshal()
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	golden := `{"schemaVersion":"2.0","adapterId":"dev.txing.mac.Daemon","status":"running","activeThingName":"mac-ab12cd","observedAtMs":1776000000000,"seq":9}`
	assertJSONEqual(t, payload, golden)
}

func TestInventoryGoldenDecode(t *testing.T) {
	// Shape as broadcast retained by txing-sparkplug-manager on
	// dev/txing/rig/v2/inventory: redconRules keys are strings.
	golden := `{
	  "schemaVersion": "2.0",
	  "managerId": "local-hz0ny3-sparkplug-manager",
	  "devices": [
	    {
	      "thingName": "mac-ab12cd",
	      "thingType": "mac",
	      "capabilities": ["sparkplug", "power", "board", "mcp", "video"],
	      "redconCommandLevels": [4, 3, 2, 1],
	      "redconRules": {
	        "1": ["sparkplug", "power", "board", "mcp", "video"],
	        "2": ["sparkplug", "power", "board", "mcp"],
	        "3": ["sparkplug", "power"],
	        "4": ["sparkplug"]
	      }
	    }
	  ],
	  "seq": 42,
	  "issuedAtMs": 1776000000000
	}`
	inventory, err := DecodeInventory([]byte(golden))
	if err != nil {
		t.Fatalf("decode: %v", err)
	}
	if len(inventory.Devices) != 1 {
		t.Fatalf("want one device, got %d", len(inventory.Devices))
	}
	device := inventory.Devices[0]
	if device.ThingName != "mac-ab12cd" || device.ThingType != "mac" {
		t.Fatalf("unexpected device: %+v", device)
	}
	if !device.HasCapability("video") || device.HasCapability("ble") {
		t.Fatalf("unexpected capabilities: %v", device.Capabilities)
	}
	if !reflect.DeepEqual(device.RedconRules[3], []string{"sparkplug", "power"}) {
		t.Fatalf("unexpected rules: %v", device.RedconRules)
	}

	// Round-trip through the copied marshaller keeps the wire shape.
	encoded, err := json.Marshal(device)
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	var again InventoryDevice
	if err := json.Unmarshal(encoded, &again); err != nil {
		t.Fatalf("unmarshal round trip: %v", err)
	}
	if !reflect.DeepEqual(device, again) {
		t.Fatalf("round trip mismatch:\n%+v\n%+v", device, again)
	}
}

func TestTopicBuildersAndParser(t *testing.T) {
	stateTopic, err := BuildCapabilityStateTopic("mac-ab12cd", "dev.txing.mac.Daemon")
	if err != nil || stateTopic != "dev/txing/rig/v2/capability/state/mac-ab12cd/dev.txing.mac.Daemon" {
		t.Fatalf("state topic: %q err=%v", stateTopic, err)
	}
	commandTopic, err := BuildCapabilityCommandTopic("mac-ab12cd")
	if err != nil || commandTopic != "dev/txing/rig/v2/capability/command/mac-ab12cd" {
		t.Fatalf("command topic: %q err=%v", commandTopic, err)
	}
	thing, ok := ParseCapabilityCommandTopic(commandTopic)
	if !ok || thing != "mac-ab12cd" {
		t.Fatalf("parse command topic: %q ok=%v", thing, ok)
	}
	if _, ok := ParseCapabilityCommandTopic("dev/txing/rig/v2/capability/command/a/b"); ok {
		t.Fatal("nested suffix must not parse")
	}
	resultTopic, err := BuildCapabilityCommandResultTopic("mac-ab12cd", "dev.txing.mac.Daemon")
	if err != nil || resultTopic != "dev/txing/rig/v2/capability/command-result/mac-ab12cd/dev.txing.mac.Daemon" {
		t.Fatalf("result topic: %q err=%v", resultTopic, err)
	}
	heartbeatTopic, err := BuildCapabilityHeartbeatTopic("dev.txing.mac.Daemon")
	if err != nil || heartbeatTopic != "dev/txing/rig/v2/capability/heartbeat/dev.txing.mac.Daemon" {
		t.Fatalf("heartbeat topic: %q err=%v", heartbeatTopic, err)
	}
	if _, err := BuildCapabilityStateTopic("bad/thing", "adapter"); err == nil {
		t.Fatal("topic separators in thing name must be rejected")
	}
}

func assertJSONEqual(t *testing.T, got []byte, want string) {
	t.Helper()
	var gotValue, wantValue any
	if err := json.Unmarshal(got, &gotValue); err != nil {
		t.Fatalf("got is not JSON: %v\n%s", err, got)
	}
	if err := json.Unmarshal([]byte(want), &wantValue); err != nil {
		t.Fatalf("want is not JSON: %v", err)
	}
	if !reflect.DeepEqual(gotValue, wantValue) {
		t.Fatalf("wire mismatch:\ngot:  %s\nwant: %s", got, want)
	}
}
