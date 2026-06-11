package main

import (
	"context"
	"reflect"
	"testing"

	"github.com/mparkachov/txing/rig/internal/mqttx"
	"github.com/mparkachov/txing/rig/internal/rigconfig"
	"github.com/mparkachov/txing/rig/internal/sparkplug"
)

type fakeNodeMQTTClient struct {
	subscriptions []string
	unsubscribes  []string
	publishes     []fakePublish
	disconnects   int
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
