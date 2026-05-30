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
	publishes     []fakePublish
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

func (f *fakeNodeMQTTClient) Publish(topic string, payload []byte, retained bool) error {
	f.publishes = append(f.publishes, fakePublish{
		topic:    topic,
		payload:  append([]byte(nil), payload...),
		retained: retained,
	})
	return nil
}

func (f *fakeNodeMQTTClient) Disconnect(uint) {}

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

func assertMetric(t *testing.T, metrics []sparkplug.Metric, want sparkplug.Metric) {
	t.Helper()
	for _, metric := range metrics {
		if metric == want {
			return
		}
	}
	t.Fatalf("missing metric %#v in %#v", want, metrics)
}
