package daemon

import (
	"bytes"
	"context"
	"encoding/binary"
	"encoding/json"
	"errors"
	"fmt"
	"net"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"sync"
	"testing"
	"time"

	boardvideov1 "github.com/mparkachov/txing/devices/unit/daemon/internal/proto/boardvideov1"
	hardwarev1 "github.com/mparkachov/txing/devices/unit/daemon/internal/proto/hardwarev1"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"
)

type fakePublisher struct {
	mu       sync.Mutex
	messages []PublishedMessage
	fail     bool
}

func (p *fakePublisher) Publish(_ context.Context, message PublishedMessage) error {
	if p.fail {
		return errors.New("publish failed")
	}
	p.mu.Lock()
	defer p.mu.Unlock()
	p.messages = append(p.messages, message)
	return nil
}

func (p *fakePublisher) Messages() []PublishedMessage {
	p.mu.Lock()
	defer p.mu.Unlock()
	return append([]PublishedMessage(nil), p.messages...)
}

func (p *fakePublisher) Clear() {
	p.mu.Lock()
	defer p.mu.Unlock()
	p.messages = nil
}

type fakeHardwareClient struct {
	mu     sync.Mutex
	calls  []string
	motion DriveState
	fail   bool
}

func (h *fakeHardwareClient) GetStatus(context.Context) (HardwareStatusSnapshot, error) {
	h.mu.Lock()
	defer h.mu.Unlock()
	if h.fail {
		return HardwareStatusSnapshot{}, errors.New("hardware worker unavailable")
	}
	return HardwareStatusSnapshot{ActuatorReady: true, Motion: h.motion}, nil
}

func (h *fakeHardwareClient) ApplyVelocity(_ context.Context, _ Twist, deadlineUnixMS uint64) (DriveState, error) {
	h.mu.Lock()
	defer h.mu.Unlock()
	if h.fail {
		return DriveState{}, errors.New("hardware worker unavailable")
	}
	h.calls = append(h.calls, "apply")
	h.motion = DriveState{LeftSpeed: 50, RightSpeed: 50, Sequence: h.motion.Sequence + 1}
	return h.motion, nil
}

func (h *fakeHardwareClient) Stop(context.Context) (DriveState, error) {
	h.mu.Lock()
	defer h.mu.Unlock()
	if h.fail {
		return DriveState{}, errors.New("hardware worker unavailable")
	}
	h.calls = append(h.calls, "stop")
	h.motion = DriveState{Sequence: h.motion.Sequence + 1}
	return h.motion, nil
}

func (h *fakeHardwareClient) Calls() []string {
	h.mu.Lock()
	defer h.mu.Unlock()
	return append([]string(nil), h.calls...)
}

func testRuntimeConfig() RuntimeConfig {
	return RuntimeConfig{
		ThingID:                    "unit-local",
		AWSRegion:                  "eu-central-1",
		IoTEndpoint:                "example.iot.eu-central-1.amazonaws.com",
		IoTCredentialEndpoint:      "example.credentials.iot.eu-central-1.amazonaws.com",
		IoTRoleAlias:               "unit-daemon-role-alias",
		IoTCertFile:                "/home/txing/.config/txing/unit-daemon/certificate.pem.crt",
		IoTPrivateKeyFile:          "/home/txing/.config/txing/unit-daemon/private.pem.key",
		IoTRootCAFile:              "/home/txing/.config/txing/unit-daemon/AmazonRootCA1.pem",
		ClientID:                   "unit-local-daemon-test",
		Capabilities:               []string{BoardCapability, MCPCapability, VideoCapability},
		CapabilityTTL:              150 * time.Second,
		Heartbeat:                  60 * time.Second,
		KVSMasterCommand:           DefaultKVSMasterCommand,
		MCPWebRTCSocketPath:        DefaultMCPWebRTCSocketPath,
		BoardVideoBridgeSocketPath: DefaultBoardVideoBridgeSocket,
		KVSPreferIPv6:              true,
		KVSDisableIPv4TURN:         false,
		VideoRegion:                "eu-central-1",
		VideoChannelName:           "unit-local-board-video",
		HardwareWorkerSocketPath:   DefaultHardwareSocketPath,
		HardwareWorkerTimeout:      time.Duration(DefaultHardwareTimeoutMillis) * time.Millisecond,
	}
}

func testRuntimeState(t *testing.T, hardware HardwareClient) *RuntimeState {
	t.Helper()
	if hardware == nil {
		hardware = &fakeHardwareClient{}
	}
	state, err := NewRuntimeStateWithHardware(testRuntimeConfig(), hardware)
	if err != nil {
		t.Fatalf("runtime state: %v", err)
	}
	return state
}

