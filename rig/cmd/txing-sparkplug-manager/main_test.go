package main

import (
	"context"
	"errors"
	"reflect"
	"sync"
	"testing"
	"time"

	"github.com/mparkachov/txing/rig/internal/ipc"
	"github.com/mparkachov/txing/rig/internal/manager"
	"github.com/mparkachov/txing/rig/internal/mqttx"
	"github.com/mparkachov/txing/rig/internal/protocol"
	"github.com/mparkachov/txing/rig/internal/registry"
	"github.com/mparkachov/txing/rig/internal/rigconfig"
	"github.com/mparkachov/txing/rig/internal/sparkplug"
)

type fakeNodeMQTTClient struct {
	subscriptions []string
	unsubscribes  []string
	publishes     []fakePublish
	disconnects   int
	publishErr    error
	publishOrder  *[]string
}

type fakePublish struct {
	topic    string
	payload  []byte
	retained bool
}

func (f *fakeNodeMQTTClient) Subscribe(filter string, _ func(mqttx.Message)) error {
	f.subscriptions = append(f.subscriptions, filter)
	return nil
}

func (f *fakeNodeMQTTClient) Unsubscribe(filter string) error {
	f.unsubscribes = append(f.unsubscribes, filter)
	return nil
}

func (f *fakeNodeMQTTClient) Publish(topic string, payload []byte, retained bool) error {
	if f.publishErr != nil {
		return f.publishErr
	}
	if f.publishOrder != nil {
		*f.publishOrder = append(*f.publishOrder, topic)
	}
	f.publishes = append(f.publishes, fakePublish{
		topic:    topic,
		payload:  append([]byte(nil), payload...),
		retained: retained,
	})
	return nil
}

func (f *fakeNodeMQTTClient) Disconnect(uint) { f.disconnects++ }

func TestIsThingShadowUpdateTopic(t *testing.T) {
	for _, topic := range []string{
		"$aws/things/unit-1/shadow/name/mcu/update",
		"$aws/things/unit-1/shadow/name/power/update",
	} {
		if !isThingShadowUpdateTopic(topic) {
			t.Fatalf("expected %s to match", topic)
		}
	}
	for _, topic := range []string{
		"$aws/things/unit-1/shadow/name/mcu/get",
		"$aws/things/unit-1/shadow/update",
		"$aws/things//shadow/name/mcu/update",
		"txings/unit-1/capability/v2/state",
	} {
		if isThingShadowUpdateTopic(topic) {
			t.Fatalf("expected %s not to match", topic)
		}
	}
}

func TestHandleIPCMessageSuppressesIdenticalShadowUpdates(t *testing.T) {
	node := &fakeNodeMQTTClient{}
	state := &runtimeState{nodeMQTT: node, shadowPayloads: map[string][]byte{}}
	topic := "$aws/things/unit-1/shadow/name/power/update"
	first := []byte(`{"state":{"reported":{"batteryMv":3011}}}`)
	sameValueWithWhitespace := []byte("{\n  \"state\": {\"reported\": {\"batteryMv\": 3011}}\n}")
	changed := []byte(`{"state":{"reported":{"batteryMv":3012}}}`)

	state.handleIPCMessage(context.Background(), ipc.Message{Topic: topic, Payload: first})
	state.handleIPCMessage(context.Background(), ipc.Message{Topic: topic, Payload: sameValueWithWhitespace})
	if len(node.publishes) != 1 {
		t.Fatalf("identical shadow publishes = %#v, want one", node.publishes)
	}
	state.handleIPCMessage(context.Background(), ipc.Message{Topic: topic, Payload: changed})
	if len(node.publishes) != 2 {
		t.Fatalf("changed shadow publishes = %#v, want two", node.publishes)
	}
	if string(node.publishes[0].payload) != string(first) {
		t.Fatalf("first payload = %s, want compact payload %s", node.publishes[0].payload, first)
	}
}

func TestPublishNodeOnlineRestoresSubscriptionsAndPublishesBirth(t *testing.T) {
	state := &runtimeState{cfg: rigconfig.Config{
		TownID: "town-1",
		RigID:  "rig-1",
	}}
	client := &fakeNodeMQTTClient{}

	if err := state.publishNodeOnline(client); err != nil {
		t.Fatal(err)
	}

	wantSubscriptions := []string{
		sparkplug.BuildNodeCommandTopic("town-1", "rig-1"),
		sparkplug.BuildDeviceTopic("town-1", "DCMD", "rig-1", "+"),
		boardRetainedCapabilityStateFilter,
	}
	if !reflect.DeepEqual(client.subscriptions, wantSubscriptions) {
		t.Fatalf("subscriptions = %#v, want %#v", client.subscriptions, wantSubscriptions)
	}
	if len(client.publishes) != 1 {
		t.Fatalf("publish count = %d, want 1", len(client.publishes))
	}
	published := client.publishes[0]
	if published.topic != sparkplug.BuildNodeTopic("town-1", "NBIRTH", "rig-1") {
		t.Fatalf("publish topic = %s", published.topic)
	}
	if published.retained {
		t.Fatal("NBIRTH publish must not be retained")
	}

	payload, err := sparkplug.DecodePayload(published.payload)
	if err != nil {
		t.Fatal(err)
	}
	if payload.Seq == nil || *payload.Seq != 0 {
		t.Fatalf("seq = %#v, want 0", payload.Seq)
	}
	assertMetric(t, payload.Metrics, sparkplug.NewUInt64Metric("bdSeq", nodeBDSeq))
	assertMetric(t, payload.Metrics, sparkplug.NewInt32Metric("redcon", 1))

	if err := state.publishNodeOnline(client); err != nil {
		t.Fatal(err)
	}
	payload, err = sparkplug.DecodePayload(client.publishes[1].payload)
	if err != nil {
		t.Fatal(err)
	}
	if payload.Seq == nil || *payload.Seq != 1 {
		t.Fatalf("second seq = %#v, want 1", payload.Seq)
	}
}

