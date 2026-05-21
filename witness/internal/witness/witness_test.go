package witness

import (
	"context"
	"encoding/base64"
	"encoding/binary"
	"math"
	"reflect"
	"strings"
	"testing"
)

type fakeAWS struct {
	things    map[string]ThingDescription
	shadow    map[string]any
	getErr    error
	updateErr error
	updates   []witnessUpdate
}

type witnessUpdate struct {
	thingName string
	payload   map[string]any
}

func (f *fakeAWS) DescribeThing(_ context.Context, thingName string) (ThingDescription, error) {
	thing, ok := f.things[thingName]
	if !ok {
		return ThingDescription{}, errString("unexpected thing: " + thingName)
	}
	return thing, nil
}

func (f *fakeAWS) GetSparkplugShadow(context.Context, string) (map[string]any, bool, error) {
	if f.getErr != nil {
		return nil, false, f.getErr
	}
	if f.shadow == nil {
		return nil, false, nil
	}
	return f.shadow, true, nil
}

func (f *fakeAWS) UpdateSparkplugShadow(_ context.Context, thingName string, payload map[string]any) error {
	if f.updateErr != nil {
		return f.updateErr
	}
	f.updates = append(f.updates, witnessUpdate{thingName: thingName, payload: payload})
	return nil
}

type errString string

func (e errString) Error() string { return string(e) }

func encodeVarint(value uint64) []byte {
	var out []byte
	for {
		next := byte(value & 0x7f)
		value >>= 7
		if value != 0 {
			out = append(out, next|0x80)
		} else {
			return append(out, next)
		}
	}
}

func encodeKey(field, wire uint64) []byte {
	return encodeVarint((field << 3) | wire)
}

func encodeLengthDelimited(field uint64, payload []byte) []byte {
	out := encodeKey(field, 2)
	out = append(out, encodeVarint(uint64(len(payload)))...)
	out = append(out, payload...)
	return out
}

func encodeMetric(name string, intValue *int64, longValue *int64, doubleValue *float64, boolValue *bool, stringValue *string, canonical bool) []byte {
	var out []byte
	out = append(out, encodeLengthDelimited(1, []byte(name))...)
	if intValue != nil {
		out = append(out, encodeKey(10, 0)...)
		out = append(out, encodeVarint(uint64(*intValue))...)
	}
	if longValue != nil {
		out = append(out, encodeKey(11, 0)...)
		out = append(out, encodeVarint(uint64(*longValue))...)
	}
	if doubleValue != nil {
		out = append(out, encodeKey(13, 1)...)
		var bytes [8]byte
		binary.LittleEndian.PutUint64(bytes[:], math.Float64bits(*doubleValue))
		out = append(out, bytes[:]...)
	}
	if boolValue != nil {
		field := uint64(12)
		if canonical {
			field = 14
		}
		out = append(out, encodeKey(field, 0)...)
		if *boolValue {
			out = append(out, 1)
		} else {
			out = append(out, 0)
		}
	}
	if stringValue != nil {
		field := uint64(13)
		if canonical {
			field = 15
		}
		out = append(out, encodeLengthDelimited(field, []byte(*stringValue))...)
	}
	return out
}

func encodePayload(timestamp *int64, seq *int64, metrics ...[]byte) string {
	var out []byte
	if timestamp != nil {
		out = append(out, encodeKey(1, 0)...)
		out = append(out, encodeVarint(uint64(*timestamp))...)
	}
	for _, metric := range metrics {
		out = append(out, encodeLengthDelimited(2, metric)...)
	}
	if seq != nil {
		out = append(out, encodeKey(3, 0)...)
		out = append(out, encodeVarint(uint64(*seq))...)
	}
	return base64.StdEncoding.EncodeToString(out)
}

func ptr[T any](value T) *T { return &value }