func TestRuntimePublishesBoardShadowMCPVideoAndCapabilityPayloads(t *testing.T) {
	ctx := context.Background()
	publisher := &fakePublisher{}
	state := testRuntimeState(t, nil)

	if err := state.PublishOnline(ctx, publisher, DefaultRouteAddresses{IPv4: net.IPv4(10, 0, 0, 5)}, 10); err != nil {
		t.Fatalf("publish online: %v", err)
	}
	if err := state.RefreshCapabilities(ctx, publisher, 20); err != nil {
		t.Fatalf("refresh capabilities: %v", err)
	}
	if err := state.PublishOffline(ctx, publisher, 30); err != nil {
		t.Fatalf("publish offline: %v", err)
	}

	messages := publisher.Messages()
	if len(messages) != 17 {
		t.Fatalf("message count mismatch: %d", len(messages))
	}
	expectedTopics := []string{
		"$aws/things/unit-local/shadow/name/board/update",
		"txings/unit-local/mcp/descriptor",
		"txings/unit-local/mcp/status",
		"$aws/things/unit-local/shadow/name/mcp/update",
		"txings/unit-local/video/descriptor",
		"txings/unit-local/video/status",
		"$aws/things/unit-local/shadow/name/video/update",
		"txings/unit-local/capability/v2/state",
		"txings/unit-local/mcp/status",
		"$aws/things/unit-local/shadow/name/mcp/update",
		"txings/unit-local/capability/v2/state",
		"$aws/things/unit-local/shadow/name/board/update",
		"txings/unit-local/mcp/status",
		"$aws/things/unit-local/shadow/name/mcp/update",
		"txings/unit-local/video/status",
		"$aws/things/unit-local/shadow/name/video/update",
		"txings/unit-local/capability/v2/state",
	}
	for i, topic := range expectedTopics {
		if messages[i].Topic != topic {
			t.Fatalf("topic[%d] mismatch: %q", i, messages[i].Topic)
		}
	}
	expectedExpiry := uint32(150)
	assertPublishRetention(t, messages[0], false, nil)
	assertPublishRetention(t, messages[1], true, nil)
	assertPublishRetention(t, messages[2], true, &expectedExpiry)
	assertPublishRetention(t, messages[4], true, nil)
	assertPublishRetention(t, messages[5], true, &expectedExpiry)
	assertPublishRetention(t, messages[7], true, &expectedExpiry)
	assertPublishRetention(t, messages[8], true, &expectedExpiry)
	assertPublishRetention(t, messages[10], true, &expectedExpiry)
	assertPublishRetention(t, messages[12], true, &expectedExpiry)
	assertPublishRetention(t, messages[14], true, &expectedExpiry)
	assertPublishRetention(t, messages[16], true, &expectedExpiry)
	var descriptor map[string]interface{}
	mustJSON(t, messages[1].Payload, &descriptor)
	if descriptor["protocolVersion"] != MCPProtocolVersion || descriptor["transport"] != string(MCPTransportMQTT) {
		t.Fatalf("unexpected MCP descriptor: %#v", descriptor)
	}
	var videoStatus map[string]interface{}
	mustJSON(t, messages[5].Payload, &videoStatus)
	if videoStatus["available"] != true || videoStatus["ready"] != false || videoStatus["status"] != VideoStatusStarting {
		t.Fatalf("unexpected video status: %#v", videoStatus)
	}
	var third CapabilityStatePayload
	mustJSON(t, messages[16].Payload, &third)
	if third.Seq != 3 || third.Capabilities[BoardCapability] || third.Capabilities[MCPCapability] || third.Capabilities[VideoCapability] {
		t.Fatalf("unexpected offline capability payload: %#v", third)
	}
}

func assertPublishRetention(t *testing.T, message PublishedMessage, retain bool, expiry *uint32) {
	t.Helper()
	if message.Retain != retain {
		t.Fatalf("publish %s retain = %t, want %t", message.Topic, message.Retain, retain)
	}
	if expiry == nil {
		if message.MessageExpirySeconds != nil {
			t.Fatalf("publish %s expiry = %d, want nil", message.Topic, *message.MessageExpirySeconds)
		}
		return
	}
	if message.MessageExpirySeconds == nil || *message.MessageExpirySeconds != *expiry {
		if message.MessageExpirySeconds == nil {
			t.Fatalf("publish %s expiry = nil, want %d", message.Topic, *expiry)
		}
		t.Fatalf("publish %s expiry = %d, want %d", message.Topic, *message.MessageExpirySeconds, *expiry)
	}
}

func TestRetainedDynamicExpiryUsesConfiguredCapabilityTTL(t *testing.T) {
	ctx := context.Background()
	publisher := &fakePublisher{}
	config := testRuntimeConfig()
	config.CapabilityTTL = 42 * time.Second
	state, err := NewRuntimeStateWithHardware(config, &fakeHardwareClient{})
	if err != nil {
		t.Fatalf("runtime state: %v", err)
	}
	if err := state.PublishOnline(ctx, publisher, DefaultRouteAddresses{}, 10); err != nil {
		t.Fatalf("publish online: %v", err)
	}

	messages := publisher.Messages()
	expectedExpiry := uint32(42)
	mcpDescriptor := findPublishedMessage(t, messages, "txings/unit-local/mcp/descriptor")
	mcpStatus := findPublishedMessage(t, messages, "txings/unit-local/mcp/status")
	videoDescriptor := findPublishedMessage(t, messages, "txings/unit-local/video/descriptor")
	videoStatus := findPublishedMessage(t, messages, "txings/unit-local/video/status")
	capabilityState := findPublishedMessage(t, messages, "txings/unit-local/capability/v2/state")

	assertPublishRetention(t, mcpDescriptor, true, nil)
	assertPublishRetention(t, mcpStatus, true, &expectedExpiry)
	assertPublishRetention(t, videoDescriptor, true, nil)
	assertPublishRetention(t, videoStatus, true, &expectedExpiry)
	assertPublishRetention(t, capabilityState, true, &expectedExpiry)
}

func findPublishedMessage(t *testing.T, messages []PublishedMessage, topic string) PublishedMessage {
	t.Helper()
	for _, message := range messages {
		if message.Topic == topic {
			return message
		}
	}
	t.Fatalf("missing published message %s", topic)
	return PublishedMessage{}
}