func TestPublishNodeOnlineRestoresExactBoardRetainedSubscriptions(t *testing.T) {
	state := &runtimeState{
		cfg: rigconfig.Config{
			TownID: "town-1",
			RigID:  "rig-1",
		},
		devices: map[string]*managedDevice{
			"unit-b": {},
			"unit-a": {},
		},
		boardStateSubscriptions: map[string]struct{}{
			"unit-a": {},
		},
	}
	client := &fakeNodeMQTTClient{}

	if err := state.publishNodeOnline(client); err != nil {
		t.Fatal(err)
	}

	wantSubscriptions := []string{
		sparkplug.BuildNodeCommandTopic("town-1", "rig-1"),
		sparkplug.BuildDeviceTopic("town-1", "DCMD", "rig-1", "+"),
		boardRetainedCapabilityStateFilter,
		boardRetainedCapabilityStateTopic("unit-a"),
		boardRetainedCapabilityStateTopic("unit-b"),
	}
	if !reflect.DeepEqual(client.subscriptions, wantSubscriptions) {
		t.Fatalf("subscriptions = %#v, want %#v", client.subscriptions, wantSubscriptions)
	}
	if len(client.publishes) != 1 {
		t.Fatalf("publish count = %d, want 1", len(client.publishes))
	}
	if client.publishes[0].retained {
		t.Fatal("NBIRTH publish must not be retained")
	}
}

func TestPublishNodeOnlineInRedconFourKeepsOnlyNodeCommandPath(t *testing.T) {
	state := &runtimeState{cfg: rigconfig.Config{
		TownID: "town-1",
		RigID:  "rig-1",
	}}
	state.setNodeRedcon(nodeRedconCommandable)
	client := &fakeNodeMQTTClient{}

	if err := state.publishNodeOnline(client); err != nil {
		t.Fatal(err)
	}

	wantSubscriptions := []string{sparkplug.BuildNodeCommandTopic("town-1", "rig-1")}
	if !reflect.DeepEqual(client.subscriptions, wantSubscriptions) {
		t.Fatalf("subscriptions = %#v, want %#v", client.subscriptions, wantSubscriptions)
	}
	payload, err := sparkplug.DecodePayload(client.publishes[0].payload)
	if err != nil {
		t.Fatal(err)
	}
	assertMetric(t, payload.Metrics, sparkplug.NewInt32Metric("redcon", 4))
}

func TestNodeRedconFourCommandTearsDownActiveWorkAndPublishesBirth(t *testing.T) {
	node := &fakeNodeMQTTClient{}
	device := &fakeNodeMQTTClient{}
	state := &runtimeState{
		cfg: rigconfig.Config{
			TownID: "town-1",
			RigID:  "rig-1",
		},
		nodeMQTT: node,
		devices: map[string]*managedDevice{
			"unit-1": {mqtt: device},
		},
		boardStateSubscriptions: map[string]struct{}{
			"unit-1": {},
		},
	}

	state.handleMQTTMessage(context.Background(), mqttx.Message{
		Topic:   sparkplug.BuildNodeCommandTopic("town-1", "rig-1"),
		Payload: redconCommandPayload(t, 4, 7),
	})

	wantUnsubscribes := []string{
		sparkplug.BuildDeviceTopic("town-1", "DCMD", "rig-1", "+"),
		boardRetainedCapabilityStateFilter,
		boardRetainedCapabilityStateTopic("unit-1"),
	}
	if !reflect.DeepEqual(node.unsubscribes, wantUnsubscribes) {
		t.Fatalf("unsubscribes = %#v, want %#v", node.unsubscribes, wantUnsubscribes)
	}
	if device.disconnects != 1 {
		t.Fatalf("device disconnects = %d, want 1", device.disconnects)
	}
	if state.devices["unit-1"].mqtt != nil {
		t.Fatal("device MQTT client should be cleared")
	}
	if state.currentNodeRedcon() != nodeRedconCommandable {
		t.Fatalf("node redcon = %d, want 4", state.currentNodeRedcon())
	}
	payload, err := sparkplug.DecodePayload(node.publishes[0].payload)
	if err != nil {
		t.Fatal(err)
	}
	assertMetric(t, payload.Metrics, sparkplug.NewInt32Metric("redcon", 4))
	assertMetric(t, payload.Metrics, sparkplug.NewStringMetric("redconCommandStatus", "succeeded"))
	assertMetric(t, payload.Metrics, sparkplug.NewInt32Metric("redconCommandSeq", 7))
	assertMetric(t, payload.Metrics, sparkplug.NewInt32Metric("redconCommandTarget", 4))
}