func TestDecodeDeviceBirthProjectsNestedMetrics(t *testing.T) {
	payload := encodePayload(
		ptr(int64(1710000000000)),
		ptr(int64(7)),
		encodeMetric("redcon", ptr(int64(1)), nil, nil, nil, nil, false),
		encodeMetric("batteryMv", ptr(int64(3795)), nil, nil, nil, nil, false),
		encodeMetric("services/demo/available", nil, nil, nil, ptr(true), nil, false),
	)
	message, ok := DecodeSparkplugPayload(payload, "spBv1.0/town/DBIRTH/rig/unit-1")
	if !ok {
		t.Fatal("expected decoded message")
	}
	if message.DeviceID == nil || *message.DeviceID != "unit-1" || message.MessageType != "DBIRTH" {
		t.Fatalf("unexpected message identity: %+v", message)
	}
	want := map[string]any{
		"redcon":    int64(1),
		"batteryMv": int64(3795),
		"services":  map[string]any{"demo": map[string]any{"available": true}},
	}
	if !reflect.DeepEqual(message.Metrics, want) {
		t.Fatalf("metrics = %#v, want %#v", message.Metrics, want)
	}
}

func TestDecodeWeatherDoubleAndCanonicalBoolMetrics(t *testing.T) {
	payload := encodePayload(
		ptr(int64(1710000000000)),
		ptr(int64(7)),
		encodeMetric("redcon", ptr(int64(4)), nil, nil, nil, nil, false),
		encodeMetric("measuredTemperature", nil, nil, ptr(21.625), nil, nil, false),
		encodeMetric("services/demo/available", nil, nil, nil, ptr(true), nil, true),
	)
	message, ok := DecodeSparkplugPayload(payload, "spBv1.0/town/DBIRTH/rig/weather-1")
	if !ok {
		t.Fatal("expected decoded message")
	}
	if message.Metrics["redcon"] != int64(4) || message.Metrics["measuredTemperature"] != 21.625 {
		t.Fatalf("bad weather metrics: %#v", message.Metrics)
	}
	services := message.Metrics["services"].(map[string]any)
	if services["demo"].(map[string]any)["available"] != true {
		t.Fatalf("bad canonical bool metric: %#v", message.Metrics)
	}
}

func TestRejectsInvalidTopicArityAndMessagePairings(t *testing.T) {
	payload := encodePayload(nil, nil)
	for _, topic := range []string{
		"spBv1.0/town/DBIRTH/rig",
		"spBv1.0/town/NBIRTH/rig/unit-1",
		"spBv1.0/town//rig",
	} {
		if _, ok := DecodeSparkplugPayload(payload, topic); ok {
			t.Fatalf("expected topic %q to be rejected", topic)
		}
	}
}

func TestProjectDeviceBirthReplacesMetrics(t *testing.T) {
	aws := &fakeAWS{}
	payload := encodePayload(
		ptr(int64(1710000000000)),
		ptr(int64(7)),
		encodeMetric("redcon", ptr(int64(1)), nil, nil, nil, nil, false),
		encodeMetric("batteryMv", ptr(int64(3795)), nil, nil, nil, nil, false),
	)
	message, _ := DecodeSparkplugPayload(payload, "spBv1.0/town/DBIRTH/rig/unit-1")
	projected, err := ProjectSparkplugMessage(context.Background(), message, 1710000000999, aws)
	if err != nil {
		t.Fatal(err)
	}
	if projected != "unit-1" {
		t.Fatalf("projected %q", projected)
	}
	if len(aws.updates) != 2 {
		t.Fatalf("updates = %d", len(aws.updates))
	}
	if aws.updates[0].payload["state"].(map[string]any)["reported"].(map[string]any)["payload"].(map[string]any)["metrics"] != nil {
		t.Fatalf("first update did not clear metrics")
	}
}

