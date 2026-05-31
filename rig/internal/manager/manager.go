package manager

import (
	"errors"
	"fmt"
	"sort"

	"github.com/mparkachov/txing/rig/internal/protocol"
	"github.com/mparkachov/txing/rig/internal/sparkplug"
)

const (
	StateTTLMS = uint64(150_000)

	SparkplugCapability = "sparkplug"
	BLECapability       = "ble"
	PowerCapability     = "power"
	BoardCapability     = "board"
	MCPCapability       = "mcp"
	VideoCapability     = "video"

	NodeRedconBorn = uint8(1)
	NodeRedconDead = uint8(4)
)

type DeviceSnapshot struct {
	ThingName          string
	ThingType          string
	Capabilities       map[string]bool
	Metrics            map[string]protocol.MetricValue
	Redcon             *uint8
	SparkplugAvailable bool
}

type DevicePublicationKind int

const (
	PublicationNone DevicePublicationKind = iota
	PublicationBirth
	PublicationData
	PublicationDeath
)

type DevicePublication struct {
	Kind    DevicePublicationKind
	Redcon  uint8
	Metrics []sparkplug.Metric
}

type MqttWill struct {
	Topic   string
	Payload []byte
}

type MqttSessionSpec struct {
	ClientID string
	Will     MqttWill
}

type DeviceRuntimeState struct {
	inventory                 protocol.InventoryDevice
	adapterStates             map[string]protocol.CapabilityState
	lastPublishedRedcon       *uint8
	lastPublishedCapabilities map[string]bool
	lastPublishedMetrics      map[string]protocol.MetricValue
	born                      bool
	unavailablePublished      bool
}

func NodeClientID(edgeNodeID string) string {
	return edgeNodeID + "-sparkplug-manager"
}

func NewDeviceRuntimeState(inventory protocol.InventoryDevice) *DeviceRuntimeState {
	return &DeviceRuntimeState{
		inventory:                 inventory,
		adapterStates:             map[string]protocol.CapabilityState{},
		lastPublishedCapabilities: map[string]bool{},
		lastPublishedMetrics:      map[string]protocol.MetricValue{},
	}
}

func (s *DeviceRuntimeState) Inventory() protocol.InventoryDevice {
	return s.inventory
}

func (s *DeviceRuntimeState) ReplaceInventory(inventory protocol.InventoryDevice) {
	if !sameStrings(s.inventory.Capabilities, inventory.Capabilities) {
		s.ResetPublication()
	}
	s.inventory = inventory
}

func (s *DeviceRuntimeState) ResetPublication() {
	s.born = false
	s.lastPublishedRedcon = nil
	s.lastPublishedCapabilities = map[string]bool{}
	s.lastPublishedMetrics = map[string]protocol.MetricValue{}
	s.unavailablePublished = false
}

func (s *DeviceRuntimeState) ObserveState(state protocol.CapabilityState) error {
	if err := state.Validate(); err != nil {
		return err
	}
	if state.ThingName != s.inventory.ThingName {
		return fmt.Errorf("state thingName %s does not match inventory thingName %s", state.ThingName, s.inventory.ThingName)
	}
	if stateReportsSparkplugUnavailable(state) {
		if existing, ok := s.adapterStates[state.AdapterID]; ok && stateReportsSparkplugAvailable(existing) && stateFreshAt(existing, state.ObservedAtMS) {
			return nil
		}
	}
	if stateReportsOnlyScannerReachability(state) {
		if existing, ok := s.adapterStates[state.AdapterID]; ok &&
			stateFreshAt(existing, state.ObservedAtMS) &&
			stateCarriesDeviceStateEvidence(existing) {
			return nil
		}
	}
	if stateReportsBleRedcon4(state) {
		observedAtMS := state.ObservedAtMS
		for adapterID, existing := range s.adapterStates {
			if stateDeclaresBoardOwnedCapability(existing) && existing.ObservedAtMS <= observedAtMS {
				delete(s.adapterStates, adapterID)
			}
		}
	} else if stateDeclaresBoardOwnedCapability(state) {
		for _, existing := range s.adapterStates {
			if stateReportsBleRedcon4(existing) && existing.ObservedAtMS >= state.ObservedAtMS {
				delete(s.adapterStates, state.AdapterID)
				return nil
			}
		}
	}
	s.adapterStates[state.AdapterID] = state
	return nil
}