func TestNodeRedconOneCommandRestoresActiveSubscriptions(t *testing.T) {
	node := &fakeNodeMQTTClient{}
	state := &runtimeState{
		cfg: rigconfig.Config{
			TownID: "town-1",
			RigID:  "rig-1",
		},
		nodeMQTT:                node,
		devices:                 map[string]*managedDevice{},
		boardStateSubscriptions: map[string]struct{}{},
	}
	state.setNodeRedcon(nodeRedconCommandable)

	state.handleMQTTMessage(context.Background(), mqttx.Message{
		Topic:   sparkplug.BuildNodeCommandTopic("town-1", "rig-1"),
		Payload: redconCommandPayload(t, 1, 8),
	})

	wantSubscriptions := []string{
		sparkplug.BuildDeviceTopic("town-1", "DCMD", "rig-1", "+"),
		boardRetainedCapabilityStateFilter,
	}
	if !reflect.DeepEqual(node.subscriptions, wantSubscriptions) {
		t.Fatalf("subscriptions = %#v, want %#v", node.subscriptions, wantSubscriptions)
	}
	if state.currentNodeRedcon() != nodeRedconActive {
		t.Fatalf("node redcon = %d, want 1", state.currentNodeRedcon())
	}
	payload, err := sparkplug.DecodePayload(node.publishes[0].payload)
	if err != nil {
		t.Fatal(err)
	}
	assertMetric(t, payload.Metrics, sparkplug.NewInt32Metric("redcon", 1))
	assertMetric(t, payload.Metrics, sparkplug.NewStringMetric("redconCommandStatus", "succeeded"))
	assertMetric(t, payload.Metrics, sparkplug.NewInt32Metric("redconCommandSeq", 8))
	assertMetric(t, payload.Metrics, sparkplug.NewInt32Metric("redconCommandTarget", 1))
}

func TestNodeRedconOneCommandRefreshesInventoryImmediately(t *testing.T) {
	node := &fakeNodeMQTTClient{}
	loader := &fakeInventoryLoader{inventory: registry.Inventory{RigType: "raspi"}}
	broker := &fakeIPCBroker{}
	state := &runtimeState{
		cfg: rigconfig.Config{
			TownID: "town-1",
			RigID:  "rig-1",
		},
		broker:                  broker,
		registry:                loader,
		nodeMQTT:                node,
		devices:                 map[string]*managedDevice{},
		boardStateSubscriptions: map[string]struct{}{},
	}
	state.setNodeRedcon(nodeRedconCommandable)

	state.handleMQTTMessage(context.Background(), mqttx.Message{
		Topic:   sparkplug.BuildNodeCommandTopic("town-1", "rig-1"),
		Payload: redconCommandPayload(t, 1, 9),
	})

	if loader.calls != 1 {
		t.Fatalf("inventory refresh calls after redcon 4->1 = %d, want 1", loader.calls)
	}
	if len(broker.publishes) != 1 {
		t.Fatalf("inventory publishes after redcon 4->1 = %d, want 1", len(broker.publishes))
	}
	if broker.publishes[0].topic != protocol.InventoryTopic || !broker.publishes[0].retained {
		t.Fatalf("inventory publish = %#v, want retained %s", broker.publishes[0], protocol.InventoryTopic)
	}
}

func TestEnsureBoardStateSubscriptionDeduplicatesExactTopic(t *testing.T) {
	state := &runtimeState{boardStateSubscriptions: map[string]struct{}{}}
	client := &fakeNodeMQTTClient{}

	if err := state.ensureBoardStateSubscription(client, "unit-1"); err != nil {
		t.Fatal(err)
	}
	if err := state.ensureBoardStateSubscription(client, "unit-1"); err != nil {
		t.Fatal(err)
	}

	wantSubscriptions := []string{boardRetainedCapabilityStateTopic("unit-1")}
	if !reflect.DeepEqual(client.subscriptions, wantSubscriptions) {
		t.Fatalf("subscriptions = %#v, want %#v", client.subscriptions, wantSubscriptions)
	}
}

func TestSparkplugDevicePublicationsAreNotRetained(t *testing.T) {
	state := &runtimeState{cfg: rigconfig.Config{
		TownID: "town-1",
		RigID:  "rig-1",
	}}
	client := &fakeNodeMQTTClient{}
	managed := &managedDevice{mqtt: client}

	state.publishDeviceReport(context.Background(), managed, "unit-1", "DBIRTH", 1, nil)
	state.publishDeviceReport(context.Background(), managed, "unit-1", "DDATA", 1, nil)
	state.publishDeviceDeath(context.Background(), managed, "unit-1")

	wantTopics := []string{
		sparkplug.BuildDeviceTopic("town-1", "DBIRTH", "rig-1", "unit-1"),
		sparkplug.BuildDeviceTopic("town-1", "DDATA", "rig-1", "unit-1"),
		sparkplug.BuildDeviceTopic("town-1", "DDEATH", "rig-1", "unit-1"),
	}
	if len(client.publishes) != len(wantTopics) {
		t.Fatalf("publish count = %d, want %d", len(client.publishes), len(wantTopics))
	}
	for i, wantTopic := range wantTopics {
		if client.publishes[i].topic != wantTopic {
			t.Fatalf("publish[%d] topic = %s, want %s", i, client.publishes[i].topic, wantTopic)
		}
		if client.publishes[i].retained {
			t.Fatalf("%s publish must not be retained", wantTopic)
		}
	}
}

