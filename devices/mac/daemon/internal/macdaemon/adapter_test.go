package macdaemon

import (
	"encoding/json"
	"strings"
	"testing"

	"github.com/mparkachov/txing/devices/mac/daemon/internal/rigadapter"
)

type publishedMessage struct {
	Topic    string
	Payload  []byte
	Retained bool
}

type fakePublisher struct {
	messages []publishedMessage
}

func (p *fakePublisher) Publish(topic string, payload []byte) error {
	p.messages = append(p.messages, publishedMessage{Topic: topic, Payload: payload})
	return nil
}

func (p *fakePublisher) PublishRetained(topic string, payload []byte) error {
	p.messages = append(p.messages, publishedMessage{Topic: topic, Payload: payload, Retained: true})
	return nil
}

func newTestAdapter(t *testing.T, initialRedcon uint8) (*Adapter, *fakePublisher) {
	t.Helper()
	machine, err := NewMachine(initialRedcon)
	if err != nil {
		t.Fatalf("NewMachine: %v", err)
	}
	publisher := &fakePublisher{}
	adapter := NewAdapter("mac-ab12cd", machine, publisher)
	adapter.NowMS = func() uint64 { return 1_776_000_000_000 }
	return adapter, publisher
}

func macInventory(devices ...rigadapter.InventoryDevice) rigadapter.Inventory {
	return rigadapter.Inventory{
		SchemaVersion: rigadapter.SchemaVersion,
		ManagerID:     "local-hz0ny3-sparkplug-manager",
		Devices:       devices,
		Seq:           1,
		IssuedAtMS:    1_776_000_000_000,
	}
}

func macDevice(thingName string) rigadapter.InventoryDevice {
	return rigadapter.InventoryDevice{
		ThingName:           thingName,
		ThingType:           "mac",
		Capabilities:        []string{"sparkplug", "power", "board", "mcp", "video"},
		RedconCommandLevels: []uint8{4, 3, 2, 1},
		RedconRules: map[uint8][]string{
			4: {"sparkplug"},
			3: {"sparkplug", "power"},
			2: {"sparkplug", "power", "board", "mcp"},
			1: {"sparkplug", "power", "board", "mcp", "video"},
		},
	}
}

func command(thingName string, target uint8) rigadapter.CapabilityCommand {
	return rigadapter.CapabilityCommand{
		SchemaVersion: rigadapter.SchemaVersion,
		CommandID:     "cmd-1",
		ThingName:     thingName,
		Target:        rigadapter.CapabilityCommandTarget{Redcon: target},
		Reason:        "test",
		IssuedAtMS:    1_775_999_999_000,
		Seq:           7,
	}
}

func decodeState(t *testing.T, payload []byte) rigadapter.CapabilityState {
	t.Helper()
	var state rigadapter.CapabilityState
	if err := json.Unmarshal(payload, &state); err != nil {
		t.Fatalf("decode state: %v", err)
	}
	return state
}

func decodeResult(t *testing.T, payload []byte) rigadapter.CapabilityCommandResult {
	t.Helper()
	var result rigadapter.CapabilityCommandResult
	if err := json.Unmarshal(payload, &result); err != nil {
		t.Fatalf("decode result: %v", err)
	}
	return result
}

func TestMachineAcceptsAllTargetsAndRejectsInvalid(t *testing.T) {
	machine, err := NewMachine(4)
	if err != nil {
		t.Fatalf("NewMachine: %v", err)
	}
	for _, target := range []uint8{3, 2, 1, 4, 1} {
		applied, err := machine.Apply(target)
		if err != nil {
			t.Fatalf("Apply(%d): %v", target, err)
		}
		if applied != target || machine.Redcon() != target {
			t.Fatalf("Apply(%d) got %d, machine %d", target, applied, machine.Redcon())
		}
	}
	for _, target := range []uint8{0, 5} {
		if _, err := machine.Apply(target); err == nil {
			t.Fatalf("Apply(%d) should fail", target)
		}
	}
	if _, err := NewMachine(0); err == nil {
		t.Fatal("NewMachine(0) should fail")
	}
}

func TestCapabilityStateForNeverDeclaresBoardOwnedCapabilities(t *testing.T) {
	for _, redcon := range []uint8{1, 2, 3, 4} {
		state := CapabilityStateFor("mac-ab12cd", redcon, 1, 2)
		if err := state.Validate(); err != nil {
			t.Fatalf("state invalid at redcon %d: %v", redcon, err)
		}
		for _, forbidden := range []string{"board", "mcp", "video", "ble", "thread"} {
			if _, ok := state.Capabilities[forbidden]; ok {
				t.Fatalf("state at redcon %d must not declare %s", redcon, forbidden)
			}
		}
		if !state.Capabilities[SparkplugCapability] {
			t.Fatalf("sparkplug must be true at redcon %d", redcon)
		}
		wantPower := redcon < 4
		if state.Capabilities[PowerCapability] != wantPower {
			t.Fatalf("power at redcon %d: got %v want %v", redcon, state.Capabilities[PowerCapability], wantPower)
		}
		metric := state.Metrics[rigadapter.TransportRedconMetric]
		if metric.Datatype != "Int32" || metric.Value != int32(redcon) {
			t.Fatalf("transportRedcon at redcon %d: %#v", redcon, metric)
		}
	}
}

