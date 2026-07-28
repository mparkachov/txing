// Package action implements the mac device action layer: the board-style
// AWS IoT publications (retained capability/video/mcp topics and named
// shadows), the BoardVideoBridge gRPC server, and a read-only MCP stub.
// It is a copied and trimmed sibling of devices/common/board/daemon/internal/daemon
// (no hardware worker, no cmd_vel actuators, no CloudWatch logging); the
// published wire contracts must stay aligned with the unit daemon and
// docs/contracts/board-video-bridge.md.
package action

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"
	"unicode"
)

const (
	SchemaVersion  = "2.0"
	BoardAdapterID = "dev.txing.mac.DaemonBoard"
	ServerName     = "txing-mac-daemon"

	BoardCapability = "board"
	MCPCapability   = "mcp"
	VideoCapability = "video"
	BoardShadowName = "board"
	MCPShadowName   = "mcp"
	VideoShadowName = "video"

	MCPProtocolVersion        = "2026-05-19"
	MCPWebRTCDataChannelLabel = "txing.mcp.v1"
	DefaultVideoCodec         = "h264"
	DefaultVideoTransport     = "aws-webrtc"
	VideoStatusStarting       = "starting"
	VideoStatusReady          = "ready"
	VideoStatusError          = "error"
	VideoStatusUnavailable    = "unavailable"
	MQTTPort                  = 8883

	DefaultCapabilityTTL = 150 * time.Second
	DefaultHeartbeat     = 60 * time.Second

	boardVideoBridgeProtocolVersion = "1"
)

// Config carries the action-layer runtime settings. It is assembled by
// macconfig from daemon.env; Enabled reports whether the AWS-facing
// fields required for the action layer are present, so a watch-layer
// only setup (no cert bundle yet) keeps working.
type Config struct {
	ThingID               string
	ClientID              string
	AWSRegion             string
	IoTEndpoint           string
	IoTCredentialEndpoint string
	IoTRoleAlias          string
	IoTCertFile           string
	IoTPrivateKeyFile     string
	IoTRootCAFile         string
	Capabilities          []string
	CapabilityTTL         time.Duration
	Heartbeat             time.Duration
	VideoChannelName      string
	BridgeSocketPath      string
	KVSMasterCommand      string
	KVSPreferIPv6         bool
	KVSDisableIPv4TURN    bool
}

func (c Config) Enabled() bool {
	return strings.TrimSpace(c.IoTEndpoint) != "" &&
		strings.TrimSpace(c.AWSRegion) != "" &&
		strings.TrimSpace(c.IoTCredentialEndpoint) != "" &&
		strings.TrimSpace(c.IoTRoleAlias) != ""
}

func (c Config) Validate() error {
	if err := ValidateTopicSegment(c.ThingID, "thing-id"); err != nil {
		return err
	}
	if err := ValidateTopicSegment(c.ClientID, "client-id"); err != nil {
		return err
	}
	if !strings.HasPrefix(c.ClientID, DefaultClientIDPrefix(c.ThingID)) {
		return fmt.Errorf("client-id must start with %q", DefaultClientIDPrefix(c.ThingID))
	}
	if err := validateEndpointHost(c.IoTEndpoint, "iot-endpoint"); err != nil {
		return err
	}
	if err := validateEndpointHost(c.IoTCredentialEndpoint, "iot-credential-endpoint"); err != nil {
		return err
	}
	if err := validateRoleAlias(c.IoTRoleAlias); err != nil {
		return err
	}
	if len(c.Capabilities) == 0 {
		return fmt.Errorf("action layer requires at least one capability")
	}
	for _, capability := range c.Capabilities {
		switch capability {
		case BoardCapability, MCPCapability, VideoCapability:
		default:
			return fmt.Errorf("unsupported capability %q; supported capabilities are %q, %q, %q", capability, BoardCapability, MCPCapability, VideoCapability)
		}
	}
	if c.CapabilityTTL <= 0 || c.Heartbeat <= 0 {
		return fmt.Errorf("capability TTL and heartbeat must be positive")
	}
	if c.VideoEnabled() {
		if strings.TrimSpace(c.VideoChannelName) == "" {
			return fmt.Errorf("video capability requires a video channel name")
		}
		if strings.TrimSpace(c.BridgeSocketPath) == "" {
			return fmt.Errorf("video capability requires a board video bridge socket path")
		}
	}
	for _, file := range []string{c.IoTCertFile, c.IoTPrivateKeyFile, c.IoTRootCAFile} {
		if strings.TrimSpace(file) == "" {
			return fmt.Errorf("IoT certificate, private key, and root CA files are required")
		}
	}
	return nil
}

