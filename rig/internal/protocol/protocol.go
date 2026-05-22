package protocol

import (
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"strconv"
	"strings"
)

const (
	SchemaVersion = "2.0"

	LocalTopicRoot                     = "dev/txing/rig/v2"
	InventoryTopic                     = LocalTopicRoot + "/inventory"
	CapabilityStateTopicPrefix         = LocalTopicRoot + "/capability/state"
	CapabilityCommandTopicPrefix       = LocalTopicRoot + "/capability/command"
	CapabilityCommandResultTopicPrefix = LocalTopicRoot + "/capability/command-result"
	CapabilityHeartbeatTopicPrefix     = LocalTopicRoot + "/capability/heartbeat"
	BleRedconMetric                    = "bleRedcon"
	CommandPending                     = "pending"
	CommandAccepted                    = "accepted"
	CommandSucceeded                   = "succeeded"
	CommandFailed                      = "failed"
	CommandRejected                    = "rejected"
	HeartbeatRunning                   = "running"
)

type Inventory struct {
	SchemaVersion string            `json:"schemaVersion"`
	ManagerID     string            `json:"managerId"`
	Devices       []InventoryDevice `json:"devices"`
	Seq           uint64            `json:"seq"`
	IssuedAtMS    uint64            `json:"issuedAtMs"`
}

type InventoryDevice struct {
	ThingName           string             `json:"thingName"`
	ThingType           string             `json:"thingType"`
	Capabilities        []string           `json:"capabilities"`
	RedconCommandLevels []uint8            `json:"redconCommandLevels"`
	RedconRules         map[uint8][]string `json:"redconRules"`
}

type rawInventoryDevice struct {
	ThingName           string              `json:"thingName"`
	ThingType           string              `json:"thingType"`
	Capabilities        []string            `json:"capabilities"`
	RedconCommandLevels []uint8             `json:"redconCommandLevels"`
	RedconRules         map[string][]string `json:"redconRules"`
}

type MetricValue struct {
	Datatype string `json:"datatype"`
	Value    any    `json:"value"`
}

type CapabilityState struct {
	SchemaVersion string                 `json:"schemaVersion"`
	AdapterID     string                 `json:"adapterId"`
	ThingName     string                 `json:"thingName"`
	Capabilities  map[string]bool        `json:"capabilities"`
	Metrics       map[string]MetricValue `json:"metrics,omitempty"`
	ObservedAtMS  uint64                 `json:"observedAtMs"`
	Seq           uint64                 `json:"seq"`
}

type CapabilityCommand struct {
	SchemaVersion string                  `json:"schemaVersion"`
	CommandID     string                  `json:"commandId"`
	ThingName     string                  `json:"thingName"`
	Target        CapabilityCommandTarget `json:"target"`
	Reason        string                  `json:"reason"`
	IssuedAtMS    uint64                  `json:"issuedAtMs"`
	DeadlineMS    *uint64                 `json:"deadlineMs,omitempty"`
	Seq           uint64                  `json:"seq"`
}

type CapabilityCommandTarget struct {
	Redcon uint8 `json:"redcon"`
}

type CapabilityCommandResult struct {
	SchemaVersion string                        `json:"schemaVersion"`
	AdapterID     string                        `json:"adapterId"`
	CommandID     string                        `json:"commandId"`
	ThingName     string                        `json:"thingName"`
	Status        string                        `json:"status"`
	Target        CapabilityCommandResultTarget `json:"target"`
	Message       *string                       `json:"message"`
	ObservedAtMS  uint64                        `json:"observedAtMs"`
	Seq           uint64                        `json:"seq"`
}

type CapabilityCommandResultTarget struct {
	Redcon *uint8 `json:"redcon,omitempty"`
}

type CapabilityHeartbeat struct {
	SchemaVersion   string  `json:"schemaVersion"`
	AdapterID       string  `json:"adapterId"`
	Status          string  `json:"status"`
	ActiveThingName *string `json:"activeThingName"`
	ObservedAtMS    uint64  `json:"observedAtMs"`
	Seq             uint64  `json:"seq"`
}

