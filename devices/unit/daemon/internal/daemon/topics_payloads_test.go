package daemon

import (
	"encoding/json"
	"net"
	"testing"
)

func TestBuildsRetainedCapabilityStateTopic(t *testing.T) {
	topic, err := BuildCapabilityStateTopic("unit-local")
	if err != nil {
		t.Fatalf("build topic: %v", err)
	}
	if topic != "txings/unit-local/capability/v2/state" {
		t.Fatalf("unexpected topic %q", topic)
	}
	if _, err := BuildCapabilityStateTopic("unit/local"); err == nil {
		t.Fatalf("expected invalid topic segment to fail")
	}
}

func TestBuildsPublicTopics(t *testing.T) {
	cases := map[string]func() (string, error){
		"mcp root":         func() (string, error) { return BuildMCPTopicRoot("unit-local") },
		"mcp descriptor":   func() (string, error) { return BuildMCPDescriptorTopic("unit-local") },
		"mcp status":       func() (string, error) { return BuildMCPStatusTopic("unit-local") },
		"video root":       func() (string, error) { return BuildVideoTopicRoot("unit-local") },
		"video descriptor": func() (string, error) { return BuildVideoDescriptorTopic("unit-local") },
		"video status":     func() (string, error) { return BuildVideoStatusTopic("unit-local") },
		"mcp c2s sub":      func() (string, error) { return BuildMCPSessionC2SSubscription("unit-local") },
		"mcp s2c":          func() (string, error) { return BuildMCPSessionS2CTopic("unit-local", "session-a") },
		"board shadow":     func() (string, error) { return BuildBoardShadowUpdateTopic("unit-local") },
		"mcp shadow":       func() (string, error) { return BuildMCPShadowUpdateTopic("unit-local") },
		"video shadow":     func() (string, error) { return BuildVideoShadowUpdateTopic("unit-local") },
	}
	expected := map[string]string{
		"mcp root":         "txings/unit-local/mcp",
		"mcp descriptor":   "txings/unit-local/mcp/descriptor",
		"mcp status":       "txings/unit-local/mcp/status",
		"video root":       "txings/unit-local/video",
		"video descriptor": "txings/unit-local/video/descriptor",
		"video status":     "txings/unit-local/video/status",
		"mcp c2s sub":      "txings/unit-local/mcp/session/+/c2s",
		"mcp s2c":          "txings/unit-local/mcp/session/session-a/s2c",
		"board shadow":     "$aws/things/unit-local/shadow/name/board/update",
		"mcp shadow":       "$aws/things/unit-local/shadow/name/mcp/update",
		"video shadow":     "$aws/things/unit-local/shadow/name/video/update",
	}
	for name, build := range cases {
		topic, err := build()
		if err != nil {
			t.Fatalf("%s: %v", name, err)
		}
		if topic != expected[name] {
			t.Fatalf("%s topic mismatch: %q", name, topic)
		}
	}
	sessionID, ok := ParseMCPSessionC2STopic("unit-local", "txings/unit-local/mcp/session/session-a/c2s")
	if !ok || sessionID != "session-a" {
		t.Fatalf("unexpected parsed session id: %q ok=%v", sessionID, ok)
	}
	if _, ok := ParseMCPSessionC2STopic("unit-local", "txings/unit-local/mcp/session/bad/id/c2s"); ok {
		t.Fatalf("expected invalid session topic to be rejected")
	}
}

func TestBuildsBoardShadowUpdatePayloads(t *testing.T) {
	online := BuildBoardShadowUpdate(BuildOnlineBoardReport(DefaultRouteAddresses{
		IPv4: net.IPv4(192, 168, 1, 25),
	}))
	if !online.State.Reported.Power || !online.State.Reported.WiFi.Online {
		t.Fatalf("expected online board report: %#v", online)
	}
	if !online.State.Reported.WiFi.IPv4.Equal(net.IPv4(192, 168, 1, 25)) {
		t.Fatalf("unexpected ipv4: %v", online.State.Reported.WiFi.IPv4)
	}
	offline := BuildBoardShadowUpdate(BuildOfflineBoardReport())
	if offline.State.Reported.Power || offline.State.Reported.WiFi.Online || offline.State.Reported.WiFi.IPv4 != nil || offline.State.Reported.WiFi.IPv6 != nil {
		t.Fatalf("expected offline board report: %#v", offline)
	}
}

func TestBuildsCapabilityPayloadWithTTLAndExpiredState(t *testing.T) {
	payload := BuildCapabilityStatePayload(
		"unit-local",
		[]string{BoardCapability},
		map[string]bool{BoardCapability: true},
		150_000,
		1_000,
		1,
	)
	if payload.SchemaVersion != SchemaVersion || payload.AdapterID != AdapterID || payload.ThingName != "unit-local" {
		t.Fatalf("identity mismatch: %#v", payload)
	}
	if payload.Capabilities[BoardCapability] != true || payload.ExpiredCapabilities[BoardCapability] != false {
		t.Fatalf("capability mismatch: %#v", payload)
	}
	if payload.ObservedAtMS != 1_000 || payload.ExpiresAtMS != 151_000 || payload.Seq != 1 {
		t.Fatalf("timing mismatch: %#v", payload)
	}
}

func TestBuildsStaticMCPAndVideoDescriptors(t *testing.T) {
	config := runtimeConfigFromArgs(t)
	mcpDescriptor := MCPDescriptor(config, "mqtt-jsonrpc")
	if mcpDescriptor["protocolVersion"] != MCPProtocolVersion {
		t.Fatalf("mcp protocol mismatch: %#v", mcpDescriptor)
	}
	if mcpDescriptor["transport"] != "mqtt-jsonrpc" {
		t.Fatalf("mcp transport mismatch: %#v", mcpDescriptor)
	}
	encoded, err := json.Marshal(mcpDescriptor)
	if err != nil {
		t.Fatalf("marshal mcp descriptor: %v", err)
	}
	if !jsonContains(encoded, `"activeTtlMs":5000`) || !jsonContains(encoded, `"topicRoot":"txings/unit-local/mcp"`) {
		t.Fatalf("mcp descriptor missing static fields: %s", encoded)
	}
	videoDescriptor := VideoDescriptor(config)
	if videoDescriptor["transport"] != DefaultVideoTransport || videoDescriptor["channelName"] != "unit-local-board-video" || videoDescriptor["region"] != "eu-central-1" {
		t.Fatalf("video descriptor mismatch: %#v", videoDescriptor)
	}
	encoded, err = json.Marshal(videoDescriptor)
	if err != nil {
		t.Fatalf("marshal video descriptor: %v", err)
	}
	if !jsonContains(encoded, `"video":"h264"`) || !jsonContains(encoded, `"serverVersion":"`+DaemonVersion+`"`) {
		t.Fatalf("video descriptor missing static fields: %s", encoded)
	}
}

func jsonContains(payload []byte, needle string) bool {
	return string(payload) != "" && contains(string(payload), needle)
}

func contains(value, needle string) bool {
	for i := 0; i+len(needle) <= len(value); i++ {
		if value[i:i+len(needle)] == needle {
			return true
		}
	}
	return false
}