func TestMQTTConnectPacketUsesMQTT5CleanStartAndSessionExpiry(t *testing.T) {
	packetType, flags, payload, err := readMQTTPacket(bytes.NewReader(mqttPacketConnect("unit-local")))
	if err != nil {
		t.Fatalf("read connect packet: %v", err)
	}
	if packetType != 1 || flags != 0 {
		t.Fatalf("packet type=%d flags=%d, want CONNECT", packetType, flags)
	}
	if len(payload) < 17 {
		t.Fatalf("connect payload too short: %x", payload)
	}
	if string(payload[2:6]) != "MQTT" || payload[6] != 5 {
		t.Fatalf("connect protocol = %x", payload[:7])
	}
	if payload[7] != 0x02 {
		t.Fatalf("connect flags = %x, want clean start", payload[7])
	}
	if keepAlive := binary.BigEndian.Uint16(payload[8:10]); keepAlive != mqttKeepAliveSeconds {
		t.Fatalf("keepalive = %d, want %d", keepAlive, mqttKeepAliveSeconds)
	}
	propertyLength, propertyLengthBytes, ok := readMQTTVariableByteInteger(payload[10:])
	if !ok || propertyLength != 5 {
		t.Fatalf("connect properties length = %d bytes=%d ok=%t", propertyLength, propertyLengthBytes, ok)
	}
	propertyOffset := 10 + propertyLengthBytes
	if payload[propertyOffset] != 0x11 || binary.BigEndian.Uint32(payload[propertyOffset+1:propertyOffset+5]) != 0 {
		t.Fatalf("connect session expiry property = %x", payload[propertyOffset:propertyOffset+5])
	}
	clientIDOffset := propertyOffset + propertyLength
	if clientIDOffset+2 > len(payload) {
		t.Fatalf("connect payload missing client id: %x", payload)
	}
	clientIDLength := int(binary.BigEndian.Uint16(payload[clientIDOffset : clientIDOffset+2]))
	clientIDStart := clientIDOffset + 2
	if clientIDStart+clientIDLength > len(payload) || string(payload[clientIDStart:clientIDStart+clientIDLength]) != "unit-local" {
		t.Fatalf("connect client id payload = %x", payload[clientIDOffset:])
	}
}

func TestMQTTPublishPacketEncodesMQTT5MessageExpiry(t *testing.T) {
	expiry := uint32(150)
	packetType, flags, payload, err := readMQTTPacket(bytes.NewReader(mqttPacketPublish(9, "txings/unit-local/video/status", []byte("status"), true, &expiry)))
	if err != nil {
		t.Fatalf("read publish packet: %v", err)
	}
	if packetType != 3 || flags != 0x03 {
		t.Fatalf("packet type=%d flags=%d, want retained QoS1 PUBLISH", packetType, flags)
	}
	topicLen := int(binary.BigEndian.Uint16(payload[:2]))
	topicEnd := 2 + topicLen
	if string(payload[2:topicEnd]) != "txings/unit-local/video/status" {
		t.Fatalf("topic = %q", payload[2:topicEnd])
	}
	packetIDOffset := topicEnd
	if binary.BigEndian.Uint16(payload[packetIDOffset:packetIDOffset+2]) != 9 {
		t.Fatalf("packet id payload = %x", payload[packetIDOffset:packetIDOffset+2])
	}
	propertyOffset := packetIDOffset + 2
	propertyLength, propertyLengthBytes, ok := readMQTTVariableByteInteger(payload[propertyOffset:])
	if !ok || propertyLength != 5 {
		t.Fatalf("publish properties length = %d bytes=%d ok=%t", propertyLength, propertyLengthBytes, ok)
	}
	propertyStart := propertyOffset + propertyLengthBytes
	if payload[propertyStart] != 0x02 || binary.BigEndian.Uint32(payload[propertyStart+1:propertyStart+5]) != expiry {
		t.Fatalf("publish message expiry property = %x", payload[propertyStart:propertyStart+5])
	}
	bodyStart := propertyStart + propertyLength
	if string(payload[bodyStart:]) != "status" {
		t.Fatalf("publish payload = %q", payload[bodyStart:])
	}

	topic, packetID, body, qos, ok := parseMQTTPublish(flags, payload)
	if !ok || topic != "txings/unit-local/video/status" || packetID != 9 || qos != 1 || string(body) != "status" {
		t.Fatalf("parsed publish topic=%q packetID=%d qos=%d ok=%t body=%q", topic, packetID, qos, ok, body)
	}
}

func TestMQTTSubscribeAndPubAckUseMQTT5Properties(t *testing.T) {
	packetType, flags, payload, err := readMQTTPacket(bytes.NewReader(mqttPacketSubscribe(4, "txings/unit-local/mcp/session/+/c2s")))
	if err != nil {
		t.Fatalf("read subscribe packet: %v", err)
	}
	if packetType != 8 || flags != 0x02 {
		t.Fatalf("packet type=%d flags=%d, want SUBSCRIBE", packetType, flags)
	}
	if binary.BigEndian.Uint16(payload[:2]) != 4 || payload[2] != 0 {
		t.Fatalf("subscribe variable header = %x", payload[:3])
	}
	if got := mqttPacketPubAck(4); !bytes.Equal(got, []byte{0x40, 0x04, 0x00, 0x04, 0x00, 0x00}) {
		t.Fatalf("puback = %x", got)
	}
	if !mqttConnAckAccepted([]byte{0x00, 0x00, 0x00}) {
		t.Fatalf("MQTT5 CONNACK with empty properties should be accepted")
	}
}

func TestVideoEventsSwitchMCPTransportAndPublishState(t *testing.T) {
	ctx := context.Background()
	publisher := &fakePublisher{}
	state := testRuntimeState(t, nil)
	if err := state.PublishOnline(ctx, publisher, DefaultRouteAddresses{}, 10); err != nil {
		t.Fatal(err)
	}
	publisher.Clear()

	if err := state.HandleVideoEvent(ctx, publisher, VideoWorkerEvent{Kind: VideoWorkerReady, WorkerVersion: "test"}, 100); err != nil {
		t.Fatalf("handle ready: %v", err)
	}
	messages := publisher.Messages()
	if len(messages) != 6 {
		t.Fatalf("ready message count mismatch: %d", len(messages))
	}
	var descriptor map[string]interface{}
	mustJSON(t, messages[0].Payload, &descriptor)
	if descriptor["transport"] != string(MCPTransportWebRTCDataChannel) {
		t.Fatalf("expected WebRTC MCP descriptor, got %#v", descriptor)
	}
	var capability CapabilityStatePayload
	mustJSON(t, messages[len(messages)-1].Payload, &capability)
	if !capability.Capabilities[VideoCapability] {
		t.Fatalf("video capability should be available after ready: %#v", capability)
	}
}

