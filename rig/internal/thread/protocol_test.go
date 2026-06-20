package thread

import (
	"context"
	"encoding/json"
	"net"
	"strings"
	"testing"

	"github.com/mparkachov/txing/rig/internal/protocol"
)

func TestDiscovererFiltersPowerSIEndpoints(t *testing.T) {
	resolver := &fakeResolver{
		ptr: map[string][]string{
			BuildServiceFQDN(DefaultDomain): {
				"power-si-001._txing-coap._udp.default.service.arpa.",
				"unit-001._txing-coap._udp.default.service.arpa.",
			},
		},
		txt: map[string][]string{
			"power-si-001._txing-coap._udp.default.service.arpa.": {"type=power-si", "pv=1"},
			"unit-001._txing-coap._udp.default.service.arpa.":     {"type=unit", "pv=1"},
		},
		srv: map[string][]SRVRecord{
			"power-si-001._txing-coap._udp.default.service.arpa.": {
				{Target: "power-si-001.default.service.arpa.", Port: 5683},
			},
			"unit-001._txing-coap._udp.default.service.arpa.": {
				{Target: "unit-001.default.service.arpa.", Port: 5683},
			},
		},
		aaaa: map[string][]net.IP{
			"power-si-001.default.service.arpa.": {net.ParseIP("fdde:ad00:beef::1")},
			"unit-001.default.service.arpa.":     {net.ParseIP("fdde:ad00:beef::2")},
		},
	}
	discoverer := Discoverer{
		Resolver: resolver,
		Domain:   DefaultDomain,
		NowMS:    func() uint64 { return 1000 },
		NextSeq:  func() uint64 { return 7 },
	}

	endpoints, err := discoverer.Discover(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if len(endpoints) != 1 {
		t.Fatalf("endpoints = %#v, want one power-si endpoint", endpoints)
	}
	endpoint := endpoints[0]
	if endpoint.ThingName != "power-si-001" {
		t.Fatalf("thingName = %s", endpoint.ThingName)
	}
	if endpoint.Port != 5683 || endpoint.TXT["type"] != "power-si" {
		t.Fatalf("endpoint = %#v", endpoint)
	}
}

func TestRuntimePublishesStateAndShadows(t *testing.T) {
	publisher := &recordingPublisher{}
	runtime := NewRuntime(
		&fakeDiscoverer{endpoints: []Endpoint{testEndpoint("power-si-001")}},
		&fakeDeviceClient{state: DeviceState{ThingName: "power-si-001", ProtocolVersion: "1", Redcon: 3, BatteryMV: intPtr(3011)}},
		publisher,
	)
	runtime.NowMS = func() uint64 { return 2000 }
	runtime.ReconcileInventory(testInventory())

	if err := runtime.DiscoverAndPoll(context.Background()); err != nil {
		t.Fatal(err)
	}

	stateTopic, err := protocol.BuildCapabilityStateTopic("power-si-001", AdapterID)
	if err != nil {
		t.Fatal(err)
	}
	capabilityPayload := publisher.retained[stateTopic]
	if len(capabilityPayload) == 0 {
		t.Fatalf("missing retained capability state on %s", stateTopic)
	}
	state, err := protocol.DecodeCapabilityState(capabilityPayload)
	if err != nil {
		t.Fatal(err)
	}
	if !state.Capabilities["sparkplug"] || !state.Capabilities["thread"] || !state.Capabilities["power"] {
		t.Fatalf("capabilities = %#v", state.Capabilities)
	}
	if value, ok := protocol.IntMetricValue(state.Metrics[protocol.TransportRedconMetric].Value); !ok || value != 3 {
		t.Fatalf("transport redcon metric = %#v", state.Metrics)
	}
	assertPublishedTopic(t, publisher, "$aws/things/power-si-001/shadow/name/thread/update")
	assertPublishedTopic(t, publisher, "$aws/things/power-si-001/shadow/name/power/update")
}

func TestRuntimeUnavailableDevicePublishesOffline(t *testing.T) {
	publisher := &recordingPublisher{}
	runtime := NewRuntime(
		&fakeDiscoverer{},
		&fakeDeviceClient{},
		publisher,
	)
	runtime.NowMS = func() uint64 { return 3000 }
	runtime.ReconcileInventory(testInventory())

	if err := runtime.DiscoverAndPoll(context.Background()); err != nil {
		t.Fatal(err)
	}

	stateTopic, _ := protocol.BuildCapabilityStateTopic("power-si-001", AdapterID)
	state, err := protocol.DecodeCapabilityState(publisher.retained[stateTopic])
	if err != nil {
		t.Fatal(err)
	}
	if state.Capabilities["sparkplug"] || state.Capabilities["thread"] || state.Capabilities["power"] {
		t.Fatalf("offline capabilities = %#v", state.Capabilities)
	}
	assertPublishedTopic(t, publisher, "$aws/things/power-si-001/shadow/name/thread/update")
}

func TestRuntimeCommandReportsSuccessAfterConfirmedState(t *testing.T) {
	publisher := &recordingPublisher{}
	client := &fakeDeviceClient{state: DeviceState{ThingName: "power-si-001", ProtocolVersion: "1", Redcon: 3}}
	runtime := NewRuntime(
		&fakeDiscoverer{endpoints: []Endpoint{testEndpoint("power-si-001")}},
		client,
		publisher,
	)
	runtime.NowMS = func() uint64 { return 4000 }
	runtime.ReconcileInventory(testInventory())
	if err := runtime.DiscoverAndPoll(context.Background()); err != nil {
		t.Fatal(err)
	}
	command, err := protocol.NewCapabilityCommand("cmd-1", "power-si-001", 4, "test", 4000, 77, nil)
	if err != nil {
		t.Fatal(err)
	}
	client.putState = DeviceState{ThingName: "power-si-001", ProtocolVersion: "1", Redcon: 4}

	if err := runtime.HandleCommand(context.Background(), command); err != nil {
		t.Fatal(err)
	}
	if client.putTarget != 4 {
		t.Fatalf("put target = %d, want 4", client.putTarget)
	}
	results := publisher.commandResults(t)
	if len(results) < 2 {
		t.Fatalf("command results = %#v", results)
	}
	if results[len(results)-2].Status != protocol.CommandAccepted {
		t.Fatalf("second last status = %s, want accepted", results[len(results)-2].Status)
	}
	if results[len(results)-1].Status != protocol.CommandSucceeded {
		t.Fatalf("last status = %s, want succeeded", results[len(results)-1].Status)
	}
}

func TestRuntimeCommandFailsWhenConfirmedStateDiffers(t *testing.T) {
	publisher := &recordingPublisher{}
	client := &fakeDeviceClient{putState: DeviceState{ThingName: "power-si-001", ProtocolVersion: "1", Redcon: 3}}
	runtime := NewRuntime(
		&fakeDiscoverer{endpoints: []Endpoint{testEndpoint("power-si-001")}},
		client,
		publisher,
	)
	runtime.NowMS = func() uint64 { return 5000 }
	runtime.ReconcileInventory(testInventory())
	runtime.recordEndpoints([]Endpoint{testEndpoint("power-si-001")})
	command, err := protocol.NewCapabilityCommand("cmd-2", "power-si-001", 4, "test", 5000, 78, nil)
	if err != nil {
		t.Fatal(err)
	}

	if err := runtime.HandleCommand(context.Background(), command); err != nil {
		t.Fatal(err)
	}
	results := publisher.commandResults(t)
	if results[len(results)-1].Status != protocol.CommandFailed {
		t.Fatalf("last status = %s, want failed", results[len(results)-1].Status)
	}
	if results[len(results)-1].Message == nil || !strings.Contains(*results[len(results)-1].Message, "confirmed Thread state REDCON") {
		t.Fatalf("failure message = %#v", results[len(results)-1].Message)
	}
}

func TestRuntimeRejectsUnsupportedThreadCommand(t *testing.T) {
	publisher := &recordingPublisher{}
	runtime := NewRuntime(&fakeDiscoverer{}, &fakeDeviceClient{}, publisher)
	runtime.NowMS = func() uint64 { return 6000 }
	runtime.ReconcileInventory(testInventory())
	command, err := protocol.NewCapabilityCommand("cmd-3", "power-si-001", 2, "test", 6000, 79, nil)
	if err != nil {
		t.Fatal(err)
	}

	if err := runtime.HandleCommand(context.Background(), command); err != nil {
		t.Fatal(err)
	}
	results := publisher.commandResults(t)
	if results[len(results)-1].Status != protocol.CommandRejected {
		t.Fatalf("last status = %s, want rejected", results[len(results)-1].Status)
	}
}

func TestRuntimeIgnoresCommandForNonThreadInventoryTarget(t *testing.T) {
	publisher := &recordingPublisher{}
	runtime := NewRuntime(&fakeDiscoverer{}, &fakeDeviceClient{}, publisher)
	runtime.NowMS = func() uint64 { return 7000 }
	runtime.ReconcileInventory(testInventory())
	command, err := protocol.NewCapabilityCommand("cmd-4", "power-ble-001", 3, "test", 7000, 80, nil)
	if err != nil {
		t.Fatal(err)
	}

	if err := runtime.HandleCommand(context.Background(), command); err != nil {
		t.Fatal(err)
	}
	if results := publisher.commandResults(t); len(results) != 0 {
		t.Fatalf("unexpected command results for non-Thread target: %#v", results)
	}
}

func testInventory() protocol.Inventory {
	return protocol.NewInventory("manager", []protocol.InventoryDevice{{
		ThingName:           "power-si-001",
		ThingType:           DeviceType,
		Capabilities:        []string{"sparkplug", "thread", "power"},
		RedconCommandLevels: []uint8{4, 3},
		RedconRules: map[uint8][]string{
			4: {"sparkplug", "thread"},
			3: {"sparkplug", "thread", "power"},
		},
	}}, 1, 1000)
}

func testEndpoint(thingName string) Endpoint {
	return Endpoint{
		ThingName:       thingName,
		ServiceInstance: thingName + "._txing-coap._udp.default.service.arpa",
		ServiceName:     ServiceName,
		Host:            thingName + ".default.service.arpa",
		Address:         net.ParseIP("fdde:ad00:beef::1"),
		Port:            5683,
		TXT:             map[string]string{"type": "power-si", "pv": "1"},
	}
}

type fakeResolver struct {
	ptr  map[string][]string
	txt  map[string][]string
	srv  map[string][]SRVRecord
	aaaa map[string][]net.IP
}

func (f *fakeResolver) LookupPTR(_ context.Context, name string) ([]string, error) {
	return f.ptr[name], nil
}

func (f *fakeResolver) LookupSRV(_ context.Context, name string) ([]SRVRecord, error) {
	return f.srv[name], nil
}

func (f *fakeResolver) LookupTXT(_ context.Context, name string) ([]string, error) {
	return f.txt[name], nil
}

func (f *fakeResolver) LookupAAAA(_ context.Context, name string) ([]net.IP, error) {
	return f.aaaa[name], nil
}

type fakeDiscoverer struct {
	endpoints []Endpoint
	err       error
}

func (f *fakeDiscoverer) Discover(_ context.Context) ([]Endpoint, error) {
	return f.endpoints, f.err
}

type fakeDeviceClient struct {
	state     DeviceState
	err       error
	putState  DeviceState
	putErr    error
	putTarget uint8
}

func (f *fakeDeviceClient) GetState(context.Context, Endpoint) (DeviceState, error) {
	return f.state, f.err
}

func (f *fakeDeviceClient) PutRedcon(_ context.Context, _ Endpoint, target uint8) (DeviceState, error) {
	f.putTarget = target
	if f.putState.ThingName == "" {
		f.putState = f.state
		f.putState.Redcon = target
	}
	return f.putState, f.putErr
}

type recordingPublisher struct {
	published []publishedMessage
	retained  map[string][]byte
}

type publishedMessage struct {
	topic   string
	payload []byte
}

func (p *recordingPublisher) Publish(topic string, payload []byte) error {
	p.published = append(p.published, publishedMessage{topic: topic, payload: append([]byte(nil), payload...)})
	return nil
}

func (p *recordingPublisher) PublishRetained(topic string, payload []byte) error {
	if p.retained == nil {
		p.retained = map[string][]byte{}
	}
	p.retained[topic] = append([]byte(nil), payload...)
	p.published = append(p.published, publishedMessage{topic: topic, payload: append([]byte(nil), payload...)})
	return nil
}

func (p *recordingPublisher) commandResults(t *testing.T) []protocol.CapabilityCommandResult {
	t.Helper()
	results := []protocol.CapabilityCommandResult{}
	for _, message := range p.published {
		if !strings.Contains(message.topic, protocol.CapabilityCommandResultTopicPrefix) {
			continue
		}
		var result protocol.CapabilityCommandResult
		if err := json.Unmarshal(message.payload, &result); err != nil {
			t.Fatal(err)
		}
		results = append(results, result)
	}
	return results
}

func assertPublishedTopic(t *testing.T, publisher *recordingPublisher, topic string) {
	t.Helper()
	for _, message := range publisher.published {
		if message.topic == topic {
			return
		}
	}
	t.Fatalf("topic %s was not published; got %#v", topic, publisher.published)
}

func intPtr(value int) *int {
	return &value
}