func NewInventory(managerID string, devices []InventoryDevice, seq uint64, nowMS uint64) Inventory {
	return Inventory{
		SchemaVersion: SchemaVersion,
		ManagerID:     managerID,
		Devices:       devices,
		Seq:           seq,
		IssuedAtMS:    nowMS,
	}
}

func DecodeInventory(payload []byte) (Inventory, error) {
	var inv Inventory
	if err := json.Unmarshal(payload, &inv); err != nil {
		return Inventory{}, err
	}
	return inv, inv.Validate()
}

func (i Inventory) Marshal() ([]byte, error) {
	if err := i.Validate(); err != nil {
		return nil, err
	}
	return json.Marshal(i)
}

func (i Inventory) Validate() error {
	if err := validateSchema(i.SchemaVersion); err != nil {
		return err
	}
	if err := ValidateSegment(i.ManagerID, "managerId"); err != nil {
		return err
	}
	for _, device := range i.Devices {
		if err := device.Validate(); err != nil {
			return err
		}
	}
	return nil
}

func (d InventoryDevice) Validate() error {
	if err := ValidateSegment(d.ThingName, "thingName"); err != nil {
		return err
	}
	if err := ValidateSegment(d.ThingType, "thingType"); err != nil {
		return err
	}
	if len(d.Capabilities) == 0 {
		return errors.New("capabilities must not be empty")
	}
	if len(d.RedconCommandLevels) == 0 {
		return errors.New("redconCommandLevels must not be empty")
	}
	for _, level := range d.RedconCommandLevels {
		if err := ValidateRedcon(level, "redconCommandLevels"); err != nil {
			return err
		}
	}
	for level, capabilities := range d.RedconRules {
		if err := ValidateRedcon(level, "redconRules"); err != nil {
			return err
		}
		if len(capabilities) == 0 {
			return fmt.Errorf("redconRules.%d must not be empty", level)
		}
		for _, capability := range capabilities {
			if err := validateNonEmpty(capability, "redconRules capability"); err != nil {
				return err
			}
		}
	}
	return nil
}

func (d InventoryDevice) HasCapability(capability string) bool {
	for _, candidate := range d.Capabilities {
		if candidate == capability {
			return true
		}
	}
	return false
}

func (d InventoryDevice) MarshalJSON() ([]byte, error) {
	raw := rawInventoryDevice{
		ThingName:           d.ThingName,
		ThingType:           d.ThingType,
		Capabilities:        d.Capabilities,
		RedconCommandLevels: d.RedconCommandLevels,
		RedconRules:         make(map[string][]string, len(d.RedconRules)),
	}
	for level, capabilities := range d.RedconRules {
		raw.RedconRules[strconv.Itoa(int(level))] = capabilities
	}
	return json.Marshal(raw)
}

func (d *InventoryDevice) UnmarshalJSON(payload []byte) error {
	var raw rawInventoryDevice
	if err := json.Unmarshal(payload, &raw); err != nil {
		return err
	}
	rules := make(map[uint8][]string, len(raw.RedconRules))
	for rawLevel, capabilities := range raw.RedconRules {
		level, err := strconv.ParseUint(rawLevel, 10, 8)
		if err != nil {
			return fmt.Errorf("parse redconRules level %q: %w", rawLevel, err)
		}
		rules[uint8(level)] = capabilities
	}
	*d = InventoryDevice{
		ThingName:           raw.ThingName,
		ThingType:           raw.ThingType,
		Capabilities:        raw.Capabilities,
		RedconCommandLevels: raw.RedconCommandLevels,
		RedconRules:         rules,
	}
	return nil
}

func NewCapabilityState(adapterID, thingName string, observedAtMS, seq uint64) CapabilityState {
	return CapabilityState{
		SchemaVersion: SchemaVersion,
		AdapterID:     adapterID,
		ThingName:     thingName,
		Capabilities:  map[string]bool{},
		Metrics:       map[string]MetricValue{},
		ObservedAtMS:  observedAtMS,
		Seq:           seq,
	}
}

func DecodeCapabilityState(payload []byte) (CapabilityState, error) {
	var state CapabilityState
	if err := json.Unmarshal(payload, &state); err != nil {
		return CapabilityState{}, err
	}
	if state.Metrics == nil {
		state.Metrics = map[string]MetricValue{}
	}
	return state, state.Validate()
}