func TestProjectDeviceDataSkipsShadowUpdateWhenUnchanged(t *testing.T) {
	aws := &fakeAWS{shadow: map[string]any{"state": map[string]any{"reported": map[string]any{"payload": map[string]any{"metrics": map[string]any{"redcon": float64(4)}}}}}}
	payload := encodePayload(ptr(int64(1710000030000)), ptr(int64(8)), encodeMetric("redcon", ptr(int64(4)), nil, nil, nil, nil, false))
	message, _ := DecodeSparkplugPayload(payload, "spBv1.0/town/DDATA/rig/weather-1")
	projected, err := ProjectSparkplugMessage(context.Background(), message, 1710000030999, aws)
	if err != nil {
		t.Fatal(err)
	}
	if projected != "weather-1" || len(aws.updates) != 0 {
		t.Fatalf("projected=%q updates=%d", projected, len(aws.updates))
	}
}

func TestProjectDeviceDataUpdatesShadowWhenMetricChanges(t *testing.T) {
	aws := &fakeAWS{shadow: map[string]any{"state": map[string]any{"reported": map[string]any{"payload": map[string]any{"metrics": map[string]any{"redcon": float64(4)}}}}}}
	payload := encodePayload(ptr(int64(1710000030000)), ptr(int64(8)), encodeMetric("redcon", ptr(int64(3)), nil, nil, nil, nil, false))
	message, _ := DecodeSparkplugPayload(payload, "spBv1.0/town/DDATA/rig/weather-1")
	if _, err := ProjectSparkplugMessage(context.Background(), message, 1710000030999, aws); err != nil {
		t.Fatal(err)
	}
	if len(aws.updates) != 1 {
		t.Fatalf("updates = %d", len(aws.updates))
	}
	metrics := aws.updates[0].payload["state"].(map[string]any)["reported"].(map[string]any)["payload"].(map[string]any)["metrics"].(map[string]any)
	if metrics["redcon"] != int64(3) {
		t.Fatalf("bad update metrics: %#v", metrics)
	}
}

func TestProjectDeviceDataPropagatesShadowReadErrors(t *testing.T) {
	aws := &fakeAWS{getErr: errString("shadow read failed")}
	payload := encodePayload(ptr(int64(1710000030000)), ptr(int64(8)), encodeMetric("redcon", ptr(int64(4)), nil, nil, nil, nil, false))
	message, _ := DecodeSparkplugPayload(payload, "spBv1.0/town/DDATA/rig/weather-1")
	if _, err := ProjectSparkplugMessage(context.Background(), message, 1710000030999, aws); err == nil {
		t.Fatal("expected shadow read error")
	}
}

func TestProjectCommandResultClearsLegacyCommandsMap(t *testing.T) {
	aws := &fakeAWS{shadow: map[string]any{"state": map[string]any{"reported": map[string]any{"payload": map[string]any{"metrics": map[string]any{"commands": map[string]any{"old": true}, "redconCommandMessage": "old"}}}}}}
	status := "succeeded"
	id := "dcmd-cloud-mcu-2"
	payload := encodePayload(
		ptr(int64(1710000040000)),
		ptr(int64(9)),
		encodeMetric("redconCommandStatus", nil, nil, nil, nil, &status, false),
		encodeMetric("redconCommandSeq", ptr(int64(2)), nil, nil, nil, nil, false),
		encodeMetric("redconCommandId", nil, nil, nil, nil, &id, false),
		encodeMetric("redconCommandTarget", ptr(int64(4)), nil, nil, nil, nil, false),
	)
	message, _ := DecodeSparkplugPayload(payload, "spBv1.0/town/DDATA/rig/cloud-mcu-1")
	if _, err := ProjectSparkplugMessage(context.Background(), message, 1710000040999, aws); err != nil {
		t.Fatal(err)
	}
	metrics := aws.updates[0].payload["state"].(map[string]any)["reported"].(map[string]any)["payload"].(map[string]any)["metrics"].(map[string]any)
	if metrics["commands"] != nil || metrics["redconCommandMessage"] != nil {
		t.Fatalf("legacy command fields not cleared: %#v", metrics)
	}
}