func TestDeviceSessionLifecycleFollowsValidatedBLEAndThreadEvidence(t *testing.T) {
	tests := []struct {
		name         string
		inventory    protocol.InventoryDevice
		adapterID    string
		capabilities map[string]bool
	}{
		{
			name:      "BLE",
			inventory: powerBLEInventory("power-ble-1"),
			adapterID: "dev.txing.rig.BleConnectivity",
			capabilities: map[string]bool{
				"sparkplug": true, "ble": true, "power": true,
			},
		},
		{
			name:      "Thread",
			inventory: powerThreadInventory("power-si-1"),
			adapterID: "dev.txing.rig.ThreadConnectivity",
			capabilities: map[string]bool{
				"sparkplug": true, "thread": true, "power": true,
			},
		},
	}

	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			managed := &managedDevice{state: manager.NewDeviceRuntimeState(test.inventory)}
			state := &runtimeState{
				cfg: rigconfig.Config{TownID: "town-1", RigID: "rig-1"},
				devices: map[string]*managedDevice{
					test.inventory.ThingName: managed,
				},
			}
			var clients []*fakeNodeMQTTClient
			state.newDeviceMQTT = func(options mqttx.Options) (managedMQTTClient, error) {
				if options.ClientID != test.inventory.ThingName {
					t.Fatalf("device client id = %s, want %s", options.ClientID, test.inventory.ThingName)
				}
				client := &fakeNodeMQTTClient{}
				clients = append(clients, client)
				return client, nil
			}

			now := uint64(time.Now().UnixMilli())
			if err := managed.state.ObserveState(protocol.CapabilityState{
				SchemaVersion: protocol.SchemaVersion,
				AdapterID:     test.adapterID,
				ThingName:     test.inventory.ThingName,
				Capabilities:  test.capabilities,
				Metrics:       map[string]protocol.MetricValue{},
				ObservedAtMS:  now,
				Seq:           1,
			}); err != nil {
				t.Fatal(err)
			}
			state.publishDeviceState(context.Background())
			if len(clients) != 1 || managed.mqtt != clients[0] {
				t.Fatalf("validated evidence created clients=%d mqtt=%T, want one active device client", len(clients), managed.mqtt)
			}
			assertPublishedDeviceTopic(t, clients[0], sparkplug.BuildDeviceTopic("town-1", "DBIRTH", "rig-1", test.inventory.ThingName), 1)

			unavailable := make(map[string]bool, len(test.capabilities))
			for capability := range test.capabilities {
				unavailable[capability] = false
			}
			if err := managed.state.ObserveState(protocol.CapabilityState{
				SchemaVersion: protocol.SchemaVersion,
				AdapterID:     test.adapterID,
				ThingName:     test.inventory.ThingName,
				Capabilities:  unavailable,
				Metrics:       map[string]protocol.MetricValue{},
				ObservedAtMS:  now + 1,
				Seq:           2,
			}); err != nil {
				t.Fatal(err)
			}
			state.publishDeviceState(context.Background())
			assertPublishedDeviceTopic(t, clients[0], sparkplug.BuildDeviceTopic("town-1", "DDEATH", "rig-1", test.inventory.ThingName), 1)
			if clients[0].disconnects != 1 || managed.mqtt != nil {
				t.Fatalf("unavailable device disconnects=%d mqtt=%T, want one disconnect and no session", clients[0].disconnects, managed.mqtt)
			}

			state.publishDeviceState(context.Background())
			if len(clients) != 1 {
				t.Fatalf("unavailable publication tick recreated %d clients, want one", len(clients))
			}
			assertPublishedDeviceTopic(t, clients[0], sparkplug.BuildDeviceTopic("town-1", "DDEATH", "rig-1", test.inventory.ThingName), 1)

			if err := managed.state.ObserveState(protocol.CapabilityState{
				SchemaVersion: protocol.SchemaVersion,
				AdapterID:     test.adapterID,
				ThingName:     test.inventory.ThingName,
				Capabilities:  test.capabilities,
				Metrics:       map[string]protocol.MetricValue{},
				ObservedAtMS:  now + 2,
				Seq:           3,
			}); err != nil {
				t.Fatal(err)
			}
			state.publishDeviceState(context.Background())
			if len(clients) != 2 || managed.mqtt != clients[1] {
				t.Fatalf("recovered evidence created clients=%d mqtt=%T, want a new active device client", len(clients), managed.mqtt)
			}
			recoveryTopic := sparkplug.BuildDeviceTopic("town-1", "DBIRTH", "rig-1", test.inventory.ThingName)
			assertPublishedDeviceTopic(t, clients[1], recoveryTopic, 1)
			recovery, err := sparkplug.DecodePayload(clients[1].publishes[0].payload)
			if err != nil {
				t.Fatal(err)
			}
			for capability, available := range test.capabilities {
				assertMetric(t, recovery.Metrics, sparkplug.NewBooleanMetric("capability."+capability, available))
			}
		})
	}
}