func TestMQTTMCPRequestsAreRejectedWhileWebRTCOnlyIsAdvertised(t *testing.T) {
	ctx := context.Background()
	publisher := &fakePublisher{}
	state := testRuntimeState(t, nil)
	if err := state.HandleVideoEvent(ctx, publisher, VideoWorkerEvent{Kind: VideoWorkerReady}, 100); err != nil {
		t.Fatal(err)
	}
	publisher.Clear()

	topic := "txings/unit-local/mcp/session/session-a/c2s"
	request := []byte(`{"jsonrpc":"2.0","id":1,"method":"initialize"}`)
	if err := state.HandleMQTTEvent(ctx, publisher, RuntimeMqttEvent{Topic: topic, Payload: request}, 110); err != nil {
		t.Fatalf("handle mqtt mcp: %v", err)
	}
	messages := publisher.Messages()
	if len(messages) != 1 {
		t.Fatalf("expected one rejection response, got %d", len(messages))
	}
	var response map[string]interface{}
	mustJSON(t, messages[0].Payload, &response)
	errObj := response["error"].(map[string]interface{})
	if errObj["code"].(float64) != -32000 {
		t.Fatalf("unexpected rejection: %#v", response)
	}
}

func TestMCPActiveControlDelegatesVelocityAndCleansUp(t *testing.T) {
	ctx := context.Background()
	publisher := &fakePublisher{}
	hardware := &fakeHardwareClient{}
	state := testRuntimeState(t, hardware)

	activate := callMCP(t, ctx, state, publisher, "session-a", `{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"control.activate","arguments":{"actor":"operator"}}}`, 100)
	active := activate["result"].(map[string]interface{})["structuredContent"].(map[string]interface{})["activeControl"].(map[string]interface{})
	epoch := uint64(active["epoch"].(float64))
	if epoch != 1 {
		t.Fatalf("unexpected epoch: %#v", activate)
	}
	publish := callMCP(t, ctx, state, publisher, "session-a", `{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"cmd_vel.publish","arguments":{"epoch":1,"twist":{"linear":{"x":1,"y":0,"z":0},"angular":{"x":0,"y":0,"z":0.5}}}}}`, 120)
	motion := publish["result"].(map[string]interface{})["structuredContent"].(map[string]interface{})["motion"].(map[string]interface{})
	if motion["leftSpeed"].(float64) != 50 || !reflect.DeepEqual(hardware.Calls(), []string{"apply"}) {
		t.Fatalf("cmd_vel publish did not delegate: response=%#v calls=%v", publish, hardware.Calls())
	}
	if err := state.TickWatchdogs(ctx, publisher, 5201); err != nil {
		t.Fatalf("tick watchdogs: %v", err)
	}
	if !reflect.DeepEqual(hardware.Calls(), []string{"apply", "stop"}) {
		t.Fatalf("expected watchdog stop: %v", hardware.Calls())
	}
}

func TestMCPActiveControlRejectsBusyAndStaleEpoch(t *testing.T) {
	ctx := context.Background()
	publisher := &fakePublisher{}
	state := testRuntimeState(t, nil)
	_ = callMCP(t, ctx, state, publisher, "session-a", `{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"control.activate"}}`, 100)
	busy := callMCP(t, ctx, state, publisher, "session-b", `{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"control.activate"}}`, 110)
	if busy["error"].(map[string]interface{})["code"].(float64) != -32012 {
		t.Fatalf("expected active busy: %#v", busy)
	}
	stale := callMCP(t, ctx, state, publisher, "session-a", `{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"control.renew_active","arguments":{"epoch":9}}}`, 120)
	if stale["error"].(map[string]interface{})["code"].(float64) != -32013 {
		t.Fatalf("expected stale epoch: %#v", stale)
	}
}