func TestResolveNodeMessageAcceptsCurrentRigTypeModel(t *testing.T) {
	townType := "town"
	cloudType := "cloud"
	aws := &fakeAWS{things: map[string]ThingDescription{
		"town-1":  {ThingTypeName: &townType, Attributes: map[string]string{"kind": "townType"}},
		"cloud-1": {ThingTypeName: &cloudType, Attributes: map[string]string{"kind": "rigType", "townId": "town-1"}},
	}}
	payload := encodePayload(ptr(int64(1710000000000)), ptr(int64(7)), encodeMetric("redcon", ptr(int64(1)), nil, nil, nil, nil, false))
	message, _ := DecodeSparkplugPayload(payload, "spBv1.0/town-1/NBIRTH/cloud-1")
	name, err := ResolveThingName(context.Background(), message, aws)
	if err != nil {
		t.Fatal(err)
	}
	if name != "cloud-1" {
		t.Fatalf("name = %q", name)
	}
}

func TestResolveNodeMessageRejectsNonRigKind(t *testing.T) {
	townType := "town"
	unitType := "unit"
	aws := &fakeAWS{things: map[string]ThingDescription{
		"town-1": {ThingTypeName: &townType, Attributes: map[string]string{}},
		"unit-1": {ThingTypeName: &unitType, Attributes: map[string]string{
			"kind":   "deviceType",
			"townId": "town-1",
		}},
	}}
	payload := encodePayload(ptr(int64(1710000000000)), ptr(int64(7)), encodeMetric("redcon", ptr(int64(1)), nil, nil, nil, nil, false))
	message, _ := DecodeSparkplugPayload(payload, "spBv1.0/town-1/NBIRTH/unit-1")
	_, err := ResolveThingName(context.Background(), message, aws)
	if err == nil || !strings.Contains(err.Error(), "does not identify a rig thing") {
		t.Fatalf("expected non-rig error, got %v", err)
	}
}

func TestProjectNodeDeathReplacesMetricsWithDeathPayload(t *testing.T) {
	townType := "town"
	cloudType := "cloud"
	aws := &fakeAWS{things: map[string]ThingDescription{
		"town": {ThingTypeName: &townType, Attributes: map[string]string{}},
		"rig": {ThingTypeName: &cloudType, Attributes: map[string]string{
			"kind":   "rigType",
			"townId": "town",
		}},
	}}
	payload := encodePayload(
		nil,
		nil,
		encodeMetric("bdSeq", nil, ptr(int64(42)), nil, nil, nil, false),
		encodeMetric("redcon", ptr(int64(4)), nil, nil, nil, nil, false),
	)
	message, _ := DecodeSparkplugPayload(payload, "spBv1.0/town/NDEATH/rig")
	if _, err := ProjectSparkplugMessage(context.Background(), message, 1710000003999, aws); err != nil {
		t.Fatal(err)
	}
	if len(aws.updates) != 2 {
		t.Fatalf("updates = %d", len(aws.updates))
	}
	reported := aws.updates[1].payload["state"].(map[string]any)["reported"].(map[string]any)
	payloadObject := reported["payload"].(map[string]any)
	if payloadObject["timestamp"] != nil || payloadObject["seq"] != nil {
		t.Fatalf("expected death payload null timestamp and seq: %#v", payloadObject)
	}
	metrics := payloadObject["metrics"].(map[string]any)
	if metrics["bdSeq"] != int64(42) || metrics["redcon"] != int64(4) {
		t.Fatalf("bad death metrics: %#v", metrics)
	}
}

func TestLambdaHandlerIgnoresUnsupportedTopics(t *testing.T) {
	result, err := HandleLambdaEvent(context.Background(), map[string]any{
		"mqttTopic":     "txings/unit-1/video/status",
		"payloadBase64": "",
		"observedAt":    int64(123),
	}, &fakeAWS{})
	if err != nil {
		t.Fatal(err)
	}
	if result["status"] != "ignored" || result["reason"] != "unsupported-topic" {
		t.Fatalf("result = %#v", result)
	}
}
