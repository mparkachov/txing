package ble

import (
	"encoding/binary"
	"encoding/json"
	"testing"
)

func TestPowerPayloadRoundTripsCurrentProtocol(t *testing.T) {
	encoded, err := EncodeRedconCommand(1)
	if err != nil {
		t.Fatal(err)
	}
	assertBytes(t, encoded, []byte{2, 3})
	encoded, err = EncodeRedconCommand(4)
	if err != nil {
		t.Fatal(err)
	}
	assertBytes(t, encoded, []byte{2, 4})

	state, err := ParsePowerState([]byte{2, 4})
	if err != nil {
		t.Fatal(err)
	}
	if state.Redcon != 4 {
		t.Fatalf("state redcon = %d, want 4", state.Redcon)
	}

	measurement, err := ParsePowerMeasurement([]byte{2, 0x82, 0x0f})
	if err != nil {
		t.Fatal(err)
	}
	if measurement.BatteryMV == nil || *measurement.BatteryMV != 3970 {
		t.Fatalf("battery = %#v, want 3970", measurement.BatteryMV)
	}
}

func TestWeatherPayloadParsesStateAndMeasurement(t *testing.T) {
	state, err := ParseWeatherState([]byte{2, 4})
	if err != nil {
		t.Fatal(err)
	}
	if state.Redcon != 4 {
		t.Fatalf("state redcon = %d, want 4", state.Redcon)
	}
	if _, err := ParseWeatherState([]byte{2, 3}); err == nil {
		t.Fatal("expected weather REDCON 3 state to fail")
	}

	payload := []byte{2}
	payload = binary.LittleEndian.AppendUint32(payload, uint32(int32(2155)))
	payload = binary.LittleEndian.AppendUint32(payload, 101_325)
	payload = binary.LittleEndian.AppendUint16(payload, 4550)
	measurement, err := ParseWeatherMeasurement(payload)
	if err != nil {
		t.Fatal(err)
	}
	if measurement.MeasuredTemperature != 21.55 || measurement.MeasuredPressure != 101.325 || measurement.MeasuredHumidity != 45.5 {
		t.Fatalf("measurement = %#v", measurement)
	}
}

func TestOldVersionOnePayloadsAreRejected(t *testing.T) {
	if _, err := ParsePowerState([]byte{1, 3}); err == nil {
		t.Fatal("expected v1 power state to fail")
	}
	if _, err := ParsePowerMeasurement([]byte{1, 0x82, 0x0f}); err == nil {
		t.Fatal("expected v1 power measurement to fail")
	}
	payload := []byte{1}
	payload = binary.LittleEndian.AppendUint32(payload, uint32(int32(2155)))
	payload = binary.LittleEndian.AppendUint32(payload, 101_325)
	payload = binary.LittleEndian.AppendUint16(payload, 4550)
	if _, err := ParseWeatherMeasurement(payload); err == nil {
		t.Fatal("expected v1 weather measurement to fail")
	}
}

func TestSamplesMapToV2Capabilities(t *testing.T) {
	spec := DeviceSpec{ThingName: "power-1", Kind: DeviceKindPower}
	name := "power-1"
	rssi := int16(-50)
	advertisement := Advertisement{
		Address:      "AA:BB:CC:DD:EE:FF",
		IdentityName: &name,
		Services:     []string{TxingBLEServiceUUID},
		RSSI:         &rssi,
		ObservedAtMS: 42,
		Seq:          7,
	}
	sample := AdvertisementSample(spec, advertisement, 1)
	state := CapabilityStateFromSample(AdapterID, sample)

	if !state.Capabilities[SparkplugCapability] || !state.Capabilities[BLECapability] {
		t.Fatalf("expected sparkplug and BLE available: %#v", state.Capabilities)
	}
	if state.Capabilities[PowerCapability] {
		t.Fatalf("expected power unavailable from advertisement: %#v", state.Capabilities)
	}
	if len(state.Metrics) != 0 {
		t.Fatalf("expected no metrics, got %#v", state.Metrics)
	}

	offline := CapabilityStateFromSample(AdapterID, OfflineSample(spec, 2, 100))
	if offline.Capabilities[SparkplugCapability] {
		t.Fatalf("expected offline sparkplug false: %#v", offline.Capabilities)
	}
}

