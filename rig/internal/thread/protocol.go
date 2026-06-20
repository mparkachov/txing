package thread

import (
	"encoding/json"
	"fmt"
	"net"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/mparkachov/txing/rig/internal/protocol"
)

const (
	AdapterID       = "dev.txing.rig.ThreadConnectivity"
	DeviceType      = "power-si"
	ServiceName     = "_txing-coap._udp"
	DefaultDomain   = "default.service.arpa"
	DefaultCoAPPort = uint16(5683)
	ProtocolVersion = "1"

	SparkplugCapability = "sparkplug"
	ThreadCapability    = "thread"
	PowerCapability     = "power"

	ThreadShadowName = "thread"
	PowerShadowName  = "power"
)

type DeviceSpec struct {
	ThingName string
}

type Endpoint struct {
	ThingName       string
	ServiceInstance string
	ServiceName     string
	Host            string
	Address         net.IP
	Port            uint16
	TXT             map[string]string
	ObservedAtMS    uint64
	Seq             uint64
}

type DeviceState struct {
	ThingName       string `json:"thingName"`
	ProtocolVersion string `json:"protocolVersion"`
	Redcon          uint8  `json:"redcon"`
	BatteryMV       *int   `json:"batteryMv,omitempty"`
	ServiceInstance string `json:"-"`
	Host            string `json:"-"`
	Address         string `json:"-"`
	Port            uint16 `json:"-"`
	ObservedAtMS    uint64 `json:"-"`
	Seq             uint64 `json:"-"`
}

type RedconRequest struct {
	Redcon uint8 `json:"redcon"`
}

type ShadowUpdate struct {
	Topic   string
	Payload []byte
}

func DeviceSpecFromInventory(device protocol.InventoryDevice) *DeviceSpec {
	if device.ThingType != DeviceType {
		return nil
	}
	if !device.HasCapability(ThreadCapability) || !device.HasCapability(PowerCapability) {
		return nil
	}
	return &DeviceSpec{ThingName: device.ThingName}
}

func BuildServiceFQDN(domain string) string {
	domain = strings.Trim(strings.TrimSpace(domain), ".")
	if domain == "" {
		domain = DefaultDomain
	}
	return ServiceName + "." + domain + "."
}

func NewEndpoint(instanceFQDN string, host string, port uint16, txt map[string]string, addresses []net.IP, observedAtMS uint64, seq uint64) (Endpoint, bool) {
	if strings.TrimSpace(instanceFQDN) == "" || strings.TrimSpace(host) == "" || port == 0 {
		return Endpoint{}, false
	}
	thingName := ServiceInstanceThingName(instanceFQDN)
	if thingName == "" || txt["type"] != DeviceType || len(addresses) == 0 {
		return Endpoint{}, false
	}
	return Endpoint{
		ThingName:       thingName,
		ServiceInstance: trimTrailingDot(instanceFQDN),
		ServiceName:     ServiceName,
		Host:            trimTrailingDot(host),
		Address:         addresses[0],
		Port:            port,
		TXT:             cloneStringMap(txt),
		ObservedAtMS:    observedAtMS,
		Seq:             seq,
	}, true
}

func ServiceInstanceThingName(instanceFQDN string) string {
	name := trimTrailingDot(instanceFQDN)
	suffix := "." + ServiceName + "."
	index := strings.Index(name, suffix)
	if index <= 0 {
		return ""
	}
	return unescapeDNSLabel(name[:index])
}

func ParseTXT(entries []string) map[string]string {
	txt := map[string]string{}
	for _, entry := range entries {
		key, value, ok := strings.Cut(entry, "=")
		if !ok {
			txt[strings.ToLower(strings.TrimSpace(entry))] = ""
			continue
		}
		key = strings.ToLower(strings.TrimSpace(key))
		if key == "" {
			continue
		}
		txt[key] = strings.TrimSpace(value)
	}
	return txt
}

func CapabilityStateFromDeviceState(state DeviceState) protocol.CapabilityState {
	capabilities := map[string]bool{
		SparkplugCapability: true,
		ThreadCapability:    true,
		PowerCapability:     state.Redcon < 4,
	}
	metrics := map[string]protocol.MetricValue{
		protocol.TransportRedconMetric: protocol.MetricInt32(int32(state.Redcon)),
	}
	return protocol.CapabilityState{
		SchemaVersion: protocol.SchemaVersion,
		AdapterID:     AdapterID,
		ThingName:     state.ThingName,
		Capabilities:  capabilities,
		Metrics:       metrics,
		ObservedAtMS:  state.ObservedAtMS,
		Seq:           state.Seq,
	}
}