func (s CapabilityState) Marshal() ([]byte, error) {
	if err := s.Validate(); err != nil {
		return nil, err
	}
	return json.Marshal(s)
}

func (s CapabilityState) Validate() error {
	if err := validateSchema(s.SchemaVersion); err != nil {
		return err
	}
	if err := ValidateSegment(s.AdapterID, "adapterId"); err != nil {
		return err
	}
	if err := ValidateSegment(s.ThingName, "thingName"); err != nil {
		return err
	}
	if len(s.Capabilities) == 0 {
		return errors.New("capabilities must not be empty")
	}
	for capability := range s.Capabilities {
		if err := validateNonEmpty(capability, "capability"); err != nil {
			return err
		}
	}
	for name, metric := range s.Metrics {
		if err := validateNonEmpty(name, "metric name"); err != nil {
			return err
		}
		if err := metric.Validate(); err != nil {
			return err
		}
	}
	return nil
}

func MetricBoolean(value bool) MetricValue {
	return MetricValue{Datatype: "Boolean", Value: value}
}

func MetricInt32(value int32) MetricValue {
	return MetricValue{Datatype: "Int32", Value: value}
}

func MetricInt64(value int64) MetricValue {
	return MetricValue{Datatype: "Int64", Value: value}
}

func MetricUInt64(value uint64) MetricValue {
	return MetricValue{Datatype: "UInt64", Value: value}
}

func MetricDouble(value float64) MetricValue {
	return MetricValue{Datatype: "Double", Value: value}
}

func MetricString(value string) MetricValue {
	return MetricValue{Datatype: "String", Value: value}
}

func (m MetricValue) Validate() error {
	switch m.Datatype {
	case "Boolean":
		if _, ok := m.Value.(bool); ok {
			return nil
		}
	case "Int32", "Int64", "UInt32", "UInt64":
		if _, ok := integerMetric(m.Value); ok {
			return nil
		}
	case "Float", "Double":
		if _, ok := floatMetric(m.Value); ok {
			return nil
		}
	case "String":
		if _, ok := m.Value.(string); ok {
			return nil
		}
	}
	return fmt.Errorf("unsupported or mismatched metric datatype %s", m.Datatype)
}

func DecodeCapabilityCommand(payload []byte) (CapabilityCommand, error) {
	var command CapabilityCommand
	if err := json.Unmarshal(payload, &command); err != nil {
		return CapabilityCommand{}, err
	}
	return command, command.Validate()
}

func NewCapabilityCommand(commandID, thingName string, redcon uint8, reason string, issuedAtMS uint64, seq uint64, deadlineMS *uint64) (CapabilityCommand, error) {
	if err := ValidateRedcon(redcon, "target.redcon"); err != nil {
		return CapabilityCommand{}, err
	}
	if deadlineMS != nil && *deadlineMS <= issuedAtMS {
		return CapabilityCommand{}, errors.New("deadlineMs must be after issuedAtMs")
	}
	command := CapabilityCommand{
		SchemaVersion: SchemaVersion,
		CommandID:     commandID,
		ThingName:     thingName,
		Target:        CapabilityCommandTarget{Redcon: redcon},
		Reason:        reason,
		IssuedAtMS:    issuedAtMS,
		DeadlineMS:    deadlineMS,
		Seq:           seq,
	}
	return command, command.Validate()
}

func (c CapabilityCommand) Marshal() ([]byte, error) {
	if err := c.Validate(); err != nil {
		return nil, err
	}
	return json.Marshal(c)
}

func (c CapabilityCommand) Validate() error {
	if err := validateSchema(c.SchemaVersion); err != nil {
		return err
	}
	if err := validateNonEmpty(c.CommandID, "commandId"); err != nil {
		return err
	}
	if err := ValidateSegment(c.ThingName, "thingName"); err != nil {
		return err
	}
	if err := ValidateRedcon(c.Target.Redcon, "target.redcon"); err != nil {
		return err
	}
	return validateNonEmpty(c.Reason, "reason")
}