func TestAdvertisementSamplePublishesOnlyBleShadowWithoutMeasurements(t *testing.T) {
	spec := DeviceSpec{ThingName: "power-1", Kind: DeviceKindPower}
	name := "power-1"
	rssi := int16(-50)
	advertisement := Advertisement{
		Address:      "AA:BB:CC:DD:EE:FF",
		IdentityName: &name,
		Services:     []string{TxingBLEServiceUUID},
		RSSI:         &rssi,
		ObservedAtMS: 42,
		Seq:          7,
	}
	updates, err := ShadowUpdatesFromSample(AdvertisementSample(spec, advertisement, 1))
	if err != nil {
		t.Fatal(err)
	}
	if len(updates) != 1 {
		t.Fatalf("update count = %d, want 1", len(updates))
	}
	if updates[0].Topic != "$aws/things/power-1/shadow/name/ble/update" {
		t.Fatalf("topic = %s", updates[0].Topic)
	}
	payload := decodePayload(t, updates[0].Payload)
	reported := payload["state"].(map[string]any)["reported"].(map[string]any)
	if reported["bleAddress"] != "AA:BB:CC:DD:EE:FF" || reported["bleLocalName"] != "power-1" {
		t.Fatalf("reported = %#v", reported)
	}
	if reported["observedAtMs"] != nil || reported["seq"] != nil {
		t.Fatalf("reported timestamps should be null: %#v", reported)
	}
}

func TestWeatherAdvertisementSamplePublishesOnlyBleCapability(t *testing.T) {
	spec := DeviceSpec{ThingName: "weather-1", Kind: DeviceKindWeather}
	name := "weather-1"
	rssi := int16(-50)
	advertisement := Advertisement{
		Address:      "AA:BB:CC:DD:EE:FF",
		IdentityName: &name,
		Services:     []string{TxingBLEServiceUUID},
		RSSI:         &rssi,
		ObservedAtMS: 42,
		Seq:          7,
	}
	sample := AdvertisementSample(spec, advertisement, 1)
	state := CapabilityStateFromSample(AdapterID, sample)

	if sample.Redcon != nil {
		t.Fatalf("sample redcon = %#v", sample.Redcon)
	}
	for _, capability := range []string{SparkplugCapability, BLECapability} {
		if !state.Capabilities[capability] {
			t.Fatalf("capability %s false in %#v", capability, state.Capabilities)
		}
	}
	for _, capability := range []string{PowerCapability, WeatherCapability} {
		if state.Capabilities[capability] {
			t.Fatalf("capability %s true in %#v", capability, state.Capabilities)
		}
	}
	if len(state.Metrics) != 0 {
		t.Fatalf("expected no metrics, got %#v", state.Metrics)
	}
}

func TestPowerStateSamplePublishesPowerShadow(t *testing.T) {
	spec := DeviceSpec{ThingName: "power-1", Kind: DeviceKindPower}
	battery := uint16(3970)
	address := "AA:BB:CC:DD:EE:FF"
	sample := PowerStateSample(spec, RedconActive, &PowerMeasurement{BatteryMV: &battery}, &address, 3, 1000)
	updates, err := ShadowUpdatesFromSample(sample)
	if err != nil {
		t.Fatal(err)
	}
	if len(updates) != 2 {
		t.Fatalf("update count = %d, want 2", len(updates))
	}
	if updates[1].Topic != "$aws/things/power-1/shadow/name/power/update" {
		t.Fatalf("topic = %s", updates[1].Topic)
	}
	reported := decodePayload(t, updates[1].Payload)["state"].(map[string]any)["reported"].(map[string]any)
	if reported["batteryMv"].(float64) != 3970 {
		t.Fatalf("reported = %#v", reported)
	}
}