func TestDeviceMQTTReconnectRepublishesUnchangedState(t *testing.T) {
	for _, adapter := range []struct {
		name      string
		inventory protocol.InventoryDevice
		adapterID string
		transport string
	}{
		{"BLE", powerBLEInventory("power-ble-1"), "dev.txing.rig.BleConnectivity", "ble"},
		{"Thread", powerThreadInventory("power-si-1"), "dev.txing.rig.ThreadConnectivity", "thread"},
		{"TBot", protocol.InventoryDevice{
			ThingName: "tbot-8yzfgj", ThingType: "tbot",
			Capabilities:        []string{"sparkplug", "thread", "power", "board", "mavlink", "video"},
			RedconCommandLevels: []uint8{4, 3, 2, 1},
			RedconRules: map[uint8][]string{
				4: {"sparkplug", "thread"}, 3: {"sparkplug", "thread", "power"},
				2: {"sparkplug", "thread", "power", "board", "mavlink"},
				1: {"sparkplug", "thread", "power", "board", "mavlink", "video"},
			},
		}, "dev.txing.rig.ThreadConnectivity", "thread"},
	} {
		t.Run(adapter.name, func(t *testing.T) {
			managed := &managedDevice{state: manager.NewDeviceRuntimeState(adapter.inventory)}
			state := &runtimeState{
				cfg:     rigconfig.Config{TownID: "town-1", RigID: "rig-1"},
				devices: map[string]*managedDevice{adapter.inventory.ThingName: managed},
			}
			client := &fakeNodeMQTTClient{}
			var options mqttx.Options
			connections := 0
			state.newDeviceMQTT = func(created mqttx.Options) (managedMQTTClient, error) {
				options = created
				connections++
				if options.OnConnection != nil {
					options.OnConnection()
				}
				return client, nil
			}
			if err := managed.state.ObserveState(protocol.CapabilityState{
				SchemaVersion: protocol.SchemaVersion,
				AdapterID:     adapter.adapterID,
				ThingName:     adapter.inventory.ThingName,
				Capabilities:  map[string]bool{"sparkplug": true, adapter.transport: true, "power": false},
				Metrics:       map[string]protocol.MetricValue{},
				ObservedAtMS:  uint64(time.Now().UnixMilli()),
				Seq:           1,
			}); err != nil {
				t.Fatal(err)
			}
			birthTopic := sparkplug.BuildDeviceTopic("town-1", "DBIRTH", "rig-1", adapter.inventory.ThingName)
			state.publishDeviceState(context.Background())
			state.publishDeviceState(context.Background())
			assertPublishedDeviceTopic(t, client, birthTopic, 1)
			if options.OnConnection == nil {
				t.Fatal("device MQTT session has no reconnect handler")
			}

			// The broker publishes the configured DDEATH will during an outage.
			// Reconnecting must replace that projection even with identical evidence.
			options.OnConnection()
			state.publishDeviceState(context.Background())
			state.publishDeviceState(context.Background())
			assertPublishedDeviceTopic(t, client, birthTopic, 2)
			if connections != 1 || client.disconnects != 0 {
				t.Fatalf("reconnect churned the session: created=%d disconnected=%d", connections, client.disconnects)
			}
			recovered, err := sparkplug.DecodePayload(client.publishes[1].payload)
			if err != nil {
				t.Fatal(err)
			}
			assertMetric(t, recovered.Metrics, sparkplug.NewBooleanMetric("capability."+adapter.transport, true))
			assertMetric(t, recovered.Metrics, sparkplug.NewInt32Metric("redcon", 4))
		})
	}
}

func TestNodeMQTTReconnectRepublishesDeviceBirths(t *testing.T) {
	inventory := powerThreadInventory("power-si-1")
	managed := &managedDevice{state: manager.NewDeviceRuntimeState(inventory)}
	var publishOrder []string
	client := &fakeNodeMQTTClient{publishOrder: &publishOrder}
	state := &runtimeState{
		cfg:     rigconfig.Config{TownID: "town-1", RigID: "rig-1"},
		devices: map[string]*managedDevice{inventory.ThingName: managed},
		newDeviceMQTT: func(mqttx.Options) (managedMQTTClient, error) {
			return client, nil
		},
	}
	if err := managed.state.ObserveState(protocol.CapabilityState{
		SchemaVersion: protocol.SchemaVersion, AdapterID: "dev.txing.rig.ThreadConnectivity", ThingName: inventory.ThingName,
		Capabilities: map[string]bool{"sparkplug": true, "thread": true, "power": false},
		Metrics:      map[string]protocol.MetricValue{}, ObservedAtMS: uint64(time.Now().UnixMilli()), Seq: 1,
	}); err != nil {
		t.Fatal(err)
	}
	node := &fakeNodeMQTTClient{publishOrder: &publishOrder}
	var options mqttx.Options
	state.newNodeMQTT = func(created mqttx.Options) (nodeMQTTClient, error) {
		options = created
		options.OnConnection()
		return node, nil
	}
	if err := state.connectNodeMQTT(context.Background()); err != nil {
		t.Fatal(err)
	}
	state.publishDeviceState(context.Background())
	state.publishDeviceState(context.Background())
	birthTopic := sparkplug.BuildDeviceTopic("town-1", "DBIRTH", "rig-1", inventory.ThingName)
	assertPublishedDeviceTopic(t, client, birthTopic, 1)

	options.OnConnection()
	state.publishDeviceState(context.Background())
	state.publishDeviceState(context.Background())
	assertPublishedDeviceTopic(t, client, birthTopic, 2)
	if client.disconnects != 0 {
		t.Fatal("node reconnect must reuse the live device MQTT session")
	}
	nodeBirthTopic := sparkplug.BuildNodeTopic("town-1", "NBIRTH", "rig-1")
	if !reflect.DeepEqual(publishOrder, []string{nodeBirthTopic, birthTopic, nodeBirthTopic, birthTopic}) {
		t.Fatalf("reconnect publication order = %v", publishOrder)
	}
}

