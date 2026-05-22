package sparkplug

import "testing"

func TestRedconCommandRoundTrips(t *testing.T) {
	payload, err := BuildRedconPayload(3, 9, 1714380000000)
	if err != nil {
		t.Fatal(err)
	}

	decoded, err := DecodeRedconCommand(payload)
	if err != nil {
		t.Fatal(err)
	}
	if decoded == nil {
		t.Fatal("expected decoded command")
	}
	if decoded.Value != 3 {
		t.Fatalf("decoded value = %d, want 3", decoded.Value)
	}
	if decoded.Seq == nil || *decoded.Seq != 9 {
		t.Fatalf("decoded seq = %#v, want 9", decoded.Seq)
	}
	if decoded.Timestamp == nil || *decoded.Timestamp != 1714380000000 {
		t.Fatalf("decoded timestamp = %#v, want 1714380000000", decoded.Timestamp)
	}
}

func TestDeviceReportSupportsTypedMetrics(t *testing.T) {
	payload, err := BuildDeviceReportPayload(
		4,
		10,
		1714380000001,
		[]Metric{
			NewInt32Metric("batteryMv", 3970),
			NewDoubleMetric("measuredTemperature", 21.625),
			NewBooleanMetric("commands/cmd-1/succeeded", true),
			NewStringMetric("commands/cmd-1/status", "succeeded"),
		},
	)
	if err != nil {
		t.Fatal(err)
	}

	decoded, err := DecodePayload(payload)
	if err != nil {
		t.Fatal(err)
	}
	if decoded.Seq == nil || *decoded.Seq != 10 {
		t.Fatalf("seq = %#v, want 10", decoded.Seq)
	}
	want := []Metric{
		NewInt32Metric("redcon", 4),
		NewInt32Metric("batteryMv", 3970),
		NewDoubleMetric("measuredTemperature", 21.625),
		NewBooleanMetric("commands/cmd-1/succeeded", true),
		NewStringMetric("commands/cmd-1/status", "succeeded"),
	}
	if len(decoded.Metrics) != len(want) {
		t.Fatalf("decoded metric count = %d, want %d", len(decoded.Metrics), len(want))
	}
	for index := range want {
		if decoded.Metrics[index] != want[index] {
			t.Fatalf("metric %d = %#v, want %#v", index, decoded.Metrics[index], want[index])
		}
	}
}