func TestActivePowerStateKeepsPowerCapabilityWithoutFreshBattery(t *testing.T) {
	spec := DeviceSpec{ThingName: "power-1", Kind: DeviceKindPower}
	sample := PowerStateSample(spec, RedconActive, nil, nil, 3, 1000)
	state := CapabilityStateFromSample(AdapterID, sample)

	if !state.Capabilities[PowerCapability] {
		t.Fatalf("expected power available: %#v", state.Capabilities)
	}
	if sample.BatteryMV != nil {
		t.Fatalf("battery = %#v, want nil", sample.BatteryMV)
	}
	updates, err := ShadowUpdatesFromSample(sample)
	if err != nil {
		t.Fatal(err)
	}
	if len(updates) != 1 || updates[0].Topic != "$aws/things/power-1/shadow/name/ble/update" {
		t.Fatalf("updates = %#v", updates)
	}
}

func TestWeatherStateSamplePublishesWeatherShadow(t *testing.T) {
	spec := DeviceSpec{ThingName: "weather-1", Kind: DeviceKindWeather}
	battery := uint16(3710)
	address := "AA:BB:CC:DD:EE:FF"
	weather := WeatherMeasurement{MeasuredTemperature: 21.625, MeasuredPressure: 100.8, MeasuredHumidity: 44.5}
	sample := WeatherStateSample(spec, RedconIdle, &PowerMeasurement{BatteryMV: &battery}, &weather, &address, 4, 2000)
	updates, err := ShadowUpdatesFromSample(sample)
	if err != nil {
		t.Fatal(err)
	}
	if len(updates) != 3 {
		t.Fatalf("update count = %d, want 3", len(updates))
	}
	if updates[1].Topic != "$aws/things/weather-1/shadow/name/power/update" {
		t.Fatalf("power topic = %s", updates[1].Topic)
	}
	powerReported := decodePayload(t, updates[1].Payload)["state"].(map[string]any)["reported"].(map[string]any)
	if powerReported["batteryMv"].(float64) != 3710 {
		t.Fatalf("power reported = %#v", powerReported)
	}
	if updates[2].Topic != "$aws/things/weather-1/shadow/name/weather/update" {
		t.Fatalf("weather topic = %s", updates[2].Topic)
	}
	weatherReported := decodePayload(t, updates[2].Payload)["state"].(map[string]any)["reported"].(map[string]any)
	if _, ok := weatherReported["batteryMv"]; ok {
		t.Fatalf("weather reported must not contain batteryMv: %#v", weatherReported)
	}
	if weatherReported["measuredTemperature"].(float64) != 21.625 ||
		weatherReported["measuredPressure"].(float64) != 100.8 ||
		weatherReported["measuredHumidity"].(float64) != 44.5 {
		t.Fatalf("weather reported = %#v", weatherReported)
	}
}

func TestWeatherStateKeepsCapabilitiesAvailableWithoutFreshMeasurements(t *testing.T) {
	spec := DeviceSpec{ThingName: "weather-1", Kind: DeviceKindWeather}
	address := "AA:BB:CC:DD:EE:FF"
	sample := WeatherStateSample(spec, RedconIdle, nil, nil, &address, 5, 3000)
	state := CapabilityStateFromSample(AdapterID, sample)

	for _, capability := range []string{SparkplugCapability, BLECapability, PowerCapability, WeatherCapability} {
		if !state.Capabilities[capability] {
			t.Fatalf("capability %s false in %#v", capability, state.Capabilities)
		}
	}
	updates, err := ShadowUpdatesFromSample(sample)
	if err != nil {
		t.Fatal(err)
	}
	if len(updates) != 1 || updates[0].Topic != "$aws/things/weather-1/shadow/name/ble/update" {
		t.Fatalf("updates = %#v", updates)
	}
}

func assertBytes(t *testing.T, got []byte, want []byte) {
	t.Helper()
	if len(got) != len(want) {
		t.Fatalf("len(got) = %d, want %d", len(got), len(want))
	}
	for index := range want {
		if got[index] != want[index] {
			t.Fatalf("got[%d] = %d, want %d; got=%v want=%v", index, got[index], want[index], got, want)
		}
	}
}

func decodePayload(t *testing.T, payload []byte) map[string]any {
	t.Helper()
	var decoded map[string]any
	if err := json.Unmarshal(payload, &decoded); err != nil {
		t.Fatal(err)
	}
	return decoded
}