func TestNodeMQTTReconnectRetriesBirthBeforeDeviceRecovery(t *testing.T) {
	state, managed, device := newThreadPublicationState(t)
	node := &fakeNodeMQTTClient{}
	var options mqttx.Options
	state.newNodeMQTT = func(created mqttx.Options) (nodeMQTTClient, error) {
		options = created
		options.OnConnection()
		return node, nil
	}
	if err := state.connectNodeMQTT(context.Background()); err != nil {
		t.Fatal(err)
	}
	state.publishDeviceState(context.Background())
	options.OnConnection()
	node.publishErr = errors.New("connection unavailable")
	state.publishDeviceState(context.Background())
	if len(device.publishes) != 1 || managed.mqtt != device {
		t.Fatal("device publications must wait for the node birth to recover")
	}
	node.publishErr = nil
	state.publishDeviceState(context.Background())
	state.publishDeviceState(context.Background())
	assertPublishedDeviceTopic(t, device, sparkplug.BuildDeviceTopic("town-1", "DBIRTH", "rig-1", "power-si-1"), 2)
	assertPublishedDeviceTopic(t, node, sparkplug.BuildNodeTopic("town-1", "NBIRTH", "rig-1"), 2)
}

func TestNodeMQTTReconnectInRedconFourKeepsDevicesDisconnected(t *testing.T) {
	state := &runtimeState{cfg: rigconfig.Config{TownID: "town-1", RigID: "rig-1"}}
	state.setNodeRedcon(nodeRedconCommandable)
	node := &fakeNodeMQTTClient{}
	var options mqttx.Options
	state.newNodeMQTT = func(created mqttx.Options) (nodeMQTTClient, error) {
		options = created
		options.OnConnection()
		return node, nil
	}
	state.newDeviceMQTT = func(mqttx.Options) (managedMQTTClient, error) {
		t.Fatal("REDCON 4 must not create device MQTT sessions")
		return nil, nil
	}
	if err := state.connectNodeMQTT(context.Background()); err != nil {
		t.Fatal(err)
	}
	options.OnConnection()
	state.publishDeviceState(context.Background())
	state.publishDeviceState(context.Background())
	assertPublishedDeviceTopic(t, node, sparkplug.BuildNodeTopic("town-1", "NBIRTH", "rig-1"), 2)
	for _, subscription := range node.subscriptions {
		if subscription != sparkplug.BuildNodeCommandTopic("town-1", "rig-1") {
			t.Fatalf("REDCON 4 restored active subscription %s", subscription)
		}
	}
}

func TestDevicePublishFailuresRetryWithoutSessionChurn(t *testing.T) {
	for _, messageType := range []string{"DBIRTH", "DDATA", "DDEATH"} {
		t.Run(messageType, func(t *testing.T) {
			state, managed, client := newThreadPublicationState(t)
			if messageType != "DBIRTH" {
				state.publishDeviceState(context.Background())
				capabilities := map[string]bool{"sparkplug": true, "thread": true, "power": true}
				if messageType == "DDEATH" {
					capabilities = map[string]bool{"sparkplug": false, "thread": false, "power": false}
				}
				if err := managed.state.ObserveState(protocol.CapabilityState{
					SchemaVersion: protocol.SchemaVersion, AdapterID: "dev.txing.rig.ThreadConnectivity", ThingName: "power-si-1",
					Capabilities: capabilities, Metrics: map[string]protocol.MetricValue{}, ObservedAtMS: uint64(time.Now().UnixMilli()), Seq: 2,
				}); err != nil {
					t.Fatal(err)
				}
			}
			client.publishErr = errors.New("connection unavailable")
			state.publishDeviceState(context.Background())
			if managed.mqtt != client || client.disconnects != 0 {
				t.Fatal("failed publication must retain the existing MQTT client for retry")
			}
			client.publishErr = nil
			state.publishDeviceState(context.Background())
			state.publishDeviceState(context.Background())
			switch messageType {
			case "DBIRTH":
				assertPublishedDeviceTopic(t, client, sparkplug.BuildDeviceTopic("town-1", "DBIRTH", "rig-1", "power-si-1"), 1)
			case "DDATA":
				assertPublishedDeviceTopic(t, client, sparkplug.BuildDeviceTopic("town-1", "DBIRTH", "rig-1", "power-si-1"), 2)
				recovered, err := sparkplug.DecodePayload(client.publishes[1].payload)
				if err != nil {
					t.Fatal(err)
				}
				assertMetric(t, recovered.Metrics, sparkplug.NewBooleanMetric("capability.power", true))
			case "DDEATH":
				assertPublishedDeviceTopic(t, client, sparkplug.BuildDeviceTopic("town-1", "DDEATH", "rig-1", "power-si-1"), 1)
				if managed.mqtt != nil || client.disconnects != 1 {
					t.Fatal("successful death retry must disconnect the device exactly once")
				}
			}
		})
	}
}

func TestDeviceMQTTReconnectDoesNotReviveExpiredEvidence(t *testing.T) {
	state, managed, client := newThreadPublicationState(t)
	state.publishDeviceState(context.Background())
	if err := managed.state.ObserveState(protocol.CapabilityState{
		SchemaVersion: protocol.SchemaVersion, AdapterID: "dev.txing.rig.ThreadConnectivity", ThingName: "power-si-1",
		Capabilities: map[string]bool{"sparkplug": true, "thread": true, "power": false},
		Metrics:      map[string]protocol.MetricValue{}, ObservedAtMS: uint64(time.Now().UnixMilli()) - manager.StateTTLMS - 1000, Seq: 2,
	}); err != nil {
		t.Fatal(err)
	}
	oldSession := managed.mqttReconnect
	oldSession.onConnection()
	state.publishDeviceState(context.Background())
	oldSession.onConnection() // A delayed callback from the closed session is ignored.
	state.publishDeviceState(context.Background())
	assertPublishedDeviceTopic(t, client, sparkplug.BuildDeviceTopic("town-1", "DBIRTH", "rig-1", "power-si-1"), 1)
	assertPublishedDeviceTopic(t, client, sparkplug.BuildDeviceTopic("town-1", "DDEATH", "rig-1", "power-si-1"), 1)
	if managed.mqtt != nil || client.disconnects != 1 {
		t.Fatal("expired evidence must close the session despite a reconnect")
	}
}

