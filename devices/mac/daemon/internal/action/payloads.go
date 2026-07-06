// Payload builders copied and trimmed from
// devices/unit/daemon/internal/daemon/payloads.go. AdapterID and server
// name are mac-specific; everything else must keep the unit wire shape.
package action

import (
	"net"
)

type DefaultRouteAddresses struct {
	IPv4 net.IP
	IPv6 net.IP
}

type BoardShadowUpdate struct {
	State BoardShadowState `json:"state"`
}

type BoardShadowState struct {
	Reported BoardReport `json:"reported"`
}

type BoardReport struct {
	Power bool       `json:"power"`
	WiFi  WiFiReport `json:"wifi"`
}

type WiFiReport struct {
	Online bool   `json:"online"`
	IPv4   net.IP `json:"ipv4,omitempty"`
	IPv6   net.IP `json:"ipv6,omitempty"`
}

type CapabilityStatePayload struct {
	SchemaVersion       string                 `json:"schemaVersion"`
	AdapterID           string                 `json:"adapterId"`
	ThingName           string                 `json:"thingName"`
	Capabilities        map[string]bool        `json:"capabilities"`
	Metrics             map[string]interface{} `json:"metrics"`
	ObservedAtMS        uint64                 `json:"observedAtMs"`
	Seq                 uint64                 `json:"seq"`
	ExpiresAtMS         uint64                 `json:"expiresAtMs"`
	ExpiredCapabilities map[string]bool        `json:"expiredCapabilities"`
}

func BuildBoardShadowUpdate(report BoardReport) BoardShadowUpdate {
	return BoardShadowUpdate{State: BoardShadowState{Reported: report}}
}

func BuildOnlineBoardReport(addresses DefaultRouteAddresses) BoardReport {
	return BoardReport{
		Power: true,
		WiFi: WiFiReport{
			Online: true,
			IPv4:   addresses.IPv4,
			IPv6:   addresses.IPv6,
		},
	}
}

func BuildOfflineBoardReport() BoardReport {
	return BoardReport{
		Power: false,
		WiFi:  WiFiReport{Online: false},
	}
}

func BuildCapabilityStatePayload(thingName string, capabilities []string, availability map[string]bool, ttlMillis, observedAtMS, seq uint64) CapabilityStatePayload {
	capabilityState := make(map[string]bool, len(capabilities))
	expiredCapabilities := make(map[string]bool, len(capabilities))
	for _, capability := range capabilities {
		capabilityState[capability] = availability[capability]
		expiredCapabilities[capability] = false
	}
	return CapabilityStatePayload{
		SchemaVersion:       SchemaVersion,
		AdapterID:           BoardAdapterID,
		ThingName:           thingName,
		Capabilities:        capabilityState,
		Metrics:             map[string]interface{}{},
		ObservedAtMS:        observedAtMS,
		Seq:                 seq,
		ExpiresAtMS:         observedAtMS + ttlMillis,
		ExpiredCapabilities: expiredCapabilities,
	}
}

func MCPDescriptor(config Config, daemonVersion, transportMode string) map[string]interface{} {
	if transportMode == "" {
		transportMode = string(MCPTransportMQTT)
	}
	descriptorTopic, _ := BuildMCPDescriptorTopic(config.ThingID)
	statusTopic, _ := BuildMCPStatusTopic(config.ThingID)
	topicRoot, _ := BuildMCPTopicRoot(config.ThingID)
	sessionTopicPattern := map[string]interface{}{
		"clientToServer": "txings/" + config.ThingID + "/mcp/session/{sessionId}/c2s",
		"serverToClient": "txings/" + config.ThingID + "/mcp/session/{sessionId}/s2c",
	}
	var transports []map[string]interface{}
	if transportMode == string(MCPTransportWebRTCDataChannel) {
		transports = []map[string]interface{}{{
			"type":        "webrtc-datachannel",
			"priority":    float64(10),
			"sessionKind": "media",
			"signaling":   "aws-kvs",
			"channelName": config.VideoChannelName,
			"region":      config.AWSRegion,
			"label":       MCPWebRTCDataChannelLabel,
		}}
	} else {
		transports = []map[string]interface{}{{
			"type":                "mqtt-jsonrpc",
			"priority":            float64(100),
			"topicRoot":           topicRoot,
			"sessionTopicPattern": sessionTopicPattern,
		}}
	}
	return map[string]interface{}{
		"serviceId":          "mcp",
		"mcpProtocolVersion": MCPProtocolVersion,
		"protocolVersion":    MCPProtocolVersion,
		"serverInfo": map[string]interface{}{
			"name":    ServerName,
			"version": daemonVersion,
		},
		"serverVersion": daemonVersion,
		"control": map[string]interface{}{
			"mode": "read-only",
		},
		"transport":       transportMode,
		"descriptorTopic": descriptorTopic,
		"statusTopic":     statusTopic,
		"transports":      transports,
	}
}

func VideoDescriptor(config Config, daemonVersion string) map[string]interface{} {
	topicRoot, _ := BuildVideoTopicRoot(config.ThingID)
	descriptorTopic, _ := BuildVideoDescriptorTopic(config.ThingID)
	statusTopic, _ := BuildVideoStatusTopic(config.ThingID)
	return map[string]interface{}{
		"serviceId": VideoCapability,
		"serverInfo": map[string]interface{}{
			"name":    VideoCapability,
			"version": daemonVersion,
		},
		"topicRoot":       topicRoot,
		"descriptorTopic": descriptorTopic,
		"statusTopic":     statusTopic,
		"transport":       DefaultVideoTransport,
		"channelName":     config.VideoChannelName,
		"region":          config.AWSRegion,
		"codec": map[string]interface{}{
			"video": DefaultVideoCodec,
		},
		"serverVersion": daemonVersion,
	}
}

func DiscoverDefaultRouteAddresses() DefaultRouteAddresses {
	return DefaultRouteAddresses{
		IPv4: probeDefaultRouteIP("udp4", "8.8.8.8:80"),
		IPv6: probeDefaultRouteIP("udp6", "[2001:4860:4860::8888]:80"),
	}
}

func probeDefaultRouteIP(network, remote string) net.IP {
	conn, err := net.Dial(network, remote)
	if err != nil {
		return nil
	}
	defer conn.Close()
	if udp, ok := conn.LocalAddr().(*net.UDPAddr); ok {
		return udp.IP
	}
	return nil
}
