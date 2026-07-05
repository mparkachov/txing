package action

import (
	"context"
	"encoding/json"
	"strings"
	"testing"
	"time"
)

type recordedMessage struct {
	Topic                string
	Payload              map[string]interface{}
	Retain               bool
	MessageExpirySeconds *uint32
}

type recordingPublisher struct {
	messages []recordedMessage
}

func (p *recordingPublisher) Publish(_ context.Context, message PublishedMessage) error {
	decoded := map[string]interface{}{}
	_ = json.Unmarshal(message.Payload, &decoded)
	p.messages = append(p.messages, recordedMessage{
		Topic:                message.Topic,
		Payload:              decoded,
		Retain:               message.Retain,
		MessageExpirySeconds: message.MessageExpirySeconds,
	})
	return nil
}

func (p *recordingPublisher) byTopic(topic string) *recordedMessage {
	for index := range p.messages {
		if p.messages[index].Topic == topic {
			return &p.messages[index]
		}
	}
	return nil
}

func testConfig() Config {
	return Config{
		ThingID:               "mac-rcg3rg",
		ClientID:              "mac-rcg3rg-daemon-123",
		AWSRegion:             "eu-central-1",
		IoTEndpoint:           "example.iot.eu-central-1.amazonaws.com",
		IoTCredentialEndpoint: "example.credentials.iot.eu-central-1.amazonaws.com",
		IoTRoleAlias:          "txing-daemon-mac-rcg3rg",
		IoTCertFile:           "certificate.pem.crt",
		IoTPrivateKeyFile:     "private.pem.key",
		IoTRootCAFile:         "AmazonRootCA1.pem",
		Capabilities:          []string{BoardCapability, MCPCapability, VideoCapability},
		CapabilityTTL:         DefaultCapabilityTTL,
		Heartbeat:             DefaultHeartbeat,
		VideoChannelName:      "mac-rcg3rg-board-video",
		BridgeSocketPath:      "/tmp/txing-mac/board-video-bridge.sock",
		KVSPreferIPv6:         true,
	}
}

func TestConfigValidateAndEnabled(t *testing.T) {
	config := testConfig()
	if err := config.Validate(); err != nil {
		t.Fatalf("Validate: %v", err)
	}
	if !config.Enabled() {
		t.Fatal("config with AWS fields must report enabled")
	}
	disabled := config
	disabled.IoTEndpoint = ""
	if disabled.Enabled() {
		t.Fatal("config without endpoint must report disabled")
	}
	badClient := config
	badClient.ClientID = "mac-rcg3rg"
	if err := badClient.Validate(); err == nil {
		t.Fatal("client id equal to the thing name must be rejected (collides with the rig device session)")
	}
}