func (s *DeviceRuntimeState) Snapshot(nowMS uint64) DeviceSnapshot {
	capabilities := make(map[string]bool, len(s.inventory.Capabilities))
	for _, capability := range s.inventory.Capabilities {
		capabilities[capability] = false
	}
	metrics := map[string]protocol.MetricValue{}

	var latestBoardStateMS *uint64
	for _, state := range s.adapterStates {
		if state.ObservedAtMS+StateTTLMS < nowMS || !stateDeclaresBoardOwnedCapability(state) {
			continue
		}
		if latestBoardStateMS == nil || state.ObservedAtMS > *latestBoardStateMS {
			value := state.ObservedAtMS
			latestBoardStateMS = &value
		}
	}

	bleRedcon4Observed := false
	for _, state := range s.adapterStates {
		if state.ObservedAtMS+StateTTLMS < nowMS {
			continue
		}
		newerOrEqualToBoard := latestBoardStateMS == nil || state.ObservedAtMS >= *latestBoardStateMS
		bleRedcon4Observed = bleRedcon4Observed || (stateReportsBleRedcon4(state) && newerOrEqualToBoard)
		for capability, available := range state.Capabilities {
			if current, ok := capabilities[capability]; ok {
				capabilities[capability] = current || available
			}
		}
	}

	applyCapabilityDependencyGates(capabilities, bleRedcon4Observed)
	redcon := SelectBestRedcon(s.inventory.RedconRules, s.inventory.RedconCommandLevels, capabilities)
	sparkplugAvailable := capabilities["sparkplug"]
	return DeviceSnapshot{
		ThingName:          s.inventory.ThingName,
		ThingType:          s.inventory.ThingType,
		Capabilities:       capabilities,
		Metrics:            metrics,
		Redcon:             redcon,
		SparkplugAvailable: sparkplugAvailable,
	}
}

func (s *DeviceRuntimeState) DecidePublication(nowMS uint64) (DevicePublication, error) {
	snapshot := s.Snapshot(nowMS)
	if !snapshot.SparkplugAvailable {
		s.lastPublishedRedcon = nil
		s.lastPublishedCapabilities = map[string]bool{}
		s.lastPublishedMetrics = map[string]protocol.MetricValue{}
		if s.born {
			s.born = false
			s.unavailablePublished = true
			return DevicePublication{Kind: PublicationDeath}, nil
		}
		if !s.unavailablePublished {
			s.unavailablePublished = true
			return DevicePublication{Kind: PublicationDeath}, nil
		}
		return DevicePublication{Kind: PublicationNone}, nil
	}

	s.unavailablePublished = false
	redcon := uint8(4)
	if snapshot.Redcon != nil {
		redcon = *snapshot.Redcon
	}
	capabilitiesChanged := !sameBoolMap(s.lastPublishedCapabilities, snapshot.Capabilities)
	metricsChanged := !sameMetricMap(s.lastPublishedMetrics, snapshot.Metrics)
	redconChanged := s.lastPublishedRedcon == nil || *s.lastPublishedRedcon != redcon

	var metrics []sparkplug.Metric
	if !s.born || redconChanged || capabilitiesChanged || metricsChanged {
		var err error
		metrics, err = sparkplugMetricsFromSnapshot(snapshot.Capabilities, snapshot.Metrics)
		if err != nil {
			return DevicePublication{}, err
		}
	}

	if !s.born {
		s.born = true
		s.lastPublishedRedcon = &redcon
		s.lastPublishedCapabilities = cloneBoolMap(snapshot.Capabilities)
		s.lastPublishedMetrics = cloneMetricMap(snapshot.Metrics)
		return DevicePublication{Kind: PublicationBirth, Redcon: redcon, Metrics: metrics}, nil
	}
	if redconChanged || capabilitiesChanged || metricsChanged {
		s.lastPublishedRedcon = &redcon
		s.lastPublishedCapabilities = cloneBoolMap(snapshot.Capabilities)
		s.lastPublishedMetrics = cloneMetricMap(snapshot.Metrics)
		return DevicePublication{Kind: PublicationData, Redcon: redcon, Metrics: metrics}, nil
	}
	return DevicePublication{Kind: PublicationNone}, nil
}

func applyCapabilityDependencyGates(capabilities map[string]bool, bleRedcon4Observed bool) {
	if bleRedcon4Observed {
		forceCapabilityUnavailable(capabilities, PowerCapability)
		forceCapabilityUnavailable(capabilities, BoardCapability)
		forceCapabilityUnavailable(capabilities, MCPCapability)
		forceCapabilityUnavailable(capabilities, VideoCapability)
	}
	if !bleRedcon4Observed &&
		capabilityIsDeclared(capabilities, PowerCapability) &&
		!capabilityIsAvailable(capabilities, PowerCapability) &&
		(capabilityIsAvailable(capabilities, BoardCapability) ||
			capabilityIsAvailable(capabilities, MCPCapability) ||
			capabilityIsAvailable(capabilities, VideoCapability)) {
		capabilities[PowerCapability] = true
	}
	if capabilityIsDeclared(capabilities, PowerCapability) && !capabilityIsAvailable(capabilities, PowerCapability) {
		forceCapabilityUnavailable(capabilities, BoardCapability)
		forceCapabilityUnavailable(capabilities, MCPCapability)
		forceCapabilityUnavailable(capabilities, VideoCapability)
	}
	if capabilityIsDeclared(capabilities, BoardCapability) && !capabilityIsAvailable(capabilities, BoardCapability) {
		forceCapabilityUnavailable(capabilities, MCPCapability)
		forceCapabilityUnavailable(capabilities, VideoCapability)
	}
	if capabilityIsDeclared(capabilities, MCPCapability) && !capabilityIsAvailable(capabilities, MCPCapability) {
		forceCapabilityUnavailable(capabilities, VideoCapability)
	}
}

