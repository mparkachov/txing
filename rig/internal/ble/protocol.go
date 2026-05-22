package ble

import (
	"encoding/binary"
	"encoding/json"
	"fmt"
	"time"

	"github.com/mparkachov/txing/rig/internal/protocol"
)

const (
	AdapterID = "dev.txing.rig.BleConnectivity"

	SparkplugCapability = "sparkplug"
	BLECapability       = "ble"
	PowerCapability     = "power"
	WeatherCapability   = "weather"

	BLEShadowName     = "ble"
	PowerShadowName   = "power"
	WeatherShadowName = "weather"

	ProtocolVersion = uint8(2)
	RedconActive    = uint8(3)
	RedconIdle      = uint8(4)

	TxingBLEServiceUUID    = "f6b4b000-7b32-4d2d-9f4b-4ff0a2b8f100"
	TxingBLECommandUUID    = "f6b4b001-7b32-4d2d-9f4b-4ff0a2b8f100"
	TxingBLEStateUUID      = "f6b4b002-7b32-4d2d-9f4b-4ff0a2b8f100"
	PowerMeasurementUUID   = "f6b4b003-7b32-4d2d-9f4b-4ff0a2b8f100"
	WeatherMeasurementUUID = "f6b4b004-7b32-4d2d-9f4b-4ff0a2b8f100"
)

type DeviceKind int

const (
	DeviceKindPower DeviceKind = iota
	DeviceKindWeather
)

func (k DeviceKind) SupportsPower() bool {
	return true
}

func (k DeviceKind) SupportsWeather() bool {
	return k == DeviceKindWeather
}

func (k DeviceKind) PrimaryCapability() string {
	if k == DeviceKindWeather {
		return WeatherCapability
	}
	return PowerCapability
}

type DeviceSpec struct {
	ThingName string
	Kind      DeviceKind
}

type Advertisement struct {
	Address      string
	IdentityName *string
	Services     []string
	RSSI         *int16
	ObservedAtMS uint64
	Seq          uint64
}

func (a Advertisement) MatchesThing(thingName string) bool {
	return a.IdentityName != nil && *a.IdentityName == thingName
}

func (a Advertisement) HasTxingService() bool {
	for _, service := range a.Services {
		if service == TxingBLEServiceUUID {
			return true
		}
	}
	return false
}

type PowerState struct {
	Redcon uint8
}

type WeatherState struct {
	Redcon uint8
}

type PowerMeasurement struct {
	BatteryMV *uint16
}

type WeatherMeasurement struct {
	MeasuredTemperature float64
	MeasuredPressure    float64
	MeasuredHumidity    float64
}

type CapabilitySample struct {
	ThingName          string
	Kind               DeviceKind
	Redcon             *uint8
	SparkplugAvailable bool
	BLEAvailable       bool
	PowerAvailable     bool
	WeatherAvailable   bool
	BLELocalName       *string
	BLEAddress         *string
	BatteryMV          *uint16
	Weather            *WeatherMeasurement
	ObservedAtMS       uint64
	Seq                uint64
}

type ShadowUpdate struct {
	Topic   string
	Payload []byte
}

func EncodeRedconCommand(targetRedcon uint8) ([]byte, error) {
	normalized, err := protocol.NormalizeBleTargetRedcon(targetRedcon)
	if err != nil {
		return nil, err
	}
	return []byte{ProtocolVersion, normalized}, nil
}

func ParsePowerState(payload []byte) (PowerState, error) {
	if len(payload) != 2 {
		return PowerState{}, fmt.Errorf("power BLE state report length must be 2, got %d", len(payload))
	}
	if payload[0] != ProtocolVersion {
		return PowerState{}, fmt.Errorf("unsupported power BLE state version %d", payload[0])
	}
	redcon, err := normalizeStateRedcon(payload[1], "power")
	if err != nil {
		return PowerState{}, err
	}
	return PowerState{Redcon: redcon}, nil
}

func ParseWeatherState(payload []byte) (WeatherState, error) {
	if len(payload) != 2 {
		return WeatherState{}, fmt.Errorf("weather BLE state report length must be 2, got %d", len(payload))
	}
	if payload[0] != ProtocolVersion {
		return WeatherState{}, fmt.Errorf("unsupported weather BLE state version %d", payload[0])
	}
	redcon := payload[1]
	if redcon != RedconIdle {
		return WeatherState{}, fmt.Errorf("weather BLE state must be REDCON 4, got %d", redcon)
	}
	return WeatherState{Redcon: redcon}, nil
}