func TestPublishOnlineContract(t *testing.T) {
	publisher := &recordingPublisher{}
	state := &sessionState{config: testConfig(), version: "0.0.0-dev", caps: &capabilityPublisher{capabilities: testConfig().Capabilities}}
	observedAt := uint64(1_776_000_000_000)
	if err := state.publishOnline(context.Background(), publisher, observedAt); err != nil {
		t.Fatalf("publishOnline: %v", err)
	}

	board := publisher.byTopic("$aws/things/mac-rcg3rg/shadow/name/board/update")
	if board == nil || board.Retain {
		t.Fatalf("board shadow update missing or retained: %+v", board)
	}
	reported := board.Payload["state"].(map[string]interface{})["reported"].(map[string]interface{})
	if reported["power"] != true {
		t.Fatalf("board shadow must report power=true online: %v", reported)
	}

	descriptor := publisher.byTopic("txings/mac-rcg3rg/mcp/descriptor")
	if descriptor == nil || !descriptor.Retain || descriptor.MessageExpirySeconds != nil {
		t.Fatalf("mcp descriptor must be retained without expiry: %+v", descriptor)
	}
	if descriptor.Payload["serverInfo"].(map[string]interface{})["name"] != ServerName {
		t.Fatalf("mcp descriptor server name: %v", descriptor.Payload["serverInfo"])
	}
	if descriptor.Payload["transport"] != "mqtt-jsonrpc" {
		t.Fatalf("mcp transport must start as mqtt-jsonrpc: %v", descriptor.Payload["transport"])
	}

	mcpStatus := publisher.byTopic("txings/mac-rcg3rg/mcp/status")
	if mcpStatus == nil || !mcpStatus.Retain || mcpStatus.MessageExpirySeconds == nil || *mcpStatus.MessageExpirySeconds != 150 {
		t.Fatalf("mcp status must be retained with TTL expiry: %+v", mcpStatus)
	}
	if mcpStatus.Payload["available"] != true || mcpStatus.Payload["activeControl"] != nil {
		t.Fatalf("mcp status shape: %v", mcpStatus.Payload)
	}

	videoStatus := publisher.byTopic("txings/mac-rcg3rg/video/status")
	if videoStatus == nil || !videoStatus.Retain || videoStatus.MessageExpirySeconds == nil {
		t.Fatalf("video status must be retained with expiry: %+v", videoStatus)
	}
	if videoStatus.Payload["ready"] != false || videoStatus.Payload["status"] != VideoStatusStarting {
		t.Fatalf("video status must start not ready: %v", videoStatus.Payload)
	}
	videoDescriptor := publisher.byTopic("txings/mac-rcg3rg/video/descriptor")
	if videoDescriptor == nil || videoDescriptor.Payload["channelName"] != "mac-rcg3rg-board-video" {
		t.Fatalf("video descriptor: %+v", videoDescriptor)
	}

	caps := publisher.byTopic("txings/mac-rcg3rg/capability/v2/state")
	if caps == nil || !caps.Retain || caps.MessageExpirySeconds == nil {
		t.Fatalf("capability state must be retained with expiry: %+v", caps)
	}
	if caps.Payload["adapterId"] != BoardAdapterID || caps.Payload["schemaVersion"] != SchemaVersion {
		t.Fatalf("capability state identity: %v", caps.Payload)
	}
	capabilities := caps.Payload["capabilities"].(map[string]interface{})
	if capabilities["board"] != true || capabilities["mcp"] != true || capabilities["video"] != false {
		t.Fatalf("online capabilities must be board+mcp true, video false: %v", capabilities)
	}
	if caps.Payload["expiresAtMs"] != float64(observedAt+150_000) {
		t.Fatalf("capability expiresAtMs: %v", caps.Payload["expiresAtMs"])
	}
}

func TestPublishOfflineContract(t *testing.T) {
	publisher := &recordingPublisher{}
	state := &sessionState{config: testConfig(), version: "0.0.0-dev", caps: &capabilityPublisher{capabilities: testConfig().Capabilities}}
	if err := state.publishOffline(context.Background(), publisher, 1_776_000_000_000); err != nil {
		t.Fatalf("publishOffline: %v", err)
	}
	board := publisher.byTopic("$aws/things/mac-rcg3rg/shadow/name/board/update")
	reported := board.Payload["state"].(map[string]interface{})["reported"].(map[string]interface{})
	if reported["power"] != false {
		t.Fatalf("board shadow must report power=false offline: %v", reported)
	}
	mcpStatus := publisher.byTopic("txings/mac-rcg3rg/mcp/status")
	if mcpStatus.Payload["available"] != false || mcpStatus.Payload["status"] != "offline" {
		t.Fatalf("mcp status must be offline: %v", mcpStatus.Payload)
	}
	videoStatus := publisher.byTopic("txings/mac-rcg3rg/video/status")
	if videoStatus.Payload["available"] != false || videoStatus.Payload["status"] != VideoStatusUnavailable {
		t.Fatalf("video status must be unavailable: %v", videoStatus.Payload)
	}
	caps := publisher.byTopic("txings/mac-rcg3rg/capability/v2/state")
	capabilities := caps.Payload["capabilities"].(map[string]interface{})
	if capabilities["board"] != false || capabilities["mcp"] != false || capabilities["video"] != false {
		t.Fatalf("offline capabilities must all be false: %v", capabilities)
	}
}