func TestMCPMultiSessionActiveControlPolicy(t *testing.T) {
	ctx := context.Background()
	publisher := &fakePublisher{}
	hardware := &fakeHardwareClient{}
	state := testRuntimeState(t, hardware)

	sessionAState := mcpStructuredContent(callMCP(t, ctx, state, publisher, "session-a", `{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"robot.get_state"}}`, 100))
	sessionBControl := mcpStructuredContent(callMCP(t, ctx, state, publisher, "session-b", `{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"control.get_state"}}`, 110))
	if sessionAState["control"].(map[string]interface{})["activeOwnerSessionId"] != nil {
		t.Fatalf("read-only robot.get_state should not acquire active control: %#v", sessionAState)
	}
	if sessionBControl["activeOwnerSessionId"] != nil {
		t.Fatalf("read-only control.get_state should not acquire active control: %#v", sessionBControl)
	}
	if len(hardware.Calls()) != 0 {
		t.Fatalf("read-only MCP calls should not touch actuators: %v", hardware.Calls())
	}

	sessionAActive := mcpStructuredContent(callMCP(t, ctx, state, publisher, "session-a", `{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"control.activate","arguments":{"actor":"operator-a"}}}`, 120))["activeControl"].(map[string]interface{})
	if sessionAActive["sessionId"] != "session-a" || sessionAActive["actor"] != "operator-a" || sessionAActive["epoch"].(float64) != 1 {
		t.Fatalf("unexpected session-a active control: %#v", sessionAActive)
	}
	statusAfterActivate := latestMCPStatus(t, publisher.Messages())
	activeAfterActivate := statusAfterActivate["activeControl"].(map[string]interface{})
	if activeAfterActivate["sessionId"] != "session-a" || activeAfterActivate["epoch"].(float64) != 1 {
		t.Fatalf("status did not publish session-a ownership: %#v", statusAfterActivate)
	}

	nonOwnerPublish := callMCP(t, ctx, state, publisher, "session-b", `{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"cmd_vel.publish","arguments":{"epoch":1,"twist":{"linear":{"x":1,"y":0,"z":0},"angular":{"x":0,"y":0,"z":0}}}}}`, 130)
	if nonOwnerPublish["error"].(map[string]interface{})["code"].(float64) != -32011 {
		t.Fatalf("expected non-owner actuator call to be rejected as unauthorized: %#v", nonOwnerPublish)
	}
	if len(hardware.Calls()) != 0 {
		t.Fatalf("non-owner actuator call should not touch hardware: %v", hardware.Calls())
	}

	sessionAPublish := mcpStructuredContent(callMCP(t, ctx, state, publisher, "session-a", `{"jsonrpc":"2.0","id":5,"method":"tools/call","params":{"name":"cmd_vel.publish","arguments":{"epoch":1,"twist":{"linear":{"x":1,"y":0,"z":0},"angular":{"x":0,"y":0,"z":0.5}}}}}`, 140))
	if sessionAPublish["motion"].(map[string]interface{})["leftSpeed"].(float64) != 50 {
		t.Fatalf("active owner actuator call should publish motion: %#v", sessionAPublish)
	}
	if !reflect.DeepEqual(hardware.Calls(), []string{"apply"}) {
		t.Fatalf("expected one active-owner apply call: %v", hardware.Calls())
	}

	sessionBActive := mcpStructuredContent(callMCP(t, ctx, state, publisher, "session-b", `{"jsonrpc":"2.0","id":6,"method":"tools/call","params":{"name":"control.activate","arguments":{"actor":"operator-b","takeover":true}}}`, 150))["activeControl"].(map[string]interface{})
	if sessionBActive["sessionId"] != "session-b" || sessionBActive["actor"] != "operator-b" || sessionBActive["epoch"].(float64) != 2 {
		t.Fatalf("unexpected session-b takeover active control: %#v", sessionBActive)
	}
	if !reflect.DeepEqual(hardware.Calls(), []string{"apply", "stop"}) {
		t.Fatalf("takeover should stop previous motion: %v", hardware.Calls())
	}
	statusAfterTakeover := latestMCPStatus(t, publisher.Messages())
	activeAfterTakeover := statusAfterTakeover["activeControl"].(map[string]interface{})
	if activeAfterTakeover["sessionId"] != "session-b" || activeAfterTakeover["epoch"].(float64) != 2 {
		t.Fatalf("status did not publish session-b takeover: %#v", statusAfterTakeover)
	}

	oldEpochPublish := callMCP(t, ctx, state, publisher, "session-a", `{"jsonrpc":"2.0","id":7,"method":"tools/call","params":{"name":"cmd_vel.publish","arguments":{"epoch":1,"twist":{"linear":{"x":1,"y":0,"z":0},"angular":{"x":0,"y":0,"z":0}}}}}`, 160)
	if oldEpochPublish["error"].(map[string]interface{})["code"].(float64) != -32011 {
		t.Fatalf("expected old epoch to be rejected after takeover: %#v", oldEpochPublish)
	}
	if !reflect.DeepEqual(hardware.Calls(), []string{"apply", "stop"}) {
		t.Fatalf("old epoch publish should not touch hardware: %v", hardware.Calls())
	}
}

func TestMCPActiveControlSurvivesObserverReconnectAndVideoReadinessChurn(t *testing.T) {
	ctx := context.Background()
	publisher := &fakePublisher{}
	hardware := &fakeHardwareClient{}
	state := testRuntimeState(t, hardware)

	if err := state.HandleVideoEvent(ctx, publisher, VideoWorkerEvent{Kind: VideoWorkerReady}, 100); err != nil {
		t.Fatalf("handle video ready: %v", err)
	}
	sessionAActive := mcpStructuredContent(callMCP(t, ctx, state, publisher, "session-a", `{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"control.activate","arguments":{"actor":"operator-a"}}}`, 110))["activeControl"].(map[string]interface{})
	if sessionAActive["sessionId"] != "session-a" || sessionAActive["epoch"].(float64) != 1 {
		t.Fatalf("unexpected session-a active control: %#v", sessionAActive)
	}
	publisher.Clear()

	if err := state.HandleMCPIPCEvent(ctx, publisher, RuntimeMcpOpenEvent{SessionID: "session-b", Transport: string(MCPTransportWebRTCDataChannel), PeerID: "peer-b"}, 120); err != nil {
		t.Fatalf("handle observer open: %v", err)
	}
	if status := mcpStructuredContent(callMCP(t, ctx, state, publisher, "session-b", `{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"control.get_state"}}`, 130)); status["activeOwnerSessionId"] != "session-a" {
		t.Fatalf("observer reconnect should see session-a still active: %#v", status)
	}

	if err := state.HandleVideoEvent(ctx, publisher, VideoWorkerEvent{Kind: VideoWorkerStarting}, 140); err != nil {
		t.Fatalf("handle video starting: %v", err)
	}
	activeWhileStarting := latestMCPStatus(t, publisher.Messages())["activeControl"].(map[string]interface{})
	if activeWhileStarting["sessionId"] != "session-a" || activeWhileStarting["epoch"].(float64) != 1 {
		t.Fatalf("video readiness churn cleared active control: %#v", activeWhileStarting)
	}
	if len(hardware.Calls()) != 0 {
		t.Fatalf("observer/video churn should not stop hardware: %v", hardware.Calls())
	}
	publisher.Clear()

	if err := state.HandleVideoEvent(ctx, publisher, VideoWorkerEvent{Kind: VideoWorkerReady}, 150); err != nil {
		t.Fatalf("handle video ready again: %v", err)
	}
	activeAfterReady := latestMCPStatus(t, publisher.Messages())["activeControl"].(map[string]interface{})
	if activeAfterReady["sessionId"] != "session-a" || activeAfterReady["epoch"].(float64) != 1 {
		t.Fatalf("video ready rediscovery cleared active control: %#v", activeAfterReady)
	}
	publisher.Clear()

	if err := state.HandleMCPIPCEvent(ctx, publisher, RuntimeMcpCloseEvent{SessionID: "session-b", Reason: "refresh"}, 160); err != nil {
		t.Fatalf("handle observer close: %v", err)
	}
	if status := mcpStructuredContent(callMCP(t, ctx, state, publisher, "session-a", `{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"control.get_state"}}`, 170)); status["activeOwnerSessionId"] != "session-a" {
		t.Fatalf("observer close should not clear session-a active control: %#v", status)
	}

	sessionAPublish := mcpStructuredContent(callMCP(t, ctx, state, publisher, "session-a", `{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"cmd_vel.publish","arguments":{"epoch":1,"twist":{"linear":{"x":1,"y":0,"z":0},"angular":{"x":0,"y":0,"z":0.5}}}}}`, 180))
	if sessionAPublish["motion"].(map[string]interface{})["leftSpeed"].(float64) != 50 {
		t.Fatalf("active owner should still control after observer reconnect: %#v", sessionAPublish)
	}
	if !reflect.DeepEqual(hardware.Calls(), []string{"apply"}) {
		t.Fatalf("expected only active-owner apply before owner close: %v", hardware.Calls())
	}

	if err := state.HandleMCPIPCEvent(ctx, publisher, RuntimeMcpCloseEvent{SessionID: "session-a", Reason: "owner closed"}, 190); err != nil {
		t.Fatalf("handle owner close: %v", err)
	}
	statusAfterOwnerClose := latestMCPStatus(t, publisher.Messages())
	if statusAfterOwnerClose["activeControl"] != nil {
		t.Fatalf("owner close should clear active control: %#v", statusAfterOwnerClose)
	}
	if !reflect.DeepEqual(hardware.Calls(), []string{"apply", "stop"}) {
		t.Fatalf("owner close should stop motion: %v", hardware.Calls())
	}
}

