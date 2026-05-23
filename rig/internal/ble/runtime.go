package ble

import (
	"container/list"
	"fmt"
	"hash/fnv"
	"strings"

	"github.com/mparkachov/txing/rig/internal/protocol"
)

const (
	BLERetryMinDelayMS                    = uint64(1_000)
	BLERetryMaxDelayMS                    = uint64(120_000)
	BLUEResourceExhaustedReconnectDelayMS = uint64(60_000)
	BluezInProgressReconnectDelayMS       = uint64(10_000)
	BluezInProgressScanRetryDelayMS       = uint64(1_000)
	BLEScannerUnmanagedTxingLogIntervalMS = uint64(30_000)
	BLEConnectSessionMaxTimeoutMS         = uint64(20_000)
	BLEActiveMeasurementStaleMS           = uint64(20_000)
	BLEIdleMeasurementStaleMS             = uint64(120_000)
)

type PendingShadowUpdates struct {
	updates map[string]ShadowUpdate
	order   *list.List
}

func NewPendingShadowUpdates() *PendingShadowUpdates {
	return &PendingShadowUpdates{
		updates: map[string]ShadowUpdate{},
		order:   list.New(),
	}
}

func (p *PendingShadowUpdates) Push(update ShadowUpdate) {
	if p.updates == nil {
		p.updates = map[string]ShadowUpdate{}
	}
	if p.order == nil {
		p.order = list.New()
	}
	if _, ok := p.updates[update.Topic]; !ok {
		p.order.PushBack(update.Topic)
	}
	p.updates[update.Topic] = update
}

func (p *PendingShadowUpdates) Pop() *ShadowUpdate {
	if p.order == nil {
		return nil
	}
	for p.order.Len() > 0 {
		front := p.order.Front()
		p.order.Remove(front)
		topic := front.Value.(string)
		if update, ok := p.updates[topic]; ok {
			delete(p.updates, topic)
			return &update
		}
	}
	return nil
}

func (p *PendingShadowUpdates) Len() int {
	return len(p.updates)
}

func (p *PendingShadowUpdates) Empty() bool {
	return len(p.updates) == 0
}

func DeviceSpecFromInventory(device protocol.InventoryDevice) *DeviceSpec {
	if !device.HasCapability(BLECapability) {
		return nil
	}
	kind := DeviceKindPower
	if device.HasCapability(WeatherCapability) {
		kind = DeviceKindWeather
	} else if !device.HasCapability(PowerCapability) {
		return nil
	}
	return &DeviceSpec{ThingName: device.ThingName, Kind: kind}
}

func PublishCommandResult(adapterID string, command protocol.CapabilityCommand, status string, message *string, redcon *uint8, nowMS uint64, seq uint64) (string, []byte, error) {
	result := protocol.NewCapabilityCommandResult(adapterID, command.CommandID, command.ThingName, status, nowMS, seq)
	result.Message = message
	result.Target.Redcon = redcon
	topic, err := protocol.BuildCapabilityCommandResultTopic(command.ThingName, adapterID)
	if err != nil {
		return "", nil, err
	}
	payload, err := result.Marshal()
	if err != nil {
		return "", nil, err
	}
	return topic, payload, nil
}

func WeatherCommandRejectReason(command protocol.CapabilityCommand, spec DeviceSpec) *string {
	if spec.Kind != DeviceKindWeather || command.Target.Redcon == RedconIdle {
		return nil
	}
	reason := fmt.Sprintf("weather BLE devices only support REDCON %d", RedconIdle)
	return &reason
}

func AdvertisementPublishesCapabilityState(_ DeviceSpec) bool {
	return true
}

func BoundedRetryDelayMS(baseDelayMS uint64, failureCount uint32, maxDelayMS uint64) uint64 {
	delay := baseDelayMS
	for i := uint32(0); i < failureCount; i++ {
		if delay >= maxDelayMS/2 {
			return maxDelayMS
		}
		delay *= 2
	}
	if delay > maxDelayMS {
		return maxDelayMS
	}
	return delay
}