func (c Config) VideoEnabled() bool {
	for _, capability := range c.Capabilities {
		if capability == VideoCapability {
			return true
		}
	}
	return false
}

func DefaultClientIDPrefix(thingName string) string {
	return sanitizeClientIDFragment(thingName) + "-daemon-"
}

func DefaultClientID(thingName string) string {
	return fmt.Sprintf("%s%d", DefaultClientIDPrefix(thingName), os.Getpid())
}

func DefaultCertFile(configDir string) string {
	return filepath.Join(configDir, "certificate.pem.crt")
}

func DefaultPrivateKeyFile(configDir string) string {
	return filepath.Join(configDir, "private.pem.key")
}

func DefaultRootCAFile(configDir string) string {
	return filepath.Join(configDir, "AmazonRootCA1.pem")
}

func ValidateTopicSegment(value, label string) error {
	if strings.TrimSpace(value) == "" {
		return fmt.Errorf("%s must not be empty", label)
	}
	if strings.ContainsAny(value, "/#+") {
		return fmt.Errorf("%s must not contain MQTT topic separators or wildcards", label)
	}
	return nil
}

func validateEndpointHost(value, label string) error {
	if err := ValidateTopicSegment(value, label); err != nil {
		return err
	}
	if strings.Contains(value, "://") || strings.ContainsAny(value, "/:") {
		return fmt.Errorf("%s must be an endpoint hostname without scheme, path, or port", label)
	}
	if strings.IndexFunc(value, unicode.IsSpace) >= 0 {
		return fmt.Errorf("%s must not contain whitespace", label)
	}
	return nil
}

func validateRoleAlias(value string) error {
	value = strings.TrimSpace(value)
	if value == "" {
		return fmt.Errorf("iot-role-alias must not be empty")
	}
	if len(value) > 128 {
		return fmt.Errorf("iot-role-alias must be 128 characters or fewer")
	}
	for _, ch := range value {
		if !(isASCIIAlnum(ch) || ch == '_' || ch == '=' || ch == ',' || ch == '@' || ch == '-') {
			return fmt.Errorf("iot-role-alias contains an unsupported character")
		}
	}
	return nil
}

func sanitizeClientIDFragment(thingName string) string {
	var b strings.Builder
	for _, ch := range thingName {
		if isASCIIAlnum(ch) || ch == '-' || ch == '_' {
			b.WriteRune(ch)
		} else {
			b.WriteRune('-')
		}
	}
	sanitized := strings.Trim(b.String(), "-")
	if sanitized == "" {
		sanitized = "mac"
	}
	const suffixReserve = 24
	if len(sanitized) > 128-suffixReserve {
		sanitized = sanitized[:128-suffixReserve]
	}
	return sanitized
}

func isASCIIAlnum(ch rune) bool {
	return (ch >= 'a' && ch <= 'z') || (ch >= 'A' && ch <= 'Z') || (ch >= '0' && ch <= '9')
}

func durationMillis(duration time.Duration) uint64 {
	if duration <= 0 {
		return 0
	}
	return uint64(duration / time.Millisecond)
}

func nowMillis() uint64 {
	return uint64(time.Now().UnixMilli())
}