func ParsePowerMeasurement(payload []byte) (PowerMeasurement, error) {
	if len(payload) != 3 {
		return PowerMeasurement{}, fmt.Errorf("power BLE measurement report length must be 3, got %d", len(payload))
	}
	if payload[0] != ProtocolVersion {
		return PowerMeasurement{}, fmt.Errorf("unsupported power BLE measurement version %d", payload[0])
	}
	batteryMV := binary.LittleEndian.Uint16(payload[1:3])
	return PowerMeasurement{BatteryMV: nonzeroBattery(batteryMV)}, nil
}

func ParseWeatherMeasurement(payload []byte) (WeatherMeasurement, error) {
	if len(payload) != 11 {
		return WeatherMeasurement{}, fmt.Errorf("weather BLE measurement report length must be 11, got %d", len(payload))
	}
	if payload[0] != ProtocolVersion {
		return WeatherMeasurement{}, fmt.Errorf("unsupported weather BLE measurement version %d", payload[0])
	}
	temperatureCenti := int32(binary.LittleEndian.Uint32(payload[1:5]))
	pressurePa := binary.LittleEndian.Uint32(payload[5:9])
	humidityCenti := binary.LittleEndian.Uint16(payload[9:11])
	return WeatherMeasurement{
		MeasuredTemperature: float64(temperatureCenti) / 100.0,
		MeasuredPressure:    float64(pressurePa) / 1000.0,
		MeasuredHumidity:    float64(humidityCenti) / 100.0,
	}, nil
}

func AdvertisementSample(spec DeviceSpec, advertisement Advertisement, seq uint64) CapabilitySample {
	var redcon *uint8
	if spec.Kind.SupportsWeather() {
		value := RedconIdle
		redcon = &value
	}
	weatherDomainAvailable := spec.Kind.SupportsWeather()
	return CapabilitySample{
		ThingName:          spec.ThingName,
		Kind:               spec.Kind,
		Redcon:             redcon,
		SparkplugAvailable: true,
		BLEAvailable:       true,
		PowerAvailable:     weatherDomainAvailable,
		WeatherAvailable:   weatherDomainAvailable,
		BLELocalName:       advertisement.IdentityName,
		BLEAddress:         stringPtr(advertisement.Address),
		ObservedAtMS:       advertisement.ObservedAtMS,
		Seq:                seq,
	}
}

func OfflineSample(spec DeviceSpec, seq uint64, nowMS uint64) CapabilitySample {
	return CapabilitySample{
		ThingName:    spec.ThingName,
		Kind:         spec.Kind,
		ObservedAtMS: nowMS,
		Seq:          seq,
	}
}

func PowerStateSample(spec DeviceSpec, redcon uint8, measurement *PowerMeasurement, bleAddress *string, seq uint64, nowMS uint64) CapabilitySample {
	var batteryMV *uint16
	if measurement != nil {
		batteryMV = measurement.BatteryMV
	}
	return CapabilitySample{
		ThingName:          spec.ThingName,
		Kind:               DeviceKindPower,
		Redcon:             &redcon,
		SparkplugAvailable: true,
		BLEAvailable:       true,
		PowerAvailable:     redcon < RedconIdle,
		BLELocalName:       stringPtr(spec.ThingName),
		BLEAddress:         bleAddress,
		BatteryMV:          batteryMV,
		ObservedAtMS:       nowMS,
		Seq:                seq,
	}
}

func WeatherStateSample(spec DeviceSpec, redcon uint8, powerMeasurement *PowerMeasurement, weatherMeasurement *WeatherMeasurement, bleAddress *string, seq uint64, nowMS uint64) CapabilitySample {
	var batteryMV *uint16
	if powerMeasurement != nil {
		batteryMV = powerMeasurement.BatteryMV
	}
	return CapabilitySample{
		ThingName:          spec.ThingName,
		Kind:               DeviceKindWeather,
		Redcon:             &redcon,
		SparkplugAvailable: true,
		BLEAvailable:       true,
		PowerAvailable:     redcon == RedconIdle,
		WeatherAvailable:   redcon == RedconIdle,
		BLELocalName:       stringPtr(spec.ThingName),
		BLEAddress:         bleAddress,
		BatteryMV:          batteryMV,
		Weather:            weatherMeasurement,
		ObservedAtMS:       nowMS,
		Seq:                seq,
	}
}