func TestReconcileInventoryGatesPublishing(t *testing.T) {
	adapter, publisher := newTestAdapter(t, 4)

	if err := adapter.PublishState(); err != nil {
		t.Fatalf("PublishState: %v", err)
	}
	if len(publisher.messages) != 0 {
		t.Fatalf("state published before inventory presence: %v", publisher.messages)
	}
	if err := adapter.HandleCommand(command("mac-ab12cd", 3)); err != nil {
		t.Fatalf("HandleCommand: %v", err)
	}
	if len(publisher.messages) != 0 {
		t.Fatalf("command handled before inventory presence: %v", publisher.messages)
	}

	present, changed, err := adapter.ReconcileInventory(macInventory(macDevice("mac-ab12cd")))
	if err != nil || !present || !changed {
		t.Fatalf("ReconcileInventory: present=%v changed=%v err=%v", present, changed, err)
	}
	if len(publisher.messages) != 1 || !publisher.messages[0].Retained {
		t.Fatalf("becoming present must publish one retained state, got %v", publisher.messages)
	}
	state := decodeState(t, publisher.messages[0].Payload)
	if state.AdapterID != AdapterID || state.ThingName != "mac-ab12cd" {
		t.Fatalf("unexpected state identity: %+v", state)
	}
	if state.Capabilities[PowerCapability] {
		t.Fatalf("power must be false at initial redcon 4")
	}

	present, changed, err = adapter.ReconcileInventory(macInventory())
	if err != nil || present || !changed {
		t.Fatalf("ReconcileInventory removal: present=%v changed=%v err=%v", present, changed, err)
	}

	otherType := macDevice("mac-ab12cd")
	otherType.ThingType = "unit"
	otherType.Capabilities = []string{"sparkplug", "ble"}
	present, _, err = adapter.ReconcileInventory(macInventory(otherType))
	if err != nil || present {
		t.Fatalf("thing with wrong type must not count as present: present=%v err=%v", present, err)
	}
}

func TestHandleCommandPublishesAcceptedStateSucceeded(t *testing.T) {
	adapter, publisher := newTestAdapter(t, 4)
	if _, _, err := adapter.ReconcileInventory(macInventory(macDevice("mac-ab12cd"))); err != nil {
		t.Fatalf("ReconcileInventory: %v", err)
	}
	publisher.messages = nil

	if err := adapter.HandleCommand(command("mac-ab12cd", 1)); err != nil {
		t.Fatalf("HandleCommand: %v", err)
	}
	if len(publisher.messages) != 3 {
		t.Fatalf("want accepted, state, succeeded; got %d messages", len(publisher.messages))
	}

	accepted := decodeResult(t, publisher.messages[0].Payload)
	if accepted.Status != rigadapter.CommandAccepted || accepted.Target.Redcon == nil || *accepted.Target.Redcon != 1 {
		t.Fatalf("first message must be accepted with target echo: %+v", accepted)
	}
	if publisher.messages[0].Retained {
		t.Fatal("command results must not be retained")
	}
	if !strings.HasPrefix(publisher.messages[0].Topic, rigadapter.CapabilityCommandResultTopicPrefix+"/mac-ab12cd/") {
		t.Fatalf("unexpected result topic %s", publisher.messages[0].Topic)
	}

	state := decodeState(t, publisher.messages[1].Payload)
	if !publisher.messages[1].Retained {
		t.Fatal("state must be retained")
	}
	if !state.Capabilities[PowerCapability] {
		t.Fatal("power must be true after target 1")
	}
	if state.Metrics[rigadapter.TransportRedconMetric].Value != float64(1) && state.Metrics[rigadapter.TransportRedconMetric].Value != int32(1) {
		// json decoding yields float64
		t.Fatalf("transportRedcon must be 1, got %#v", state.Metrics[rigadapter.TransportRedconMetric].Value)
	}

	succeeded := decodeResult(t, publisher.messages[2].Payload)
	if succeeded.Status != rigadapter.CommandSucceeded {
		t.Fatalf("last message must be succeeded: %+v", succeeded)
	}
	if adapter.Machine.Redcon() != 1 {
		t.Fatalf("machine redcon must be 1, got %d", adapter.Machine.Redcon())
	}
}