func DecodeCapabilityCommandResult(payload []byte) (CapabilityCommandResult, error) {
	var result CapabilityCommandResult
	if err := json.Unmarshal(payload, &result); err != nil {
		return CapabilityCommandResult{}, err
	}
	return result, result.Validate()
}

func NewCapabilityCommandResult(adapterID, commandID, thingName, status string, observedAtMS, seq uint64) CapabilityCommandResult {
	return CapabilityCommandResult{
		SchemaVersion: SchemaVersion,
		AdapterID:     adapterID,
		CommandID:     commandID,
		ThingName:     thingName,
		Status:        status,
		Target:        CapabilityCommandResultTarget{},
		ObservedAtMS:  observedAtMS,
		Seq:           seq,
	}
}

func (r CapabilityCommandResult) Marshal() ([]byte, error) {
	if err := r.Validate(); err != nil {
		return nil, err
	}
	return json.Marshal(r)
}

func (r CapabilityCommandResult) Validate() error {
	if err := validateSchema(r.SchemaVersion); err != nil {
		return err
	}
	if err := ValidateSegment(r.AdapterID, "adapterId"); err != nil {
		return err
	}
	if err := validateNonEmpty(r.CommandID, "commandId"); err != nil {
		return err
	}
	if err := ValidateSegment(r.ThingName, "thingName"); err != nil {
		return err
	}
	switch r.Status {
	case CommandPending, CommandAccepted, CommandSucceeded, CommandFailed, CommandRejected:
	default:
		return fmt.Errorf("unsupported command result status %s", r.Status)
	}
	if r.Target.Redcon != nil {
		return ValidateRedcon(*r.Target.Redcon, "target.redcon")
	}
	return nil
}

func DecodeCapabilityHeartbeat(payload []byte) (CapabilityHeartbeat, error) {
	var heartbeat CapabilityHeartbeat
	if err := json.Unmarshal(payload, &heartbeat); err != nil {
		return CapabilityHeartbeat{}, err
	}
	return heartbeat, heartbeat.Validate()
}

func NewCapabilityHeartbeat(adapterID, status string, activeThingName *string, observedAtMS, seq uint64) CapabilityHeartbeat {
	return CapabilityHeartbeat{
		SchemaVersion:   SchemaVersion,
		AdapterID:       adapterID,
		Status:          status,
		ActiveThingName: activeThingName,
		ObservedAtMS:    observedAtMS,
		Seq:             seq,
	}
}

func (h CapabilityHeartbeat) Marshal() ([]byte, error) {
	if err := h.Validate(); err != nil {
		return nil, err
	}
	return json.Marshal(h)
}

func (h CapabilityHeartbeat) Validate() error {
	if err := validateSchema(h.SchemaVersion); err != nil {
		return err
	}
	if err := ValidateSegment(h.AdapterID, "adapterId"); err != nil {
		return err
	}
	if err := validateNonEmpty(h.Status, "status"); err != nil {
		return err
	}
	if h.ActiveThingName != nil {
		return ValidateSegment(*h.ActiveThingName, "activeThingName")
	}
	return nil
}

func BuildCapabilityStateTopic(thingName, adapterID string) (string, error) {
	if err := ValidateSegment(thingName, "thingName"); err != nil {
		return "", err
	}
	if err := ValidateSegment(adapterID, "adapterId"); err != nil {
		return "", err
	}
	return CapabilityStateTopicPrefix + "/" + thingName + "/" + adapterID, nil
}

func BuildCapabilityCommandTopic(thingName string) (string, error) {
	if err := ValidateSegment(thingName, "thingName"); err != nil {
		return "", err
	}
	return CapabilityCommandTopicPrefix + "/" + thingName, nil
}

func BuildCapabilityCommandResultTopic(thingName, adapterID string) (string, error) {
	if err := ValidateSegment(thingName, "thingName"); err != nil {
		return "", err
	}
	if err := ValidateSegment(adapterID, "adapterId"); err != nil {
		return "", err
	}
	return CapabilityCommandResultTopicPrefix + "/" + thingName + "/" + adapterID, nil
}

func BuildCapabilityHeartbeatTopic(adapterID string) (string, error) {
	if err := ValidateSegment(adapterID, "adapterId"); err != nil {
		return "", err
	}
	return CapabilityHeartbeatTopicPrefix + "/" + adapterID, nil
}