func TestReconnectCallbacksCanRunDuringPublication(t *testing.T) {
	state, managed, client := newThreadPublicationState(t)
	state.publishDeviceState(context.Background())
	var callbacks sync.WaitGroup
	callbacks.Add(1)
	go func() {
		defer callbacks.Done()
		for range 100 {
			managed.mqttReconnect.onConnection()
		}
	}()
	for range 100 {
		state.publishDeviceState(context.Background())
	}
	callbacks.Wait()
	state.publishDeviceState(context.Background())
	if len(client.publishes) < 2 {
		t.Fatal("concurrent reconnects must cause a device rebirth")
	}
}

func newThreadPublicationState(t *testing.T) (*runtimeState, *managedDevice, *fakeNodeMQTTClient) {
	t.Helper()
	managed := &managedDevice{state: manager.NewDeviceRuntimeState(powerThreadInventory("power-si-1"))}
	client := &fakeNodeMQTTClient{}
	state := &runtimeState{
		cfg:     rigconfig.Config{TownID: "town-1", RigID: "rig-1"},
		devices: map[string]*managedDevice{"power-si-1": managed},
		newDeviceMQTT: func(options mqttx.Options) (managedMQTTClient, error) {
			options.OnConnection()
			return client, nil
		},
	}
	if err := managed.state.ObserveState(protocol.CapabilityState{
		SchemaVersion: protocol.SchemaVersion, AdapterID: "dev.txing.rig.ThreadConnectivity", ThingName: "power-si-1",
		Capabilities: map[string]bool{"sparkplug": true, "thread": true, "power": false},
		Metrics:      map[string]protocol.MetricValue{}, ObservedAtMS: uint64(time.Now().UnixMilli()), Seq: 1,
	}); err != nil {
		t.Fatal(err)
	}
	return state, managed, client
}

func TestOfflineDeviceSessionDoesNotInterruptOtherDeviceSession(t *testing.T) {
	firstInventory := powerBLEInventory("power-ble-1")
	secondInventory := powerThreadInventory("power-si-1")
	first := &managedDevice{state: manager.NewDeviceRuntimeState(firstInventory)}
	second := &managedDevice{state: manager.NewDeviceRuntimeState(secondInventory)}
	node := &fakeNodeMQTTClient{}
	state := &runtimeState{
		cfg:      rigconfig.Config{TownID: "town-1", RigID: "rig-1"},
		nodeMQTT: node,
		devices: map[string]*managedDevice{
			firstInventory.ThingName:  first,
			secondInventory.ThingName: second,
		},
	}
	clients := map[string]*fakeNodeMQTTClient{}
	state.newDeviceMQTT = func(options mqttx.Options) (managedMQTTClient, error) {
		client := &fakeNodeMQTTClient{}
		clients[options.ClientID] = client
		return client, nil
	}
	now := uint64(time.Now().UnixMilli())
	for _, observed := range []struct {
		managed      *managedDevice
		inventory    protocol.InventoryDevice
		adapterID    string
		capabilities map[string]bool
	}{
		{first, firstInventory, "dev.txing.rig.BleConnectivity", map[string]bool{"sparkplug": true, "ble": true, "power": true}},
		{second, secondInventory, "dev.txing.rig.ThreadConnectivity", map[string]bool{"sparkplug": true, "thread": true, "power": true}},
	} {
		if err := observed.managed.state.ObserveState(protocol.CapabilityState{
			SchemaVersion: protocol.SchemaVersion, AdapterID: observed.adapterID, ThingName: observed.inventory.ThingName,
			Capabilities: observed.capabilities, Metrics: map[string]protocol.MetricValue{}, ObservedAtMS: now, Seq: 1,
		}); err != nil {
			t.Fatal(err)
		}
	}
	state.publishDeviceState(context.Background())

	if err := first.state.ObserveState(protocol.CapabilityState{
		SchemaVersion: protocol.SchemaVersion, AdapterID: "dev.txing.rig.BleConnectivity", ThingName: firstInventory.ThingName,
		Capabilities: map[string]bool{"sparkplug": false, "ble": false, "power": false}, Metrics: map[string]protocol.MetricValue{}, ObservedAtMS: now + 1, Seq: 2,
	}); err != nil {
		t.Fatal(err)
	}
	state.publishDeviceState(context.Background())
	if clients[firstInventory.ThingName].disconnects != 1 || first.mqtt != nil {
		t.Fatalf("offline device session = %#v disconnects=%d", first.mqtt, clients[firstInventory.ThingName].disconnects)
	}
	if clients[secondInventory.ThingName].disconnects != 0 || second.mqtt != clients[secondInventory.ThingName] {
		t.Fatalf("unrelated device session was interrupted mqtt=%#v disconnects=%d", second.mqtt, clients[secondInventory.ThingName].disconnects)
	}
	if node.disconnects != 0 {
		t.Fatalf("rig node MQTT session was interrupted disconnects=%d", node.disconnects)
	}
}