func TestVideoReadyRaisesCapabilityAndSwitchesTransport(t *testing.T) {
	publisher := &recordingPublisher{}
	state := &sessionState{config: testConfig(), version: "0.0.0-dev", caps: &capabilityPublisher{capabilities: testConfig().Capabilities}}
	if err := state.publishOnline(context.Background(), publisher, 1); err != nil {
		t.Fatalf("publishOnline: %v", err)
	}
	publisher.messages = nil
	if err := state.handleVideoEvent(context.Background(), publisher, VideoWorkerEvent{Kind: VideoWorkerReady}, 2); err != nil {
		t.Fatalf("handleVideoEvent: %v", err)
	}
	caps := publisher.byTopic("txings/mac-rcg3rg/capability/v2/state")
	if caps.Payload["capabilities"].(map[string]interface{})["video"] != true {
		t.Fatalf("video capability must be true after READY: %v", caps.Payload)
	}
	descriptor := publisher.byTopic("txings/mac-rcg3rg/mcp/descriptor")
	if descriptor == nil || descriptor.Payload["transport"] != "webrtc-datachannel" {
		t.Fatalf("mcp transport must switch to webrtc when video ready: %+v", descriptor)
	}
}

func TestMCPReadOnlyStub(t *testing.T) {
	video := VideoRuntimeStarting(1)
	initialize := HandleMCPJSONRPC(map[string]interface{}{"jsonrpc": "2.0", "id": float64(1), "method": "initialize"}, "0.0.0-dev", video)
	result := initialize["result"].(map[string]interface{})
	if result["protocolVersion"] != MCPProtocolVersion {
		t.Fatalf("initialize protocol version: %v", result)
	}

	list := HandleMCPJSONRPC(map[string]interface{}{"jsonrpc": "2.0", "id": float64(2), "method": "tools/list"}, "0.0.0-dev", video)
	tools := list["result"].(map[string]interface{})["tools"].([]map[string]string)
	if len(tools) != 2 {
		t.Fatalf("read-only stub must expose exactly two tools: %v", tools)
	}
	for _, tool := range tools {
		if strings.HasPrefix(tool["name"], "cmd_vel") || tool["name"] == "control.activate" {
			t.Fatalf("actuator tool leaked into read-only stub: %v", tool)
		}
	}

	call := HandleMCPJSONRPC(map[string]interface{}{
		"jsonrpc": "2.0", "id": float64(3), "method": "tools/call",
		"params": map[string]interface{}{"name": "robot.get_state"},
	}, "0.0.0-dev", video)
	if call["error"] != nil {
		t.Fatalf("robot.get_state must succeed: %v", call)
	}

	actuator := HandleMCPJSONRPC(map[string]interface{}{
		"jsonrpc": "2.0", "id": float64(4), "method": "tools/call",
		"params": map[string]interface{}{"name": "cmd_vel.publish"},
	}, "0.0.0-dev", video)
	if actuator["error"] == nil {
		t.Fatal("actuator tools must be rejected")
	}

	if response := HandleMCPJSONRPC(map[string]interface{}{"jsonrpc": "2.0", "method": "notifications/initialized"}, "0.0.0-dev", video); response != nil {
		t.Fatalf("notifications must not produce a response: %v", response)
	}
}

func TestControllerLifecycleWithoutConfiguration(t *testing.T) {
	var warnings []string
	controller := NewController(Config{}, false, "0.0.0-dev", func(level, message string) {
		if level == "warning" {
			warnings = append(warnings, message)
		}
	})
	controller.SetTarget(2)
	if controller.Running() {
		t.Fatal("unconfigured controller must not start")
	}
	if len(warnings) != 1 {
		t.Fatalf("unconfigured start must warn once: %v", warnings)
	}
	controller.SetTarget(4)
	controller.Shutdown()
}

func TestRetainedExpiryRounding(t *testing.T) {
	if seconds := retainedExpirySeconds(150 * time.Second); *seconds != 150 {
		t.Fatalf("expiry for 150s: %d", *seconds)
	}
	if seconds := retainedExpirySeconds(1500 * time.Millisecond); *seconds != 2 {
		t.Fatalf("expiry must round up: %d", *seconds)
	}
}