func TestHandleCommandDeadlineExpired(t *testing.T) {
	adapter, publisher := newTestAdapter(t, 4)
	if _, _, err := adapter.ReconcileInventory(macInventory(macDevice("mac-ab12cd"))); err != nil {
		t.Fatalf("ReconcileInventory: %v", err)
	}
	publisher.messages = nil

	expired := command("mac-ab12cd", 3)
	deadline := uint64(1_775_999_999_500)
	expired.DeadlineMS = &deadline
	if err := adapter.HandleCommand(expired); err != nil {
		t.Fatalf("HandleCommand: %v", err)
	}
	if len(publisher.messages) != 1 {
		t.Fatalf("want one failed result, got %d", len(publisher.messages))
	}
	result := decodeResult(t, publisher.messages[0].Payload)
	if result.Status != rigadapter.CommandFailed || result.Message == nil || *result.Message != "command deadline expired" {
		t.Fatalf("unexpected result: %+v", result)
	}
	if adapter.Machine.Redcon() != 4 {
		t.Fatalf("machine must stay at 4 after expired command, got %d", adapter.Machine.Redcon())
	}
}

func TestHandleCommandIgnoresOtherThings(t *testing.T) {
	adapter, publisher := newTestAdapter(t, 4)
	if _, _, err := adapter.ReconcileInventory(macInventory(macDevice("mac-ab12cd"))); err != nil {
		t.Fatalf("ReconcileInventory: %v", err)
	}
	publisher.messages = nil

	if err := adapter.HandleCommand(command("mac-other", 3)); err != nil {
		t.Fatalf("HandleCommand: %v", err)
	}
	if len(publisher.messages) != 0 {
		t.Fatalf("command for another thing must be ignored, got %v", publisher.messages)
	}
}

type orderRecorder struct {
	events []string
}

type orderedPublisher struct {
	recorder *orderRecorder
}

func (p *orderedPublisher) Publish(topic string, _ []byte) error {
	p.recorder.events = append(p.recorder.events, "publish:"+topic)
	return nil
}

func (p *orderedPublisher) PublishRetained(topic string, _ []byte) error {
	p.recorder.events = append(p.recorder.events, "retained:"+topic)
	return nil
}

type orderedController struct {
	recorder *orderRecorder
}

func (c *orderedController) SetTarget(redcon uint8) {
	c.recorder.events = append(c.recorder.events, "action:"+string('0'+rune(redcon)))
}

func TestHandleCommandDrivesActionLayerBeforeIPCState(t *testing.T) {
	recorder := &orderRecorder{}
	machine, err := NewMachine(2)
	if err != nil {
		t.Fatalf("NewMachine: %v", err)
	}
	adapter := NewAdapter("mac-ab12cd", machine, &orderedPublisher{recorder: recorder})
	adapter.Action = &orderedController{recorder: recorder}
	adapter.NowMS = func() uint64 { return 1_776_000_000_000 }
	if _, _, err := adapter.ReconcileInventory(macInventory(macDevice("mac-ab12cd"))); err != nil {
		t.Fatalf("ReconcileInventory: %v", err)
	}
	recorder.events = nil

	if err := adapter.HandleCommand(command("mac-ab12cd", 4)); err != nil {
		t.Fatalf("HandleCommand: %v", err)
	}
	stateTopic := "retained:" + rigadapter.CapabilityStateTopicPrefix + "/mac-ab12cd/" + AdapterID
	actionIndex, stateIndex := -1, -1
	for index, event := range recorder.events {
		if event == "action:4" && actionIndex == -1 {
			actionIndex = index
		}
		if event == stateTopic && stateIndex == -1 {
			stateIndex = index
		}
	}
	if actionIndex == -1 || stateIndex == -1 || actionIndex > stateIndex {
		t.Fatalf("action stop must run before the IPC sleep state is published: %v", recorder.events)
	}
}

func TestHeartbeatCarriesPresence(t *testing.T) {
	adapter, publisher := newTestAdapter(t, 4)
	if err := adapter.PublishHeartbeat(); err != nil {
		t.Fatalf("PublishHeartbeat: %v", err)
	}
	var absent rigadapter.CapabilityHeartbeat
	if err := json.Unmarshal(publisher.messages[0].Payload, &absent); err != nil {
		t.Fatalf("decode heartbeat: %v", err)
	}
	if absent.ActiveThingName != nil {
		t.Fatalf("heartbeat before presence must carry no active thing: %+v", absent)
	}
	if !publisher.messages[0].Retained {
		t.Fatal("heartbeat must be retained")
	}

	if _, _, err := adapter.ReconcileInventory(macInventory(macDevice("mac-ab12cd"))); err != nil {
		t.Fatalf("ReconcileInventory: %v", err)
	}
	publisher.messages = nil
	if err := adapter.PublishHeartbeat(); err != nil {
		t.Fatalf("PublishHeartbeat: %v", err)
	}
	var presentHeartbeat rigadapter.CapabilityHeartbeat
	if err := json.Unmarshal(publisher.messages[0].Payload, &presentHeartbeat); err != nil {
		t.Fatalf("decode heartbeat: %v", err)
	}
	if presentHeartbeat.ActiveThingName == nil || *presentHeartbeat.ActiveThingName != "mac-ab12cd" {
		t.Fatalf("heartbeat after presence must carry the thing name: %+v", presentHeartbeat)
	}
}