func powerBLEInventory(thingName string) protocol.InventoryDevice {
	return protocol.InventoryDevice{
		ThingName: thingName, ThingType: "power", Capabilities: []string{"sparkplug", "ble", "power"},
		RedconCommandLevels: []uint8{4, 3}, RedconRules: map[uint8][]string{4: {"sparkplug", "ble"}, 3: {"sparkplug", "ble", "power"}},
	}
}

func powerThreadInventory(thingName string) protocol.InventoryDevice {
	return protocol.InventoryDevice{
		ThingName: thingName, ThingType: "power-si", Capabilities: []string{"sparkplug", "thread", "power"},
		RedconCommandLevels: []uint8{4, 3}, RedconRules: map[uint8][]string{4: {"sparkplug", "thread"}, 3: {"sparkplug", "thread", "power"}},
	}
}

func assertPublishedDeviceTopic(t *testing.T, client *fakeNodeMQTTClient, topic string, want int) {
	t.Helper()
	got := 0
	for _, publication := range client.publishes {
		if publication.topic == topic {
			got++
		}
	}
	if got != want {
		t.Fatalf("publications on %s = %d, want %d; all=%#v", topic, got, want, client.publishes)
	}
}

type fakeInventoryLoader struct {
	inventory registry.Inventory
	calls     int
}

func (f *fakeInventoryLoader) LoadInventory(context.Context, string) (registry.Inventory, error) {
	f.calls++
	return f.inventory, nil
}

type fakeIPCBroker struct {
	publishes []fakePublish
}

func (f *fakeIPCBroker) Publish(topic string, payload []byte, retain bool) {
	f.publishes = append(f.publishes, fakePublish{
		topic:    topic,
		payload:  append([]byte(nil), payload...),
		retained: retain,
	})
}

func testInventoryDevice(thingName string) protocol.InventoryDevice {
	return protocol.InventoryDevice{
		ThingName:           thingName,
		ThingType:           "unit",
		Capabilities:        []string{"sparkplug"},
		RedconCommandLevels: []uint8{1, 4},
		RedconRules:         map[uint8][]string{1: {"sparkplug"}},
	}
}

func TestRefreshInventoryPublishesOnlyOnChange(t *testing.T) {
	deviceOne := testInventoryDevice("unit-1")
	deviceTwo := testInventoryDevice("unit-2")
	loader := &fakeInventoryLoader{inventory: registry.Inventory{
		RigType: "raspi",
		Devices: []protocol.InventoryDevice{deviceOne, deviceTwo},
	}}
	broker := &fakeIPCBroker{}
	state := &runtimeState{
		cfg:      rigconfig.Config{TownID: "town-1", RigID: "rig-1"},
		broker:   broker,
		registry: loader,
		nodeMQTT: &fakeNodeMQTTClient{},
		devices: map[string]*managedDevice{
			"unit-1": {mqtt: &fakeNodeMQTTClient{}, state: manager.NewDeviceRuntimeState(deviceOne)},
			"unit-2": {mqtt: &fakeNodeMQTTClient{}, state: manager.NewDeviceRuntimeState(deviceTwo)},
		},
		boardStateSubscriptions: map[string]struct{}{},
	}

	if err := state.refreshInventory(context.Background()); err != nil {
		t.Fatal(err)
	}
	if len(broker.publishes) != 1 {
		t.Fatalf("publish count after first refresh = %d, want 1", len(broker.publishes))
	}
	if broker.publishes[0].topic != protocol.InventoryTopic || !broker.publishes[0].retained {
		t.Fatalf("publish = %#v, want retained %s", broker.publishes[0], protocol.InventoryTopic)
	}

	for range 3 {
		if err := state.refreshInventory(context.Background()); err != nil {
			t.Fatal(err)
		}
	}
	if len(broker.publishes) != 1 {
		t.Fatalf("publish count after unchanged refreshes = %d, want 1", len(broker.publishes))
	}

	loader.inventory = registry.Inventory{
		RigType: "raspi",
		Devices: []protocol.InventoryDevice{deviceOne},
	}
	if err := state.refreshInventory(context.Background()); err != nil {
		t.Fatal(err)
	}
	if len(broker.publishes) != 2 {
		t.Fatalf("publish count after device removal = %d, want 2", len(broker.publishes))
	}
	if _, ok := state.devices["unit-2"]; ok {
		t.Fatal("removed device should leave managed set")
	}

	decoded, err := protocol.DecodeInventory(broker.publishes[1].payload)
	if err != nil {
		t.Fatal(err)
	}
	if len(decoded.Devices) != 1 || decoded.Devices[0].ThingName != "unit-1" {
		t.Fatalf("published inventory devices = %#v, want only unit-1", decoded.Devices)
	}
	if decoded.Seq != 1 {
		t.Fatalf("published inventory seq = %d, want 1 (seq advances only on publish)", decoded.Seq)
	}
}

func redconCommandPayload(t *testing.T, redcon uint8, seq uint64) []byte {
	t.Helper()
	payload, err := sparkplug.EncodePayload(sparkplug.Payload{
		Timestamp: 1714380000000,
		Seq:       &seq,
		Metrics: []sparkplug.Metric{
			sparkplug.NewInt32Metric("redcon", int32(redcon)),
		},
	})
	if err != nil {
		t.Fatal(err)
	}
	return payload
}

func assertMetric(t *testing.T, metrics []sparkplug.Metric, want sparkplug.Metric) {
	t.Helper()
	for _, metric := range metrics {
		if metric == want {
			return
		}
	}
	t.Fatalf("missing metric %#v in %#v", want, metrics)
}