func stateReportsBleRedcon4(state protocol.CapabilityState) bool {
	if !capabilityIsDeclared(state.Capabilities, PowerCapability) || capabilityIsAvailable(state.Capabilities, PowerCapability) {
		return false
	}
	metric, ok := state.Metrics[protocol.BleRedconMetric]
	if !ok {
		return false
	}
	value, ok := protocol.IntMetricValue(metric.Value)
	return ok && value == 4
}

func stateReportsOnlyScannerReachability(state protocol.CapabilityState) bool {
	if len(state.Metrics) != 0 {
		return false
	}
	if !capabilityIsAvailable(state.Capabilities, SparkplugCapability) ||
		!capabilityIsAvailable(state.Capabilities, BLECapability) {
		return false
	}
	for capability, available := range state.Capabilities {
		switch capability {
		case SparkplugCapability, BLECapability:
			if !available {
				return false
			}
		default:
			if available {
				return false
			}
		}
	}
	return true
}

func stateCarriesDeviceStateEvidence(state protocol.CapabilityState) bool {
	if len(state.Metrics) != 0 {
		return true
	}
	for capability, available := range state.Capabilities {
		if capability != SparkplugCapability && capability != BLECapability && available {
			return true
		}
	}
	return false
}

func stateReportsSparkplugAvailable(state protocol.CapabilityState) bool {
	return capabilityIsAvailable(state.Capabilities, SparkplugCapability)
}

func stateReportsSparkplugUnavailable(state protocol.CapabilityState) bool {
	return capabilityIsDeclared(state.Capabilities, SparkplugCapability) && !capabilityIsAvailable(state.Capabilities, SparkplugCapability)
}

func stateFreshAt(state protocol.CapabilityState, nowMS uint64) bool {
	if state.ObservedAtMS > nowMS {
		return state.ObservedAtMS-nowMS <= StateTTLMS
	}
	return nowMS-state.ObservedAtMS <= StateTTLMS
}

func stateDeclaresBoardOwnedCapability(state protocol.CapabilityState) bool {
	return capabilityIsDeclared(state.Capabilities, BoardCapability) ||
		capabilityIsDeclared(state.Capabilities, MCPCapability) ||
		capabilityIsDeclared(state.Capabilities, VideoCapability)
}

func capabilityIsDeclared(capabilities map[string]bool, capability string) bool {
	_, ok := capabilities[capability]
	return ok
}

func capabilityIsAvailable(capabilities map[string]bool, capability string) bool {
	return capabilities[capability]
}

func forceCapabilityUnavailable(capabilities map[string]bool, capability string) {
	if _, ok := capabilities[capability]; ok {
		capabilities[capability] = false
	}
}

func SelectBestRedcon(rules map[uint8][]string, commandLevels []uint8, capabilities map[string]bool) *uint8 {
	commandLevelSet := make(map[uint8]struct{}, len(commandLevels))
	for _, level := range commandLevels {
		commandLevelSet[level] = struct{}{}
	}
	var best *uint8
	for level, required := range rules {
		if _, ok := commandLevelSet[level]; !ok {
			continue
		}
		ready := true
		for _, capability := range required {
			if !capabilities[capability] {
				ready = false
				break
			}
		}
		if ready && (best == nil || level < *best) {
			value := level
			best = &value
		}
	}
	return best
}

func CommandFromDCMD(thingName string, payload []byte, commandID string, nowMS uint64, deadlineMS *uint64) (*protocol.CapabilityCommand, error) {
	decoded, err := sparkplug.DecodeRedconCommand(payload)
	if err != nil {
		return nil, err
	}
	if decoded == nil {
		return nil, nil
	}
	command, err := protocol.NewCapabilityCommand(commandID, thingName, decoded.Value, "sparkplug-dcmd", nowMS, seqOrZero(decoded.Seq), deadlineMS)
	if err != nil {
		return nil, err
	}
	return &command, nil
}