func OfflineCapabilityState(thingName string, nowMS uint64, seq uint64) protocol.CapabilityState {
	return protocol.CapabilityState{
		SchemaVersion: protocol.SchemaVersion,
		AdapterID:     AdapterID,
		ThingName:     thingName,
		Capabilities: map[string]bool{
			SparkplugCapability: false,
			ThreadCapability:    false,
			PowerCapability:     false,
		},
		Metrics:      map[string]protocol.MetricValue{},
		ObservedAtMS: nowMS,
		Seq:          seq,
	}
}

func ShadowUpdatesFromState(state DeviceState) ([]ShadowUpdate, error) {
	reported := map[string]any{
		"online":          true,
		"service":         ServiceName,
		"serviceInstance": state.ServiceInstance,
		"host":            state.Host,
		"address":         state.Address,
		"port":            int(state.Port),
		"protocolVersion": state.ProtocolVersion,
	}
	updates := []ShadowUpdate{}
	threadUpdate, err := BuildShadowUpdate(state.ThingName, ThreadShadowName, reported)
	if err != nil {
		return nil, err
	}
	updates = append(updates, threadUpdate)
	if state.BatteryMV != nil {
		powerUpdate, err := BuildShadowUpdate(state.ThingName, PowerShadowName, map[string]any{
			"batteryMv": *state.BatteryMV,
		})
		if err != nil {
			return nil, err
		}
		updates = append(updates, powerUpdate)
	}
	return updates, nil
}

func OfflineShadowUpdate(thingName string) (ShadowUpdate, error) {
	return BuildShadowUpdate(thingName, ThreadShadowName, map[string]any{
		"online": false,
	})
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

func PublishCommandResult(command protocol.CapabilityCommand, status string, message *string, redcon *uint8, nowMS uint64, seq uint64) (string, []byte, error) {
	result := protocol.NewCapabilityCommandResult(AdapterID, command.CommandID, command.ThingName, status, nowMS, seq)
	result.Message = message
	result.Target.Redcon = redcon
	topic, err := protocol.BuildCapabilityCommandResultTopic(command.ThingName, AdapterID)
	if err != nil {
		return "", nil, err
	}
	payload, err := result.Marshal()
	if err != nil {
		return "", nil, err
	}
	return topic, payload, nil
}

func DecodeDeviceState(payload []byte, endpoint Endpoint, nowMS uint64, seq uint64) (DeviceState, error) {
	var state DeviceState
	if err := json.Unmarshal(payload, &state); err != nil {
		return DeviceState{}, err
	}
	if state.ThingName == "" {
		state.ThingName = endpoint.ThingName
	}
	if state.ThingName != endpoint.ThingName {
		return DeviceState{}, fmt.Errorf("state thingName %s does not match endpoint thingName %s", state.ThingName, endpoint.ThingName)
	}
	if state.ProtocolVersion == "" {
		state.ProtocolVersion = ProtocolVersion
	}
	if _, err := protocol.NormalizeThreadTargetRedcon(state.Redcon); err != nil {
		return DeviceState{}, err
	}
	state.ServiceInstance = endpoint.ServiceInstance
	state.Host = endpoint.Host
	state.Address = endpoint.Address.String()
	state.Port = endpoint.Port
	state.ObservedAtMS = nowMS
	state.Seq = seq
	return state, nil
}

func EncodeRedconRequest(redcon uint8) ([]byte, error) {
	normalized, err := protocol.NormalizeThreadTargetRedcon(redcon)
	if err != nil {
		return nil, err
	}
	return json.Marshal(RedconRequest{Redcon: normalized})
}

func NowMS() uint64 {
	return uint64(time.Now().UnixMilli())
}

func SortEndpoints(endpoints []Endpoint) {
	sort.Slice(endpoints, func(i, j int) bool {
		if endpoints[i].ThingName == endpoints[j].ThingName {
			return endpoints[i].Address.String() < endpoints[j].Address.String()
		}
		return endpoints[i].ThingName < endpoints[j].ThingName
	})
}

func trimTrailingDot(value string) string {
	return strings.TrimSuffix(strings.TrimSpace(value), ".")
}

func unescapeDNSLabel(label string) string {
	var builder strings.Builder
	for i := 0; i < len(label); i++ {
		if label[i] != '\\' {
			builder.WriteByte(label[i])
			continue
		}
		if i+3 < len(label) {
			if value, err := strconv.Atoi(label[i+1 : i+4]); err == nil {
				builder.WriteByte(byte(value))
				i += 3
				continue
			}
		}
		if i+1 < len(label) {
			builder.WriteByte(label[i+1])
			i++
		}
	}
	return builder.String()
}

func cloneStringMap(input map[string]string) map[string]string {
	output := make(map[string]string, len(input))
	for key, value := range input {
		output[key] = value
	}
	return output
}