func TestBoardVideoBridgeWorkerConfigAndUnixSocketEvents(t *testing.T) {
	ctx := context.Background()
	socketPath := shortUnixSocketPath(t, "board-video.sock")
	config := testRuntimeConfig()
	config.BoardVideoBridgeSocketPath = socketPath
	videoEvents := make(chan VideoWorkerEvent, 8)
	mcpEvents := make(chan interface{}, 8)
	service := NewBoardVideoBridgeService(config, videoEvents, mcpEvents)
	service.credentialsFetcher = func(context.Context, RuntimeConfig) (IotTemporaryCredentials, error) {
		return IotTemporaryCredentials{AccessKeyID: "akid", SecretAccessKey: "secret", SessionToken: "token", Expiration: "2026-05-14T12:00:00Z"}, nil
	}
	listener, err := bindUnixListener(socketPath)
	if err != nil {
		t.Fatalf("bind unix: %v", err)
	}
	server := grpc.NewServer()
	boardvideov1.RegisterBoardVideoBridgeServer(server, service)
	go server.Serve(listener)
	defer server.Stop()

	conn, err := grpc.DialContext(ctx, "unix://"+socketPath, grpc.WithTransportCredentials(insecure.NewCredentials()), grpc.WithBlock())
	if err != nil {
		t.Fatalf("dial bridge: %v", err)
	}
	defer conn.Close()
	client := boardvideov1.NewBoardVideoBridgeClient(conn)

	workerConfig, err := client.GetWorkerConfig(ctx, &boardvideov1.WorkerHello{ProtocolVersion: "1", WorkerName: "worker", WorkerVersion: "v"})
	if err != nil {
		t.Fatalf("get worker config: %v", err)
	}
	if workerConfig.GetRegion() != "eu-central-1" || workerConfig.GetChannelName() != "unit-local-board-video" || workerConfig.GetClientId() != "unit-local-unit-kvs-master" || !workerConfig.GetPreferIpv6() {
		t.Fatalf("worker config mismatch: %#v", workerConfig)
	}
	if _, err := client.ReportVideoState(ctx, &boardvideov1.VideoState{State: boardvideov1.VideoState_READY, ViewerCount: 1}); err != nil {
		t.Fatalf("report video: %v", err)
	}
	if got := <-videoEvents; got.Kind != VideoWorkerReady {
		t.Fatalf("unexpected video event: %#v", got)
	}
	if got := <-videoEvents; got.Kind != VideoWorkerViewerConnected || !got.Connected {
		t.Fatalf("unexpected viewer event: %#v", got)
	}
	responseText := `{"jsonrpc":"2.0","id":1,"result":{}}`
	go func() {
		event := (<-mcpEvents).(RuntimeMcpRequestEvent)
		event.Response <- &responseText
	}()
	response, err := client.HandleMcp(ctx, &boardvideov1.McpRequest{McpSessionId: "bridge-a", Payload: []byte(`{"jsonrpc":"2.0","id":1,"method":"initialize"}`)})
	if err != nil {
		t.Fatalf("handle mcp: %v", err)
	}
	if !response.GetHasPayload() || string(response.GetPayload()) != responseText {
		t.Fatalf("unexpected MCP response: %#v", response)
	}
}

func TestGRPCHardwareClientDelegatesOverUnixSocket(t *testing.T) {
	ctx := context.Background()
	socketPath := shortUnixSocketPath(t, "hardware.sock")
	listener, err := bindUnixListener(socketPath)
	if err != nil {
		t.Fatalf("bind hardware: %v", err)
	}
	server := grpc.NewServer()
	fake := &fakeHardwareServer{}
	hardwarev1.RegisterUnitHardwareServer(server, fake)
	go server.Serve(listener)
	defer server.Stop()

	client := NewGRPCHardwareClient(socketPath, time.Second)
	motion, err := client.ApplyVelocity(ctx, Twist{Linear: Vector3{X: 1}, Angular: Vector3{Z: 0.5}}, 1234)
	if err != nil {
		t.Fatalf("apply velocity: %v", err)
	}
	if motion.Sequence != 1 || fake.lastDeadline != 1234 || fake.lastCommandID != "cmd_vel-1234" {
		t.Fatalf("apply mismatch motion=%#v fake=%#v", motion, fake)
	}
	if _, err := client.Stop(ctx); err != nil {
		t.Fatalf("stop: %v", err)
	}
	if fake.stopReason != "daemon-policy" {
		t.Fatalf("stop reason mismatch: %q", fake.stopReason)
	}
}