func CommandResultMetrics(result protocol.CapabilityCommandResult) ([]sparkplug.Metric, error) {
	if err := result.Validate(); err != nil {
		return nil, err
	}
	if result.Seq > uint64(^uint32(0)>>1) {
		return nil, errors.New("command result seq exceeds Int32")
	}
	metrics := []sparkplug.Metric{
		sparkplug.NewStringMetric("redconCommandStatus", result.Status),
		sparkplug.NewInt32Metric("redconCommandSeq", int32(result.Seq)),
		sparkplug.NewStringMetric("redconCommandId", result.CommandID),
	}
	if result.Target.Redcon != nil {
		metrics = append(metrics, sparkplug.NewInt32Metric("redconCommandTarget", int32(*result.Target.Redcon)))
	}
	if result.Message != nil && *result.Message != "" {
		metrics = append(metrics, sparkplug.NewStringMetric("redconCommandMessage", *result.Message))
	}
	return metrics, nil
}

func NodeSessionSpec(groupID, edgeNodeID, clientID string, bdSeq uint64, timestamp uint64) (MqttSessionSpec, error) {
	payload, err := sparkplug.BuildNodeDeathPayload(NodeRedconDead, bdSeq, timestamp)
	if err != nil {
		return MqttSessionSpec{}, err
	}
	return MqttSessionSpec{
		ClientID: clientID,
		Will: MqttWill{
			Topic:   sparkplug.BuildNodeTopic(groupID, "NDEATH", edgeNodeID),
			Payload: payload,
		},
	}, nil
}

func DeviceSessionSpec(groupID, edgeNodeID, thingName string, timestamp uint64) (MqttSessionSpec, error) {
	payload, err := sparkplug.BuildDeviceDeathPayload(0, timestamp)
	if err != nil {
		return MqttSessionSpec{}, err
	}
	return MqttSessionSpec{
		ClientID: thingName,
		Will: MqttWill{
			Topic:   sparkplug.BuildDeviceTopic(groupID, "DDEATH", edgeNodeID, thingName),
			Payload: payload,
		},
	}, nil
}

func GracefulDeviceDeath(groupID, edgeNodeID, thingName string, seq uint64, timestamp uint64) (string, []byte, error) {
	payload, err := sparkplug.BuildDeviceDeathPayload(seq, timestamp)
	if err != nil {
		return "", nil, err
	}
	return sparkplug.BuildDeviceTopic(groupID, "DDEATH", edgeNodeID, thingName), payload, nil
}

func GracefulNodeDeath(groupID, edgeNodeID string, bdSeq uint64, timestamp uint64) (string, []byte, error) {
	payload, err := sparkplug.BuildNodeDeathPayload(NodeRedconDead, bdSeq, timestamp)
	if err != nil {
		return "", nil, err
	}
	return sparkplug.BuildNodeTopic(groupID, "NDEATH", edgeNodeID), payload, nil
}

func sparkplugMetricsFromSnapshot(capabilities map[string]bool, _ map[string]protocol.MetricValue) ([]sparkplug.Metric, error) {
	keys := make([]string, 0, len(capabilities))
	for capability := range capabilities {
		keys = append(keys, capability)
	}
	sort.Strings(keys)
	metrics := make([]sparkplug.Metric, 0, len(keys))
	for _, capability := range keys {
		metrics = append(metrics, sparkplug.NewBooleanMetric("capability."+capability, capabilities[capability]))
	}
	return metrics, nil
}

func seqOrZero(value *uint64) uint64 {
	if value == nil {
		return 0
	}
	return *value
}

func sameStrings(left, right []string) bool {
	if len(left) != len(right) {
		return false
	}
	for index := range left {
		if left[index] != right[index] {
			return false
		}
	}
	return true
}

func sameBoolMap(left, right map[string]bool) bool {
	if len(left) != len(right) {
		return false
	}
	for key, leftValue := range left {
		if rightValue, ok := right[key]; !ok || rightValue != leftValue {
			return false
		}
	}
	return true
}

func sameMetricMap(left, right map[string]protocol.MetricValue) bool {
	if len(left) != len(right) {
		return false
	}
	for key, leftValue := range left {
		rightValue, ok := right[key]
		if !ok || leftValue.Datatype != rightValue.Datatype || fmt.Sprint(leftValue.Value) != fmt.Sprint(rightValue.Value) {
			return false
		}
	}
	return true
}

func cloneBoolMap(input map[string]bool) map[string]bool {
	output := make(map[string]bool, len(input))
	for key, value := range input {
		output[key] = value
	}
	return output
}

func cloneMetricMap(input map[string]protocol.MetricValue) map[string]protocol.MetricValue {
	output := make(map[string]protocol.MetricValue, len(input))
	for key, value := range input {
		output[key] = value
	}
	return output
}
