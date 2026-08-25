package thread

import (
	"context"
	"encoding/json"
	"net"
	"strings"
	"sync"
	"testing"

	"github.com/mparkachov/txing/rig/internal/protocol"
)

func TestDiscovererAcceptsSupportedThreadDeviceEndpoints(t *testing.T) {
	resolver := &fakeResolver{
		ptr: map[string][]string{
			BuildServiceFQDN(DefaultDomain): {
				"power-si-001._txing-coap._udp.default.service.arpa.",
				"power-nrf-001._txing-coap._udp.default.service.arpa.",
				"tbot-001._txing-coap._udp.default.service.arpa.",
				"unit-001._txing-coap._udp.default.service.arpa.",
			},
		},
		txt: map[string][]string{
			"power-si-001._txing-coap._udp.default.service.arpa.":  {"type=power-si", "pv=1"},
			"power-nrf-001._txing-coap._udp.default.service.arpa.": {"type=power-nrf", "pv=1"},
			"tbot-001._txing-coap._udp.default.service.arpa.":      {"type=tbot", "pv=1"},
			"unit-001._txing-coap._udp.default.service.arpa.":      {"type=unit", "pv=1"},
		},
		srv: map[string][]SRVRecord{
			"power-si-001._txing-coap._udp.default.service.arpa.": {
				{Target: "power-si-001.default.service.arpa.", Port: 5683},
			},
			"power-nrf-001._txing-coap._udp.default.service.arpa.": {
				{Target: "power-nrf-001.default.service.arpa.", Port: 5683},
			},
			"tbot-001._txing-coap._udp.default.service.arpa.": {
				{Target: "tbot-001.default.service.arpa.", Port: 5683},
			},
			"unit-001._txing-coap._udp.default.service.arpa.": {
				{Target: "unit-001.default.service.arpa.", Port: 5683},
			},
		},
		aaaa: map[string][]net.IP{
			"power-si-001.default.service.arpa.":  {net.ParseIP("fdde:ad00:beef::1")},
			"power-nrf-001.default.service.arpa.": {net.ParseIP("fdde:ad00:beef::2")},
			"tbot-001.default.service.arpa.":      {net.ParseIP("fdde:ad00:beef::3")},
			"unit-001.default.service.arpa.":      {net.ParseIP("fdde:ad00:beef::3")},
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
	if len(endpoints) != 3 {
		t.Fatalf("endpoints = %#v, want supported Thread endpoints", endpoints)
	}
	if endpoints[0].ThingName != "power-nrf-001" || endpoints[0].TXT["type"] != DeviceTypePowerNRF ||
		endpoints[1].ThingName != "power-si-001" || endpoints[1].TXT["type"] != DeviceTypePowerSI ||
		endpoints[2].ThingName != "tbot-001" || endpoints[2].TXT["type"] != DeviceTypeTBot {
		t.Fatalf("endpoints = %#v", endpoints)
	}
}

func TestParseOTCTLSRPServicesFiltersActiveSupportedThreadDevices(t *testing.T) {
	output := `power-si-001._txing-coap._udp.default.service.arpa.
    deleted: false
    port: 5683
    TXT: [type=706f7765722d7369, pv=31, profile=7365642d6465627567]
    host: power-si-001.default.service.arpa.
    addresses: [fdde:ad00:beef::1]
power-nrf-001._txing-coap._udp.default.service.arpa.
    deleted: false
    port: 5683
    TXT: [type=706f7765722d6e7266, pv=31]
    host: power-nrf-001.default.service.arpa.
    addresses: [fdde:ad00:beef::2]
tbot-001._txing-coap._udp.default.service.arpa.
    deleted: false
    port: 5683
    TXT: [type=74626f74, pv=31]
    host: tbot-001.default.service.arpa.
    addresses: [fdde:ad00:beef::3]
unit-001._txing-coap._udp.default.service.arpa.
    deleted: false
    port: 5683
    TXT: [type=756e6974, pv=31]
    host: unit-001.default.service.arpa.
    addresses: [fdde:ad00:beef::2]
removed._txing-coap._udp.default.service.arpa.
    deleted: true
    port: 5683
    TXT: [type=706f7765722d7369, pv=31]
    host: removed.default.service.arpa.
    addresses: [fdde:ad00:beef::3]
Done
`

	endpoints, err := ParseOTCTLSRPServices(output, DefaultDomain, func() uint64 { return 1000 }, func() uint64 { return 7 })
	if err != nil {
		t.Fatal(err)
	}
	if len(endpoints) != 3 {
		t.Fatalf("endpoints = %#v, want three active supported endpoints", endpoints)
	}
	if endpoints[0].ThingName != "power-nrf-001" || endpoints[0].TXT["type"] != DeviceTypePowerNRF ||
		endpoints[1].ThingName != "power-si-001" || endpoints[1].TXT["type"] != DeviceTypePowerSI ||
		endpoints[2].ThingName != "tbot-001" || endpoints[2].TXT["type"] != DeviceTypeTBot {
		t.Fatalf("endpoints = %#v", endpoints)
	}
	endpoint := endpoints[1]
	if endpoint.Port != 5683 || endpoint.Address.String() != "fdde:ad00:beef::1" || endpoint.TXT["pv"] != "1" ||
		endpoint.TXT[DeviceProfileTXTKey] != SEDDebugProfile {
		t.Fatalf("endpoint = %#v", endpoint)
	}
}

func TestOTCTLSRPDiscovererReportsCommandFailure(t *testing.T) {
	discoverer := OTCTLSRPDiscoverer{
		Path:   "/usr/sbin/ot-ctl",
		Domain: DefaultDomain,
		Runner: fakeOTCTLRunner{err: context.DeadlineExceeded, output: []byte("connection failed")},
	}
	_, err := discoverer.Discover(context.Background())
	if err == nil || !strings.Contains(err.Error(), "ot-ctl srp server service") || !strings.Contains(err.Error(), "connection failed") {
		t.Fatalf("error = %v", err)
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

func TestPowerShadowPublishesValidUnavailableAndFailedBatteryValues(t *testing.T) {
	battery := 3011
	testCases := []struct {
		name  string
		value *int
		want  any
	}{
		{name: "valid", value: &battery, want: float64(3011)},
		{name: "unavailable", value: nil, want: nil},
		{name: "failed", value: nil, want: nil},
	}

	for _, testCase := range testCases {
		t.Run(testCase.name, func(t *testing.T) {
			updates, err := ShadowUpdatesFromState(DeviceState{
				ThingName: "power-nrf-001",
				BatteryMV: testCase.value,
			})
			if err != nil {
				t.Fatal(err)
			}
			if len(updates) != 2 || !strings.HasSuffix(updates[1].Topic, "/shadow/name/power/update") {
				t.Fatalf("updates = %#v", updates)
			}
			var payload struct {
				State struct {
					Reported map[string]any `json:"reported"`
				} `json:"state"`
			}
			if err := json.Unmarshal(updates[1].Payload, &payload); err != nil {
				t.Fatal(err)
			}
			if got := payload.State.Reported["batteryMv"]; got != testCase.want {
				t.Fatalf("batteryMv = %#v, want %#v", got, testCase.want)
			}
		})
	}
}

func TestDeviceSpecFromInventoryRetainsSupportedDeviceType(t *testing.T) {
	for _, testCase := range []struct {
		name      string
		thingName string
		thingType string
		want      bool
	}{
		{name: "power-si", thingName: "power-si-001", thingType: DeviceTypePowerSI, want: true},
		{name: "power-nrf", thingName: "power-nrf-001", thingType: DeviceTypePowerNRF, want: true},
		{name: "tbot", thingName: "tbot-001", thingType: DeviceTypeTBot, want: true},
		{name: "unsupported", thingName: "unit-001", thingType: "unit", want: false},
	} {
		t.Run(testCase.name, func(t *testing.T) {
			spec := DeviceSpecFromInventory(testInventoryDevice(testCase.thingName, testCase.thingType))
			if (spec != nil) != testCase.want {
				t.Fatalf("spec = %#v, want supported=%t", spec, testCase.want)
			}
			if spec != nil && (spec.ThingName != testCase.thingName || spec.ThingType != testCase.thingType) {
				t.Fatalf("spec = %#v", spec)
			}
		})
	}
}

func TestRuntimeRejectsEndpointWithMismatchedEnlistedType(t *testing.T) {
	publisher := &recordingPublisher{}
	runtime := NewRuntime(
		&fakeDiscoverer{endpoints: []Endpoint{testEndpointFor("power-nrf-001", DeviceTypePowerSI)}},
		&fakeDeviceClient{},
		publisher,
	)
	runtime.NowMS = func() uint64 { return 3500 }
	runtime.ReconcileInventory(testInventoryFor("power-nrf-001", DeviceTypePowerNRF))

	if err := runtime.DiscoverAndPoll(context.Background()); err != nil {
		t.Fatal(err)
	}
	if got := runtime.EndpointThingNames(); len(got) != 0 {
		t.Fatalf("endpoints = %#v, want no mismatched endpoint", got)
	}
	stateTopic, err := protocol.BuildCapabilityStateTopic("power-nrf-001", AdapterID)
	if err != nil {
		t.Fatal(err)
	}
	state, err := protocol.DecodeCapabilityState(publisher.retained[stateTopic])
	if err != nil {
		t.Fatal(err)
	}
	if state.Capabilities[ThreadCapability] || state.Capabilities[PowerCapability] {
		t.Fatalf("mismatched endpoint capability state = %#v", state.Capabilities)
	}
}

func TestRuntimeRejectsMismatchedEnlistedTbotEndpoint(t *testing.T) {
	publisher := &recordingPublisher{}
	client := &fakeDeviceClient{}
	runtime := NewRuntime(
		&fakeDiscoverer{endpoints: []Endpoint{testEndpointFor("tbot-001", DeviceTypePowerNRF)}},
		client,
		publisher,
	)
	runtime.NowMS = func() uint64 { return 3600 }
	runtime.ReconcileInventory(testInventoryFor("tbot-001", DeviceTypeTBot))

	if err := runtime.DiscoverAndPoll(context.Background()); err != nil {
		t.Fatal(err)
	}
	command, err := protocol.NewCapabilityCommand("cmd-tbot-mismatch", "tbot-001", 1, "test", 3600, 1, nil)
	if err != nil {
		t.Fatal(err)
	}
	if err := runtime.HandleCommand(context.Background(), command); err != nil {
		t.Fatal(err)
	}
	if client.putTarget != 0 {
		t.Fatalf("mismatched tbot endpoint received target REDCON %d", client.putTarget)
	}
	results := publisher.commandResults(t)
	if len(results) == 0 || results[len(results)-1].Status != protocol.CommandFailed {
		t.Fatalf("command results = %#v, want unavailable failure", results)
	}
}

func TestRuntimeConfirmsREDCONAndPublishesShadowsForBothDeviceTypes(t *testing.T) {
	for _, testCase := range []struct {
		name      string
		thingName string
		thingType string
	}{
		{name: "power-si", thingName: "power-si-001", thingType: DeviceTypePowerSI},
		{name: "power-nrf", thingName: "power-nrf-001", thingType: DeviceTypePowerNRF},
	} {
		t.Run(testCase.name, func(t *testing.T) {
			publisher := &recordingPublisher{}
			client := &fakeDeviceClient{
				state:    DeviceState{ThingName: testCase.thingName, ProtocolVersion: "1", Redcon: 3},
				putState: DeviceState{ThingName: testCase.thingName, ProtocolVersion: "1", Redcon: 4},
			}
			runtime := NewRuntime(
				&fakeDiscoverer{endpoints: []Endpoint{testEndpointFor(testCase.thingName, testCase.thingType)}},
				client,
				publisher,
			)
			runtime.NowMS = func() uint64 { return 4000 }
			runtime.ReconcileInventory(testInventoryFor(testCase.thingName, testCase.thingType))
			if err := runtime.DiscoverAndPoll(context.Background()); err != nil {
				t.Fatal(err)
			}
			command, err := protocol.NewCapabilityCommand("cmd-"+testCase.name, testCase.thingName, 4, "test", 4000, 77, nil)
			if err != nil {
				t.Fatal(err)
			}
			if err := runtime.HandleCommand(context.Background(), command); err != nil {
				t.Fatal(err)
			}
			if client.putTarget != 4 {
				t.Fatalf("put target = %d, want 4", client.putTarget)
			}
			stateTopic, err := protocol.BuildCapabilityStateTopic(testCase.thingName, AdapterID)
			if err != nil {
				t.Fatal(err)
			}
			state, err := protocol.DecodeCapabilityState(publisher.retained[stateTopic])
			if err != nil {
				t.Fatal(err)
			}
			if !state.Capabilities[ThreadCapability] || state.Capabilities[PowerCapability] {
				t.Fatalf("confirmed capability state = %#v", state.Capabilities)
			}
			assertPublishedTopic(t, publisher, "$aws/things/"+testCase.thingName+"/shadow/name/thread/update")
			assertPublishedTopic(t, publisher, "$aws/things/"+testCase.thingName+"/shadow/name/power/update")
		})
	}
}

func TestRuntimeNormalizesTbotPublicRedconWithoutChangingPowerDeviceRules(t *testing.T) {
	publisher := &recordingPublisher{}
	client := &fakeDeviceClient{putState: DeviceState{ThingName: "tbot-001", ProtocolVersion: "1", Redcon: 3}}
	runtime := NewRuntime(
		&fakeDiscoverer{endpoints: []Endpoint{testEndpointFor("tbot-001", DeviceTypeTBot)}},
		client,
		publisher,
	)
	runtime.NowMS = func() uint64 { return 4050 }
	runtime.ReconcileInventory(testInventoryFor("tbot-001", DeviceTypeTBot))
	runtime.recordEndpoints([]Endpoint{testEndpointFor("tbot-001", DeviceTypeTBot)})

	for _, publicTarget := range []uint8{1, 2, 3} {
		command, err := protocol.NewCapabilityCommand("cmd-tbot", "tbot-001", publicTarget, "test", 4050, uint64(publicTarget), nil)
		if err != nil {
			t.Fatal(err)
		}
		if err := runtime.HandleCommand(context.Background(), command); err != nil {
			t.Fatal(err)
		}
		if client.putTarget != 3 {
			t.Fatalf("public REDCON %d put target = %d, want transport REDCON 3", publicTarget, client.putTarget)
		}
	}

	powerSpec := DeviceSpec{ThingName: "power-si-001", ThingType: DeviceTypePowerSI}
	if _, err := NormalizeTargetRedcon(powerSpec, 2); err == nil {
		t.Fatal("power-si accepted public REDCON 2")
	}
}

func TestRuntimePollsMixedThreadPowerDeviceTypes(t *testing.T) {
	publisher := &recordingPublisher{}
	runtime := NewRuntime(
		&fakeDiscoverer{endpoints: []Endpoint{
			testEndpointFor("power-si-001", DeviceTypePowerSI),
			testEndpointFor("power-nrf-001", DeviceTypePowerNRF),
			testEndpointFor("tbot-001", DeviceTypeTBot),
		}},
		&stateByThingClient{states: map[string]DeviceState{
			"power-si-001":  {ThingName: "power-si-001", ProtocolVersion: "1", Redcon: 3},
			"power-nrf-001": {ThingName: "power-nrf-001", ProtocolVersion: "1", Redcon: 4},
			"tbot-001":      {ThingName: "tbot-001", ProtocolVersion: "1", Redcon: 3},
		}},
		publisher,
	)
	runtime.NowMS = func() uint64 { return 4100 }
	runtime.ReconcileInventory(protocol.NewInventory("manager", []protocol.InventoryDevice{
		testInventoryDevice("power-si-001", DeviceTypePowerSI),
		testInventoryDevice("power-nrf-001", DeviceTypePowerNRF),
		testInventoryDevice("tbot-001", DeviceTypeTBot),
	}, 1, 1000))

	if err := runtime.DiscoverAndPoll(context.Background()); err != nil {
		t.Fatal(err)
	}
	for _, testCase := range []struct {
		thingName string
		power     bool
	}{
		{thingName: "power-si-001", power: true},
		{thingName: "power-nrf-001", power: false},
		{thingName: "tbot-001", power: true},
	} {
		stateTopic, err := protocol.BuildCapabilityStateTopic(testCase.thingName, AdapterID)
		if err != nil {
			t.Fatal(err)
		}
		state, err := protocol.DecodeCapabilityState(publisher.retained[stateTopic])
		if err != nil {
			t.Fatal(err)
		}
		if !state.Capabilities[ThreadCapability] || state.Capabilities[PowerCapability] != testCase.power {
			t.Fatalf("%s capability state = %#v", testCase.thingName, state.Capabilities)
		}
		assertPublishedTopic(t, publisher, "$aws/things/"+testCase.thingName+"/shadow/name/thread/update")
		assertPublishedTopic(t, publisher, "$aws/things/"+testCase.thingName+"/shadow/name/power/update")
	}
}

func TestRuntimeDoesNotRepublishUnchangedShadows(t *testing.T) {
	publisher := &recordingPublisher{}
	runtime := NewRuntime(
		&fakeDiscoverer{endpoints: []Endpoint{testEndpoint("power-si-001")}},
		&fakeDeviceClient{state: DeviceState{ThingName: "power-si-001", ProtocolVersion: "1", Redcon: 4}},
		publisher,
	)
	runtime.NowMS = func() uint64 { return 2000 }
	runtime.ReconcileInventory(testInventory())

	if err := runtime.DiscoverAndPoll(context.Background()); err != nil {
		t.Fatal(err)
	}
	if err := runtime.DiscoverAndPoll(context.Background()); err != nil {
		t.Fatal(err)
	}

	topic := "$aws/things/power-si-001/shadow/name/thread/update"
	if got := publisher.publishedTopicCount(topic); got != 1 {
		t.Fatalf("Thread shadow updates = %d, want 1", got)
	}
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
	if got := publisher.publishedTopicCount(stateTopic); got != 1 {
		t.Fatalf("offline capability publications = %d, want one", got)
	}
	assertPublishedTopic(t, publisher, "$aws/things/power-si-001/shadow/name/thread/update")
}

func TestRuntimeFailedPollPublishesOfflineOnce(t *testing.T) {
	publisher := &recordingPublisher{}
	runtime := NewRuntime(
		&fakeDiscoverer{endpoints: []Endpoint{testEndpoint("power-si-001")}},
		&fakeDeviceClient{err: context.DeadlineExceeded},
		publisher,
	)
	runtime.ReconcileInventory(testInventory())

	if err := runtime.DiscoverAndPoll(context.Background()); err != nil {
		t.Fatal(err)
	}
	stateTopic, _ := protocol.BuildCapabilityStateTopic("power-si-001", AdapterID)
	if got := publisher.publishedTopicCount(stateTopic); got != 1 {
		t.Fatalf("offline capability publications after failed poll = %d, want one", got)
	}
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
	stateTopic, err := protocol.BuildCapabilityStateTopic("power-si-001", AdapterID)
	if err != nil {
		t.Fatal(err)
	}
	state, err := protocol.DecodeCapabilityState(publisher.retained[stateTopic])
	if err != nil {
		t.Fatal(err)
	}
	if !state.Capabilities[ThreadCapability] || state.Capabilities[PowerCapability] {
		t.Fatalf("confirmed REDCON 4 capability state = %#v", state.Capabilities)
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

func TestRuntimeReportsConfirmedSEDDebugRedconTransition(t *testing.T) {
	publisher := &recordingPublisher{}
	endpoint := testEndpoint("power-si-001")
	endpoint.TXT[DeviceProfileTXTKey] = SEDDebugProfile
	client := &fakeDeviceClient{putState: DeviceState{ThingName: "power-si-001", ProtocolVersion: "1", Redcon: 3}}
	runtime := NewRuntime(&fakeDiscoverer{endpoints: []Endpoint{endpoint}}, client, publisher)
	runtime.NowMS = func() uint64 { return 4500 }
	runtime.ReconcileInventory(testInventory())
	runtime.recordEndpoints([]Endpoint{endpoint})

	var confirmed Endpoint
	var redcon uint8
	runtime.OnSEDDebugRedconConfirmed = func(received Endpoint, target uint8) {
		confirmed = received
		redcon = target
	}
	command, err := protocol.NewCapabilityCommand("cmd-sed", "power-si-001", 3, "test", 4500, 77, nil)
	if err != nil {
		t.Fatal(err)
	}

	if err := runtime.HandleCommand(context.Background(), command); err != nil {
		t.Fatal(err)
	}
	if confirmed.ThingName != "power-si-001" || redcon != 3 {
		t.Fatalf("sed-debug confirmation = endpoint=%#v redcon=%d", confirmed, redcon)
	}
	if !IsSEDDebugEndpoint(confirmed) {
		t.Fatalf("endpoint is not sed-debug: %#v", confirmed)
	}
	if mode := SEDDebugLinkModeForRedcon(redcon); mode != "rn" {
		t.Fatalf("redcon %d mode = %q, want rn", redcon, mode)
	}
}

func TestRuntimeDoesNotReportRedconTransitionForNormalProfile(t *testing.T) {
	publisher := &recordingPublisher{}
	endpoint := testEndpoint("power-si-001")
	client := &fakeDeviceClient{putState: DeviceState{ThingName: "power-si-001", ProtocolVersion: "1", Redcon: 4}}
	runtime := NewRuntime(&fakeDiscoverer{endpoints: []Endpoint{endpoint}}, client, publisher)
	runtime.NowMS = func() uint64 { return 4600 }
	runtime.ReconcileInventory(testInventory())
	runtime.recordEndpoints([]Endpoint{endpoint})
	reported := false
	runtime.OnSEDDebugRedconConfirmed = func(Endpoint, uint8) { reported = true }
	command, err := protocol.NewCapabilityCommand("cmd-normal", "power-si-001", 4, "test", 4600, 78, nil)
	if err != nil {
		t.Fatal(err)
	}

	if err := runtime.HandleCommand(context.Background(), command); err != nil {
		t.Fatal(err)
	}
	if reported {
		t.Fatal("normal profile reported a sed-debug REDCON transition")
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
	return testInventoryFor("power-si-001", DeviceTypePowerSI)
}

func testInventoryFor(thingName string, thingType string) protocol.Inventory {
	return protocol.NewInventory("manager", []protocol.InventoryDevice{testInventoryDevice(thingName, thingType)}, 1, 1000)
}

func testInventoryDevice(thingName string, thingType string) protocol.InventoryDevice {
	if thingType == DeviceTypeTBot {
		return protocol.InventoryDevice{
			ThingName:           thingName,
			ThingType:           thingType,
			Capabilities:        []string{"sparkplug", "thread", "power", "board", "mcp", "video"},
			RedconCommandLevels: []uint8{4, 3, 2, 1},
			RedconRules: map[uint8][]string{
				4: {"sparkplug", "thread"},
				3: {"sparkplug", "thread", "power"},
				2: {"sparkplug", "thread", "power", "board", "mcp"},
				1: {"sparkplug", "thread", "power", "board", "mcp", "video"},
			},
		}
	}
	return protocol.InventoryDevice{
		ThingName:           thingName,
		ThingType:           thingType,
		Capabilities:        []string{"sparkplug", "thread", "power"},
		RedconCommandLevels: []uint8{4, 3},
		RedconRules: map[uint8][]string{
			4: {"sparkplug", "thread"},
			3: {"sparkplug", "thread", "power"},
		},
	}
}

func testEndpoint(thingName string) Endpoint {
	return testEndpointFor(thingName, DeviceTypePowerSI)
}

func testEndpointFor(thingName string, thingType string) Endpoint {
	return Endpoint{
		ThingName:       thingName,
		ServiceInstance: thingName + "._txing-coap._udp.default.service.arpa",
		ServiceName:     ServiceName,
		Host:            thingName + ".default.service.arpa",
		Address:         net.ParseIP("fdde:ad00:beef::1"),
		Port:            5683,
		TXT:             map[string]string{"type": thingType, "pv": "1"},
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

type fakeOTCTLRunner struct {
	output []byte
	err    error
}

func (f fakeOTCTLRunner) Run(_ context.Context, _ string, _ ...string) ([]byte, error) {
	return f.output, f.err
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

type stateByThingClient struct {
	states map[string]DeviceState
}

func (c *stateByThingClient) GetState(_ context.Context, endpoint Endpoint) (DeviceState, error) {
	return c.states[endpoint.ThingName], nil
}

func (c *stateByThingClient) PutRedcon(_ context.Context, endpoint Endpoint, target uint8) (DeviceState, error) {
	state := c.states[endpoint.ThingName]
	state.Redcon = target
	c.states[endpoint.ThingName] = state
	return state, nil
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
	mu        sync.Mutex
	published []publishedMessage
	retained  map[string][]byte
}

type publishedMessage struct {
	topic   string
	payload []byte
}

func (p *recordingPublisher) Publish(topic string, payload []byte) error {
	p.mu.Lock()
	defer p.mu.Unlock()
	p.published = append(p.published, publishedMessage{topic: topic, payload: append([]byte(nil), payload...)})
	return nil
}

func (p *recordingPublisher) PublishRetained(topic string, payload []byte) error {
	p.mu.Lock()
	defer p.mu.Unlock()
	if p.retained == nil {
		p.retained = map[string][]byte{}
	}
	p.retained[topic] = append([]byte(nil), payload...)
	p.published = append(p.published, publishedMessage{topic: topic, payload: append([]byte(nil), payload...)})
	return nil
}

func (p *recordingPublisher) commandResults(t *testing.T) []protocol.CapabilityCommandResult {
	t.Helper()
	p.mu.Lock()
	defer p.mu.Unlock()
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

func (p *recordingPublisher) publishedTopicCount(topic string) int {
	p.mu.Lock()
	defer p.mu.Unlock()
	count := 0
	for _, message := range p.published {
		if message.topic == topic {
			count++
		}
	}
	return count
}

func assertPublishedTopic(t *testing.T, publisher *recordingPublisher, topic string) {
	t.Helper()
	publisher.mu.Lock()
	defer publisher.mu.Unlock()
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