func TestIotCredentialAndSparkplugHelpers(t *testing.T) {
	config := testRuntimeConfig()
	config.IoTRoleAlias = "unit_daemon,role-alias@Test=1"
	request, err := BuildIotCredentialsRequest(config)
	if err != nil {
		t.Fatalf("build request: %v", err)
	}
	if request.URL != "https://example.credentials.iot.eu-central-1.amazonaws.com/role-aliases/unit_daemon,role-alias@Test=1/credentials" || request.ThingName != "unit-local" {
		t.Fatalf("request mismatch: %#v", request)
	}
	credentials, err := ParseIotCredentialsResponse([]byte(`{"credentials":{"accessKeyId":"akid","secretAccessKey":"secret","sessionToken":"token","expiration":"2026-05-14T12:00:00Z"}}`))
	if err != nil {
		t.Fatalf("parse credentials: %v", err)
	}
	if credentials.AccessKeyID != "akid" {
		t.Fatalf("credentials mismatch: %#v", credentials)
	}
	if _, err := ParseIotCredentialsResponse([]byte(`{"credentials":{"accessKeyId":""}}`)); err == nil {
		t.Fatalf("expected invalid credentials to fail")
	}
	redcon, err := ParseSparkplugRedcon([]byte(`{"state":{"reported":{"topic":{"messageType":"DDATA"},"payload":{"metrics":{"redcon":2}}}}}`))
	if err != nil || redcon.Level != 2 || redcon.Unavailable {
		t.Fatalf("redcon mismatch: %#v err=%v", redcon, err)
	}
	death, err := ParseSparkplugRedcon([]byte(`{"state":{"reported":{"topic":{"messageType":"DDEATH"},"payload":{"metrics":{"redcon":2}}}}}`))
	if err != nil || !death.Unavailable {
		t.Fatalf("death redcon mismatch: %#v err=%v", death, err)
	}
	if _, err := BuildIotDataEndpointURL("https://example.iot.eu-central-1.amazonaws.com"); err == nil {
		t.Fatalf("expected endpoint with scheme to fail")
	}
}

func TestCloudWatchWriterSemantics(t *testing.T) {
	ctx := context.Background()
	fake := &fakeCloudWatchLogsClient{
		createLogGroupResults:  []error{NewCloudWatchLogClientError(CloudWatchAlreadyExists, "group exists")},
		createLogStreamResults: []error{NewCloudWatchLogClientError(CloudWatchAlreadyExists, "stream exists")},
	}
	writer := NewCloudWatchLogWriter(cloudWatchLogConfigForRuntimeTest(), fake)
	if err := writer.EnsureReady(ctx); err != nil {
		t.Fatalf("ensure ready: %v", err)
	}
	if !reflect.DeepEqual(fake.calls, []string{
		"create-log-group:txing/town-local/rig-local/unit-local",
		"put-retention:txing/town-local/rig-local/unit-local:14",
		"create-log-stream:txing/town-local/rig-local/unit-local:daemon/unit-local-daemon-test",
	}) {
		t.Fatalf("setup calls mismatch: %v", fake.calls)
	}

	expected := "expected"
	fake = &fakeCloudWatchLogsClient{
		putResults: []putResult{
			{err: CloudWatchLogClientError{Kind: CloudWatchInvalidSequenceToken, Message: "invalid", Expected: &expected}},
			{result: CloudWatchPutLogEventsResult{NextSequenceToken: ptrString("next")}},
		},
	}
	writer = NewCloudWatchLogWriter(cloudWatchLogConfigForRuntimeTest(), fake)
	result, err := writer.PutLogEventsWithRetry(ctx, []CloudWatchLogRecord{{TimestampMS: 1, Message: "first"}}, ptrString("stale"))
	if err != nil {
		t.Fatalf("put retry: %v", err)
	}
	if result.NextSequenceToken == nil || *result.NextSequenceToken != "next" || len(fake.puts) != 2 || *fake.puts[1].sequenceToken != "expected" {
		t.Fatalf("retry mismatch result=%#v puts=%#v", result, fake.puts)
	}
}

func TestVideoMarkerAndCredentialRestartHelpers(t *testing.T) {
	event, ok := ParseVideoWorkerMarker("TXING_MCP_DATACHANNEL_CLOSED sessionId=session-a reason=operator-closed")
	if !ok || event.Kind != VideoWorkerMCPDataChannelClosed || event.SessionID != "session-a" || event.Reason != "operator-closed" {
		t.Fatalf("marker mismatch: %#v ok=%v", event, ok)
	}
	now := time.Unix(1000, 0)
	expires := now.Add(20 * time.Minute)
	if restart := VideoCredentialRestartAt(expires, now); !restart.Equal(expires.Add(-5 * time.Minute)) {
		t.Fatalf("restart mismatch: %s", restart)
	}
	if restart := VideoCredentialRestartAt(now.Add(time.Minute), now); !restart.Equal(now.Add(30 * time.Second)) {
		t.Fatalf("restart floor mismatch: %s", restart)
	}
}

type fakeHardwareServer struct {
	hardwarev1.UnimplementedUnitHardwareServer
	lastDeadline  uint64
	lastCommandID string
	stopReason    string
	sequence      uint64
}

func (s *fakeHardwareServer) GetStatus(context.Context, *hardwarev1.GetStatusRequest) (*hardwarev1.HardwareStatus, error) {
	return &hardwarev1.HardwareStatus{ActuatorReady: true, Motion: &hardwarev1.MotionState{Sequence: s.sequence}}, nil
}

func (s *fakeHardwareServer) ApplyVelocity(_ context.Context, request *hardwarev1.ApplyVelocityRequest) (*hardwarev1.ApplyVelocityResponse, error) {
	s.lastDeadline = request.GetDeadlineUnixMs()
	s.lastCommandID = request.GetCommandId()
	s.sequence++
	return &hardwarev1.ApplyVelocityResponse{Motion: &hardwarev1.MotionState{LeftSpeed: 50, RightSpeed: 50, Sequence: s.sequence}}, nil
}