func StableJitterMS(key string, maxJitterMS uint64) uint64 {
	if maxJitterMS == 0 {
		return 0
	}
	hash := fnv.New64a()
	_, _ = hash.Write([]byte(key))
	return hash.Sum64() % (maxJitterMS + 1)
}

func BLEErrorIndicatesInProgress(message string) bool {
	lower := strings.ToLower(message)
	return strings.Contains(lower, "in progress") ||
		strings.Contains(lower, "already in progress") ||
		strings.Contains(lower, "operation already in progress")
}

func BLEErrorIndicatesNoDiscovery(message string) bool {
	lower := strings.ToLower(message)
	return strings.Contains(lower, "no discovery started") ||
		strings.Contains(lower, "not discovering") ||
		strings.Contains(lower, "discovery not started")
}

func BLEErrorIndicatesHostResourceExhaustion(message string) bool {
	lower := strings.ToLower(message)
	return strings.Contains(lower, "resource temporarily unavailable") ||
		strings.Contains(lower, "connection timed out") ||
		strings.Contains(lower, "failed to connect: le-connection-abort-by-local")
}

func BLECommandConnectErrorIsRetryable(message string) bool {
	lower := strings.ToLower(message)
	return BLEErrorIndicatesInProgress(message) ||
		BLEErrorIndicatesNoDiscovery(message) ||
		BLEErrorIndicatesHostResourceExhaustion(message) ||
		strings.Contains(lower, "not found") ||
		strings.Contains(lower, "no ble advertisement has been observed") ||
		strings.Contains(lower, "last ble advertisement") ||
		strings.Contains(lower, "is not visible") ||
		strings.Contains(lower, "ble connect timed out") ||
		strings.Contains(lower, "ble connect session timed out") ||
		strings.Contains(lower, "connect ble peripheral") ||
		strings.Contains(lower, "le-connection-abort-by-local")
}

func ShouldPublishScannerAdvertisement(targetNames map[string]struct{}, advertisement Advertisement, nowMS uint64, lastPublished map[string]uint64, minIntervalMS uint64) bool {
	if !advertisement.HasTxingService() {
		return false
	}
	name := ScannerReportedIdentityName(advertisement)
	if name == "" {
		return false
	}
	if _, ok := targetNames[name]; !ok {
		return false
	}
	last := lastPublished[name]
	if last != 0 && last+minIntervalMS > nowMS {
		return false
	}
	lastPublished[name] = nowMS
	return true
}

func ShouldLogUnmanagedTxingAdvertisement(advertisement Advertisement, nowMS uint64, lastLogged map[string]uint64) bool {
	if !advertisement.HasTxingService() {
		return false
	}
	name := ScannerReportedIdentityName(advertisement)
	if name == "" {
		return false
	}
	last := lastLogged[name]
	if last != 0 && last+BLEScannerUnmanagedTxingLogIntervalMS > nowMS {
		return false
	}
	lastLogged[name] = nowMS
	return true
}

func ScannerReportedIdentityName(advertisement Advertisement) string {
	if advertisement.IdentityName != nil && *advertisement.IdentityName != "" {
		return *advertisement.IdentityName
	}
	return ""
}

func BLEAddressIsMatchable(address string) bool {
	trimmed := strings.TrimSpace(address)
	if trimmed == "" {
		return false
	}
	lower := strings.ToLower(trimmed)
	return lower != "00:00:00:00:00:00" &&
		lower != "ff:ff:ff:ff:ff:ff" &&
		lower != "unknown"
}

func ConnectSessionTimeoutMS(connectTimeoutMS uint64) uint64 {
	timeout := connectTimeoutMS + 2_000
	if timeout > BLEConnectSessionMaxTimeoutMS {
		return BLEConnectSessionMaxTimeoutMS
	}
	if timeout < connectTimeoutMS {
		return connectTimeoutMS
	}
	return timeout
}

func ScannerAdvertisementHasFreshSignal(rssi *int16) bool {
	return rssi != nil
}