func ParseCapabilityStateTopic(topic string) (thingName, adapterID string, ok bool) {
	return parseTwoSegmentSuffix(topic, CapabilityStateTopicPrefix)
}

func ParseCapabilityCommandTopic(topic string) (thingName string, ok bool) {
	prefix := CapabilityCommandTopicPrefix + "/"
	suffix, ok := strings.CutPrefix(topic, prefix)
	if !ok || suffix == "" || strings.Contains(suffix, "/") {
		return "", false
	}
	return suffix, true
}

func ParseCapabilityCommandResultTopic(topic string) (thingName, adapterID string, ok bool) {
	return parseTwoSegmentSuffix(topic, CapabilityCommandResultTopicPrefix)
}

func ParseCapabilityHeartbeatTopic(topic string) (adapterID string, ok bool) {
	prefix := CapabilityHeartbeatTopicPrefix + "/"
	suffix, ok := strings.CutPrefix(topic, prefix)
	if !ok || suffix == "" || strings.Contains(suffix, "/") {
		return "", false
	}
	return suffix, true
}

func CommandDeadlineExpired(command CapabilityCommand, nowMS uint64) bool {
	return command.DeadlineMS != nil && nowMS > *command.DeadlineMS
}

func NormalizeBleTargetRedcon(redcon uint8) (uint8, error) {
	switch redcon {
	case 1, 2:
		return 3, nil
	case 3, 4:
		return redcon, nil
	default:
		return 0, fmt.Errorf("unsupported BLE target REDCON %d", redcon)
	}
}

func ValidateSegment(value, label string) error {
	if err := validateNonEmpty(value, label); err != nil {
		return err
	}
	if strings.ContainsAny(value, "/#+") {
		return fmt.Errorf("%s must not contain MQTT topic separators or wildcards", label)
	}
	return nil
}

func ValidateRedcon(level uint8, label string) error {
	if level < 1 || level > 4 {
		return fmt.Errorf("%s must be between 1 and 4, got %d", label, level)
	}
	return nil
}

func validateSchema(value string) error {
	if value != SchemaVersion {
		return fmt.Errorf("unsupported schemaVersion %s", value)
	}
	return nil
}

func validateNonEmpty(value, label string) error {
	if strings.TrimSpace(value) == "" {
		return fmt.Errorf("%s must not be empty", label)
	}
	return nil
}

func parseTwoSegmentSuffix(topic, prefix string) (string, string, bool) {
	suffix, ok := strings.CutPrefix(topic, prefix+"/")
	if !ok {
		return "", "", false
	}
	parts := strings.Split(suffix, "/")
	if len(parts) != 2 || parts[0] == "" || parts[1] == "" {
		return "", "", false
	}
	return parts[0], parts[1], true
}

func integerMetric(value any) (int64, bool) {
	switch typed := value.(type) {
	case int:
		return int64(typed), true
	case int32:
		return int64(typed), true
	case int64:
		return typed, true
	case uint:
		if uint64(typed) > math.MaxInt64 {
			return 0, false
		}
		return int64(typed), true
	case uint32:
		return int64(typed), true
	case uint64:
		if typed > math.MaxInt64 {
			return 0, false
		}
		return int64(typed), true
	case float64:
		if math.Trunc(typed) == typed && typed >= math.MinInt64 && typed <= math.MaxInt64 {
			return int64(typed), true
		}
	case json.Number:
		if value, err := typed.Int64(); err == nil {
			return value, true
		}
	}
	return 0, false
}

func FloatMetricValue(value any) (float64, bool) {
	return floatMetric(value)
}

func IntMetricValue(value any) (int64, bool) {
	return integerMetric(value)
}

func floatMetric(value any) (float64, bool) {
	switch typed := value.(type) {
	case float64:
		return typed, true
	case float32:
		return float64(typed), true
	case int:
		return float64(typed), true
	case int64:
		return float64(typed), true
	case uint64:
		return float64(typed), true
	case json.Number:
		if value, err := typed.Float64(); err == nil {
			return value, true
		}
	}
	return 0, false
}