func (s *fakeHardwareServer) Stop(_ context.Context, request *hardwarev1.StopRequest) (*hardwarev1.StopResponse, error) {
	s.stopReason = request.GetReason()
	s.sequence++
	return &hardwarev1.StopResponse{Motion: &hardwarev1.MotionState{Sequence: s.sequence}}, nil
}

type putResult struct {
	result CloudWatchPutLogEventsResult
	err    error
}

type fakeCloudWatchPut struct {
	logGroup      string
	logStream     string
	events        []CloudWatchLogRecord
	sequenceToken *string
}

type fakeCloudWatchLogsClient struct {
	calls                  []string
	puts                   []fakeCloudWatchPut
	createLogGroupResults  []error
	createLogStreamResults []error
	putResults             []putResult
}

func (c *fakeCloudWatchLogsClient) CreateLogGroup(_ context.Context, logGroup string) error {
	c.calls = append(c.calls, "create-log-group:"+logGroup)
	if len(c.createLogGroupResults) > 0 {
		err := c.createLogGroupResults[0]
		c.createLogGroupResults = c.createLogGroupResults[1:]
		return err
	}
	return nil
}

func (c *fakeCloudWatchLogsClient) PutRetentionPolicy(_ context.Context, logGroup string, retentionDays int32) error {
	c.calls = append(c.calls, "put-retention:"+logGroup+":"+intText(int(retentionDays)))
	return nil
}

func (c *fakeCloudWatchLogsClient) CreateLogStream(_ context.Context, logGroup, logStream string) error {
	c.calls = append(c.calls, "create-log-stream:"+logGroup+":"+logStream)
	if len(c.createLogStreamResults) > 0 {
		err := c.createLogStreamResults[0]
		c.createLogStreamResults = c.createLogStreamResults[1:]
		return err
	}
	return nil
}

func (c *fakeCloudWatchLogsClient) PutLogEvents(_ context.Context, logGroup, logStream string, events []CloudWatchLogRecord, sequenceToken *string) (CloudWatchPutLogEventsResult, error) {
	c.puts = append(c.puts, fakeCloudWatchPut{logGroup: logGroup, logStream: logStream, events: events, sequenceToken: sequenceToken})
	if len(c.putResults) > 0 {
		result := c.putResults[0]
		c.putResults = c.putResults[1:]
		return result.result, result.err
	}
	return CloudWatchPutLogEventsResult{NextSequenceToken: ptrString("next-token")}, nil
}

func callMCP(t *testing.T, ctx context.Context, state *RuntimeState, publisher Publisher, sessionID, payload string, observedAtMS uint64) map[string]interface{} {
	t.Helper()
	responseCh := make(chan *string, 1)
	if err := state.HandleMCPIPCEvent(ctx, publisher, RuntimeMcpRequestEvent{SessionID: sessionID, Payload: payload, Response: responseCh}, observedAtMS); err != nil {
		t.Fatalf("handle mcp ipc: %v", err)
	}
	responseText := <-responseCh
	if responseText == nil {
		t.Fatalf("expected MCP response")
	}
	var response map[string]interface{}
	mustJSON(t, []byte(*responseText), &response)
	return response
}

func mcpStructuredContent(response map[string]interface{}) map[string]interface{} {
	result := response["result"].(map[string]interface{})
	return result["structuredContent"].(map[string]interface{})
}

func latestMCPStatus(t *testing.T, messages []PublishedMessage) map[string]interface{} {
	t.Helper()
	for index := len(messages) - 1; index >= 0; index-- {
		if messages[index].Topic != "txings/unit-local/mcp/status" {
			continue
		}
		var status map[string]interface{}
		mustJSON(t, messages[index].Payload, &status)
		return status
	}
	t.Fatalf("missing MCP status message")
	return nil
}

func mustJSON(t *testing.T, payload []byte, target interface{}) {
	t.Helper()
	if err := json.Unmarshal(payload, target); err != nil {
		t.Fatalf("decode JSON %s: %v", payload, err)
	}
}

func shortUnixSocketPath(t *testing.T, name string) string {
	t.Helper()
	candidates := []string{os.Getenv("TXING_TEST_UNIX_SOCKET_DIR"), "/tmp", os.TempDir(), t.TempDir()}
	var lastErr error
	for _, base := range candidates {
		if base == "" {
			continue
		}
		info, err := os.Stat(base)
		if err != nil {
			lastErr = err
			continue
		}
		if !info.IsDir() {
			lastErr = fmt.Errorf("%s is not a directory", base)
			continue
		}
		dir, err := os.MkdirTemp(base, fmt.Sprintf("txing-daemon-%d-", os.Getpid()))
		if err != nil {
			lastErr = err
			continue
		}
		socketPath := filepath.Join(dir, name)
		if len(socketPath) >= 100 {
			_ = os.RemoveAll(dir)
			lastErr = fmt.Errorf("unix socket path too long: %s", socketPath)
			continue
		}
		t.Cleanup(func() { _ = os.RemoveAll(dir) })
		return socketPath
	}
	t.Fatalf("create short temp dir: %v", lastErr)
	return ""
}

func ptrString(value string) *string {
	return &value
}

func cloudWatchLogConfigForRuntimeTest() CloudWatchLogConfig {
	return CloudWatchLogConfig{
		LogGroup:      "txing/town-local/rig-local/unit-local",
		LogStream:     "daemon/unit-local-daemon-test",
		Level:         CloudWatchInfo,
		RetentionDays: DefaultLogRetentionDays,
	}
}

func intText(value int) string {
	return strings.TrimSpace(strings.ReplaceAll(strings.TrimPrefix(strings.TrimSuffix(strings.TrimSpace(jsonNumber(value)), "\n"), "\n"), "\n", ""))
}

func jsonNumber(value int) string {
	encoded, _ := json.Marshal(value)
	return string(encoded)
}