func CapabilityStateFromSample(adapterID string, sample CapabilitySample) protocol.CapabilityState {
	capabilities := map[string]bool{
		SparkplugCapability: sample.SparkplugAvailable,
		BLECapability:       sample.BLEAvailable,
	}
	if sample.Kind.SupportsPower() {
		capabilities[PowerCapability] = sample.PowerAvailable
	}
	if sample.Kind.SupportsWeather() {
		capabilities[WeatherCapability] = sample.WeatherAvailable
	}
	metrics := map[string]protocol.MetricValue{}
	if sample.Redcon != nil {
		metrics[protocol.BleRedconMetric] = protocol.MetricInt32(int32(*sample.Redcon))
	}
	return protocol.CapabilityState{
		SchemaVersion: protocol.SchemaVersion,
		AdapterID:     adapterID,
		ThingName:     sample.ThingName,
		Capabilities:  capabilities,
		Metrics:       metrics,
		ObservedAtMS:  sample.ObservedAtMS,
		Seq:           sample.Seq,
	}
}

func ShadowUpdatesFromSample(sample CapabilitySample) ([]ShadowUpdate, error) {
	updates := []ShadowUpdate{}
	bleUpdate, err := BuildShadowUpdate(sample.ThingName, BLEShadowName, map[string]any{
		"bleAddress":   optionalString(sample.BLEAddress),
		"bleLocalName": optionalString(sample.BLELocalName),
		"observedAtMs": nil,
		"seq":          nil,
	})
	if err != nil {
		return nil, err
	}
	updates = append(updates, bleUpdate)

	if sample.Kind.SupportsPower() && sample.BatteryMV != nil {
		powerUpdate, err := BuildShadowUpdate(sample.ThingName, PowerShadowName, map[string]any{
			"batteryMv":    int(*sample.BatteryMV),
			"observedAtMs": nil,
			"seq":          nil,
		})
		if err != nil {
			return nil, err
		}
		updates = append(updates, powerUpdate)
	}

	if sample.Kind.SupportsWeather() && sample.Weather != nil {
		weatherUpdate, err := BuildShadowUpdate(sample.ThingName, WeatherShadowName, map[string]any{
			"measuredTemperature": sample.Weather.MeasuredTemperature,
			"measuredPressure":    sample.Weather.MeasuredPressure,
			"measuredHumidity":    sample.Weather.MeasuredHumidity,
			"observedAtMs":        nil,
			"seq":                 nil,
		})
		if err != nil {
			return nil, err
		}
		updates = append(updates, weatherUpdate)
	}
	return updates, nil
}

func BuildShadowUpdate(thingName string, shadowName string, reported map[string]any) (ShadowUpdate, error) {
	if err := protocol.ValidateSegment(thingName, "thingName"); err != nil {
		return ShadowUpdate{}, err
	}
	if err := protocol.ValidateSegment(shadowName, "shadowName"); err != nil {
		return ShadowUpdate{}, err
	}
	payload, err := json.Marshal(map[string]any{
		"state": map[string]any{"reported": reported},
	})
	if err != nil {
		return ShadowUpdate{}, err
	}
	return ShadowUpdate{
		Topic:   fmt.Sprintf("$aws/things/%s/shadow/name/%s/update", thingName, shadowName),
		Payload: payload,
	}, nil
}

func NowMS() uint64 {
	return uint64(time.Now().UnixMilli())
}

func normalizeStateRedcon(redcon uint8, label string) (uint8, error) {
	switch redcon {
	case 1, 2:
		return RedconActive, nil
	case RedconActive, RedconIdle:
		return redcon, nil
	default:
		return 0, fmt.Errorf("unsupported %s BLE state REDCON %d", label, redcon)
	}
}

func nonzeroBattery(value uint16) *uint16 {
	if value == 0 {
		return nil
	}
	return &value
}

func optionalString(value *string) any {
	if value == nil {
		return nil
	}
	return *value
}

func stringPtr(value string) *string {
	return &value
}
