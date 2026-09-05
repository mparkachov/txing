package daemon

import (
	"context"
	"encoding/binary"
	"encoding/json"
	"math"
	"net"
	"testing"
	"time"

	mavlinkv1 "github.com/mparkachov/txing/devices/common/board/daemon/internal/proto/mavlinkv1"
)

func TestMAVLinkControlLeaseTakeoverAndWatchdog(t *testing.T) {
	state := NewMAVLinkControlState(5*time.Second, 500*time.Millisecond)
	first := state.OpenPeer()
	second := state.OpenPeer()

	active, err := state.Activate(first.SessionID, "first@example.test", false, 100)
	if err != nil || active.Epoch != 1 {
		t.Fatalf("first activation = %#v, %v", active, err)
	}
	if _, err := state.Activate(second.SessionID, "second@example.test", false, 200); err != errMAVLinkControlBusy {
		t.Fatalf("second activation error = %v, want active-control busy", err)
	}
	taken, err := state.Activate(second.SessionID, "second@example.test", true, 300)
	if err != nil || taken.Epoch != 2 {
		t.Fatalf("takeover = %#v, %v", taken, err)
	}
	if _, err := state.EnsureActive(first.SessionID, active.Epoch, 301); err != errMAVLinkStaleEpoch {
		t.Fatalf("old epoch error = %v, want stale epoch", err)
	}

	frame := testMAVLinkFrame(mavlinkHeartbeatMessageID, make([]byte, 9), defaultMAVLinkGCSSystemID, defaultMAVLinkGCSComponentID)
	if err := state.AcceptControlFrame(second.SessionID, taken.Epoch, frame, DefaultMAVLinkUplinkPolicy(MAVLinkTarget{SystemID: 1, ComponentID: 1}), 400); err != nil {
		t.Fatalf("accept heartbeat: %v", err)
	}
	if state.WatchdogExpired(899) {
		t.Fatal("watchdog fired before 500 ms elapsed")
	}
	if !state.WatchdogExpired(900) {
		t.Fatal("watchdog did not fire at 500 ms")
	}
	if state.WatchdogExpired(901) {
		t.Fatal("watchdog fired more than once for one control gap")
	}
	if !state.ClosePeer(second.SessionID) {
		t.Fatal("active peer close must request immediate safe state")
	}
	if state.Active() != nil {
		t.Fatalf("active control remains after close: %#v", state.Active())
	}
}

func TestMAVLinkControlEnvelopeUsesStableLeaseAndErrors(t *testing.T) {
	state := NewMAVLinkControlState(5*time.Second, 500*time.Millisecond)
	first := state.OpenPeer()
	second := state.OpenPeer()

	result := state.HandleControlMessage(first.SessionID, `{"type":"control.activate","requestId":"one","actor":"first","takeover":false}`, 10)
	if result.SafeRequired || !result.StatusChanged {
		t.Fatal("activation must not request safe state")
	}
	response := result.Response
	var decoded map[string]interface{}
	if err := json.Unmarshal([]byte(response), &decoded); err != nil {
		t.Fatal(err)
	}
	if decoded["type"] != "control.activated" {
		t.Fatalf("activation response = %#v", decoded)
	}
	stateMap := decoded["state"].(map[string]interface{})
	if stateMap["leaseTtlMs"] != float64(5000) {
		t.Fatalf("lease state = %#v", stateMap)
	}

	result = state.HandleControlMessage(second.SessionID, `{"type":"control.activate","requestId":"two","actor":"second","takeover":false}`, 11)
	if result.SafeRequired || result.StatusChanged || !mavlinkControlResponseHasCode(t, result.Response, "control_busy") {
		t.Fatalf("busy response = %s safe=%t", result.Response, result.SafeRequired)
	}

	result = state.HandleControlMessage(second.SessionID, `{"type":"control.activate","requestId":"three","actor":"second","takeover":true}`, 12)
	if result.SafeRequired || !result.StatusChanged {
		t.Fatal("takeover must not inject safe state")
	}
	if err := json.Unmarshal([]byte(result.Response), &decoded); err != nil || decoded["type"] != "control.activated" {
		t.Fatalf("takeover response = %s err=%v", result.Response, err)
	}
	result = state.HandleControlMessage(second.SessionID, `{"type":"control.renew_active","requestId":"renew","epoch":2}`, 13)
	if result.SafeRequired || result.StatusChanged || !mavlinkControlResponseHasType(t, result.Response, "control.renewed") {
		t.Fatalf("renewal response = %s safe=%t status-changed=%t", result.Response, result.SafeRequired, result.StatusChanged)
	}
	if active := state.Active(); active == nil || active.ExpiresAt != 5013 {
		t.Fatalf("renewal must extend the local lease: %#v", active)
	}

	result = state.HandleControlMessage(first.SessionID, `{"type":"control.release_active","requestId":"four","epoch":1}`, 14)
	if result.SafeRequired || result.StatusChanged || !mavlinkControlResponseHasCode(t, result.Response, "stale_epoch") {
		t.Fatalf("stale response = %s safe=%t", result.Response, result.SafeRequired)
	}
	result = state.HandleControlMessage(second.SessionID, `{"type":"control.release_active","requestId":"five","epoch":2}`, 15)
	if !result.SafeRequired || !result.StatusChanged || !mavlinkControlResponseHasType(t, result.Response, "control.released") {
		t.Fatalf("release response = %s safe=%t", result.Response, result.SafeRequired)
	}
	result = state.HandleControlMessage(second.SessionID, `{"type":"control.get_state","requestId":"six","extra":true}`, 15)
	if !mavlinkControlResponseHasCode(t, result.Response, "invalid_request") {
		t.Fatalf("extra-field response = %s", result.Response)
	}
	result = state.HandleControlMessage(second.SessionID, `{"type":"control.renew_active","requestId":"seven","epoch":2.5}`, 16)
	if !mavlinkControlResponseHasCode(t, result.Response, "invalid_request") {
		t.Fatalf("fractional epoch response = %s", result.Response)
	}
	result = state.HandleControlMessage(second.SessionID, `{"type":"control.get_state","requestId":"eight"}{}`, 17)
	if !mavlinkControlResponseHasCode(t, result.Response, "invalid_request") {
		t.Fatalf("trailing JSON response = %s", result.Response)
	}
}

func TestMAVLinkUplinkAllowlistAndIntegrity(t *testing.T) {
	policy := DefaultMAVLinkUplinkPolicy(MAVLinkTarget{SystemID: 1, ComponentID: 1})
	valid := [][]byte{
		testMAVLinkFrame(mavlinkHeartbeatMessageID, make([]byte, 9), defaultMAVLinkGCSSystemID, defaultMAVLinkGCSComponentID),
		testMAVLinkFrame(mavlinkManualControlMessageID, testManualControlPayload(1), defaultMAVLinkGCSSystemID, defaultMAVLinkGCSComponentID),
		testMAVLinkFrame(mavlinkCommandLongMessageID, testCommandLongPayload(mavlinkCommandComponentArmDisarm, 1, 0, 1, 1), defaultMAVLinkGCSSystemID, defaultMAVLinkGCSComponentID),
		testMAVLinkFrame(mavlinkCommandLongMessageID, testCommandLongPayload(mavlinkCommandComponentArmDisarm, 0, 0, 1, 1), defaultMAVLinkGCSSystemID, defaultMAVLinkGCSComponentID),
		testMAVLinkFrame(mavlinkCommandLongMessageID, testCommandLongPayload(mavlinkCommandDoSetMode, 1, float32(mavlinkModeHold), 1, 1), defaultMAVLinkGCSSystemID, defaultMAVLinkGCSComponentID),
		testMAVLinkFrame(mavlinkSetModeMessageID, testSetModePayload(mavlinkModeManual, 1, 1), defaultMAVLinkGCSSystemID, defaultMAVLinkGCSComponentID),
	}
	for _, frame := range valid {
		if err := ValidateMAVLinkUplink(frame, policy); err != nil {
			t.Fatalf("valid frame rejected: %v", err)
		}
	}

	wrongSource := append([]byte(nil), valid[0]...)
	wrongSource[5] = 1
	if err := ValidateMAVLinkUplink(wrongSource, policy); err == nil {
		t.Fatal("wrong source heartbeat was accepted")
	}
	forcedArm := testMAVLinkFrame(mavlinkCommandLongMessageID, testCommandLongPayload(mavlinkCommandComponentArmDisarm, 1, 21196, 1, 1), defaultMAVLinkGCSSystemID, defaultMAVLinkGCSComponentID)
	if err := ValidateMAVLinkUplink(forcedArm, policy); err == nil {
		t.Fatal("forced arm was accepted")
	}
	wrongTarget := testMAVLinkFrame(mavlinkManualControlMessageID, testManualControlPayload(2), defaultMAVLinkGCSSystemID, defaultMAVLinkGCSComponentID)
	if err := ValidateMAVLinkUplink(wrongTarget, policy); err == nil {
		t.Fatal("wrong-target manual control was accepted")
	}
	unsupported := testMAVLinkFrame(77, make([]byte, 3), defaultMAVLinkGCSSystemID, defaultMAVLinkGCSComponentID)
	if err := ValidateMAVLinkUplink(unsupported, policy); err == nil {
		t.Fatal("unsupported message was accepted")
	}
	corrupt := append([]byte(nil), valid[1]...)
	corrupt[len(corrupt)-1] ^= 0xff
	if err := ValidateMAVLinkUplink(corrupt, policy); err == nil {
		t.Fatal("corrupt frame was accepted")
	}
	signed := append([]byte(nil), valid[0]...)
	signed[2] = mavlinkV2SignedIncompatibilityFlag
	if err := ValidateMAVLinkUplink(signed, policy); err == nil {
		t.Fatal("signed frame was accepted")
	}
}

func TestMAVLinkTelemetryFanoutIsBoundedPerPeer(t *testing.T) {
	state := NewMAVLinkControlState(5*time.Second, 500*time.Millisecond)
	fast := state.OpenPeer()
	slow := state.OpenPeer()
	for index := 0; index < defaultMAVLinkPeerOutboundBuffer+1; index++ {
		state.BroadcastTelemetry([]byte{byte(index)})
		select {
		case <-fast.Outbound:
		default:
			t.Fatalf("fast peer did not receive telemetry %d", index)
		}
	}
	if slow.Dropped != 1 {
		t.Fatalf("slow peer dropped %d frames, want 1", slow.Dropped)
	}
	if connected, observers := state.PeerCounts(); connected != 2 || observers != 2 {
		t.Fatalf("peer counts = %d/%d, want 2/2", connected, observers)
	}
}

func TestMAVLinkRuntimePublishesDedicatedDescriptorStatusAndShadow(t *testing.T) {
	config := testRuntimeConfig()
	config.ThingID = "cyberbrick-a1"
	config.Capabilities = []string{BoardCapability, MAVLinkCapability, VideoCapability}
	config.MAVLinkChannelName = "cyberbrick-a1-mavlink"
	state, err := NewRuntimeState(config)
	if err != nil {
		t.Fatal(err)
	}
	state.mavlinkKVSReady = true
	state.mavlinkStatus = MAVLinkRuntimeStatus{
		LinkState:      "ready",
		HeartbeatFresh: true,
		Target:         &MAVLinkTarget{SystemID: 1, ComponentID: 1},
		Armed:          true,
		Errors:         []MAVLinkError{},
	}
	publisher := &fakePublisher{}
	if err := state.PublishOnline(context.Background(), publisher, DefaultRouteAddresses{}, 10); err != nil {
		t.Fatal(err)
	}
	var descriptor, retainedStatus, shadow map[string]interface{}
	for _, message := range publisher.Messages() {
		switch message.Topic {
		case "txings/cyberbrick-a1/mavlink/descriptor":
			mustJSON(t, message.Payload, &descriptor)
			if !message.Retain || message.MessageExpirySeconds != nil {
				t.Fatalf("descriptor retention = %#v", message)
			}
		case "txings/cyberbrick-a1/mavlink/status":
			mustJSON(t, message.Payload, &retainedStatus)
		case "$aws/things/cyberbrick-a1/shadow/name/mavlink/update":
			mustJSON(t, message.Payload, &shadow)
		}
	}
	if descriptor["channelName"] != "cyberbrick-a1-mavlink" || descriptor["transport"] != "webrtc-datachannel" {
		t.Fatalf("descriptor = %#v", descriptor)
	}
	if retainedStatus["available"] != true || retainedStatus["serviceId"] != MAVLinkCapability {
		t.Fatalf("status = %#v", retainedStatus)
	}
	reported := shadow["state"].(map[string]interface{})["reported"].(map[string]interface{})
	if _, hasTimestamp := reported["updatedAtMs"]; hasTimestamp || reported["armed"] != true {
		t.Fatalf("shadow = %#v", shadow)
	}

	publisher.Clear()
	if err := state.RefreshCapabilities(context.Background(), publisher, 20); err != nil {
		t.Fatal(err)
	}
	heartbeat := publisher.Messages()
	expectedTopics := []string{
		"txings/cyberbrick-a1/mavlink/status",
		"txings/cyberbrick-a1/video/status",
		"txings/cyberbrick-a1/capability/v2/state",
	}
	if len(heartbeat) != len(expectedTopics) {
		t.Fatalf("heartbeat messages = %#v", heartbeat)
	}
	expectedExpiry := uint32(150)
	for index, topic := range expectedTopics {
		if heartbeat[index].Topic != topic {
			t.Fatalf("heartbeat topic[%d] = %q, want %q", index, heartbeat[index].Topic, topic)
		}
		assertPublishRetention(t, heartbeat[index], true, &expectedExpiry)
	}
}

func TestTbotMAVLinkAvailabilityRequiresLocalServiceHeartbeatAndKVSPath(t *testing.T) {
	config := testRuntimeConfig()
	config.ThingID = "tbot-a1"
	config.Capabilities = []string{BoardCapability, MAVLinkCapability, VideoCapability}
	config.MAVLinkChannelName = "tbot-a1-mavlink"
	state, err := NewRuntimeState(config)
	if err != nil {
		t.Fatal(err)
	}

	cases := []struct {
		name           string
		kvsReady       bool
		linkState      string
		heartbeatFresh bool
		wantAvailable  bool
	}{
		{
			name:           "KVS path unavailable",
			kvsReady:       false,
			linkState:      "ready",
			heartbeatFresh: true,
			wantAvailable:  false,
		},
		{
			name:           "local MAVLink service unavailable",
			kvsReady:       true,
			linkState:      "unavailable",
			heartbeatFresh: false,
			wantAvailable:  false,
		},
		{
			name:           "flight-controller heartbeat stale",
			kvsReady:       true,
			linkState:      "ready",
			heartbeatFresh: false,
			wantAvailable:  false,
		},
		{
			name:           "ready without an Office peer",
			kvsReady:       true,
			linkState:      "ready",
			heartbeatFresh: true,
			wantAvailable:  true,
		},
	}

	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			state.mavlinkKVSReady = testCase.kvsReady
			state.mavlinkStatus = MAVLinkRuntimeStatus{
				LinkState:      testCase.linkState,
				HeartbeatFresh: testCase.heartbeatFresh,
			}

			availability := state.onlineCapabilities()
			if got := availability[MAVLinkCapability]; got != testCase.wantAvailable {
				t.Fatalf("MAVLink availability = %t, want %t", got, testCase.wantAvailable)
			}
			if peers, _ := state.mavlink.PeerCounts(); peers != 0 {
				t.Fatalf("MAVLink peer count = %d, want no Office peer", peers)
			}
		})
	}
}

func TestMAVLinkStatusAlwaysPublishesAnErrorArray(t *testing.T) {
	payload := MAVLinkUnavailableStatus("").StatusPayload(nil, false)
	errors, ok := payload["errors"].([]MAVLinkError)
	if !ok || len(errors) != 0 {
		t.Fatalf("errors payload = %#v", payload["errors"])
	}
}

func TestMAVLinkBridgeEventUsesSubmittedEpochAndRequestsSafeState(t *testing.T) {
	config := testRuntimeConfig()
	config.Capabilities = []string{BoardCapability, MAVLinkCapability}
	state, err := NewRuntimeState(config)
	if err != nil {
		t.Fatal(err)
	}
	state.mavlinkStatus = MAVLinkRuntimeStatus{LinkState: "ready", HeartbeatFresh: true, Target: &MAVLinkTarget{SystemID: 1, ComponentID: 1}}
	transport := &fakeMAVLinkFlightTransport{}
	state.mavlinkFlight = transport
	publisher := &fakePublisher{}

	open := make(chan runtimeMAVLinkBridgeOpenResult, 1)
	if err := state.HandleMAVLinkBridgeEvent(context.Background(), publisher, runtimeMAVLinkBridgeOpenEvent{response: open}, 10); err != nil {
		t.Fatal(err)
	}
	peer := (<-open).peer
	control := make(chan string, 1)
	if err := state.HandleMAVLinkBridgeEvent(context.Background(), publisher, runtimeMAVLinkBridgeControlEvent{
		sessionID: peer.SessionID,
		json:      `{"type":"control.activate","requestId":"one","actor":"operator","takeover":false}`,
		response:  control,
	}, 20); err != nil {
		t.Fatal(err)
	}
	if !mavlinkControlResponseHasType(t, <-control, "control.activated") {
		t.Fatal("activation response was not stable")
	}
	publisher.Clear()
	renew := make(chan string, 1)
	if err := state.HandleMAVLinkBridgeEvent(context.Background(), publisher, runtimeMAVLinkBridgeControlEvent{
		sessionID: peer.SessionID,
		json:      `{"type":"control.renew_active","requestId":"renew","epoch":1}`,
		response:  renew,
	}, 21); err != nil {
		t.Fatal(err)
	}
	if !mavlinkControlResponseHasType(t, <-renew, "control.renewed") {
		t.Fatal("renewal response was not stable")
	}
	if messages := publisher.Messages(); len(messages) != 0 {
		t.Fatalf("renewal must not publish retained state or named shadows: %#v", messages)
	}
	frame := testMAVLinkFrame(mavlinkHeartbeatMessageID, make([]byte, 9), defaultMAVLinkGCSSystemID, defaultMAVLinkGCSComponentID)
	denied := make(chan error, 1)
	if err := state.HandleMAVLinkBridgeEvent(context.Background(), publisher, runtimeMAVLinkBridgeFrameEvent{sessionID: peer.SessionID, epoch: 99, frame: frame, response: denied}, 30); err != nil {
		t.Fatal(err)
	}
	if <-denied != errMAVLinkStaleEpoch {
		t.Fatal("wrong epoch was not rejected")
	}
	accepted := make(chan error, 1)
	if err := state.HandleMAVLinkBridgeEvent(context.Background(), publisher, runtimeMAVLinkBridgeFrameEvent{sessionID: peer.SessionID, epoch: 1, frame: frame, response: accepted}, 31); err != nil {
		t.Fatal(err)
	}
	if err := <-accepted; err != nil {
		t.Fatalf("accepted frame = %v", err)
	}
	closed := make(chan error, 1)
	if err := state.HandleMAVLinkBridgeEvent(context.Background(), publisher, runtimeMAVLinkBridgeCloseEvent{sessionID: peer.SessionID, reason: "test", response: closed}, 32); err != nil {
		t.Fatal(err)
	}
	if err := <-closed; err != nil {
		t.Fatal(err)
	}
	if len(transport.frames) != 1 || len(transport.safeRequests) != 1 {
		t.Fatalf("transport frames=%d safe=%#v", len(transport.frames), transport.safeRequests)
	}
}

func TestMAVLinkOfflineRequestsBoundedNeutralHoldAndDisarm(t *testing.T) {
	config := testRuntimeConfig()
	config.Capabilities = []string{BoardCapability, MAVLinkCapability}
	state, err := NewRuntimeState(config)
	if err != nil {
		t.Fatal(err)
	}
	transport := &fakeMAVLinkFlightTransport{}
	state.mavlinkFlight = transport
	if err := state.PublishOffline(context.Background(), &fakePublisher{}, 10); err != nil {
		t.Fatal(err)
	}
	if len(transport.safeRequests) != 1 || !transport.safeRequests[0].requestDisarm || transport.safeRequests[0].reason != "MAVLink daemon shutdown" {
		t.Fatalf("shutdown safe state = %#v", transport.safeRequests)
	}
}

func TestMAVLinkServiceTracksHeartbeatAndBuildsSafeFrames(t *testing.T) {
	service := NewMAVLinkService(MAVLinkServiceConfig{HeartbeatWindow: time.Second})
	heartbeat := testMAVLinkFrame(mavlinkHeartbeatMessageID, testHeartbeatPayload(4, true), 1, 1)
	service.observeFrame(heartbeat)
	status, err := service.GetStatus(context.Background(), &mavlinkv1.GetStatusRequest{})
	if err != nil {
		t.Fatal(err)
	}
	if status.GetLinkState() != mavlinkv1.LinkState_LINK_STATE_READY || !status.GetHeartbeatFresh() || !status.GetArmed() || status.GetTarget().GetSystemId() != 1 {
		t.Fatalf("service status = %#v", status)
	}

	receiver, err := net.ListenUDP("udp", &net.UDPAddr{IP: net.IPv4(127, 0, 0, 1), Port: 0})
	if err != nil {
		t.Fatal(err)
	}
	defer receiver.Close()
	connection, err := net.DialUDP("udp", nil, receiver.LocalAddr().(*net.UDPAddr))
	if err != nil {
		t.Fatal(err)
	}
	defer connection.Close()
	service.transport = connection
	response, err := service.EnterSafeState(context.Background(), &mavlinkv1.EnterSafeStateRequest{Reason: "test"})
	if err != nil {
		t.Fatal(err)
	}
	if !response.GetNeutralRequested() || !response.GetHoldRequested() || len(response.GetErrors()) != 0 {
		t.Fatalf("safe response = %#v", response)
	}
	for index, expectedID := range []uint32{mavlinkManualControlMessageID, mavlinkCommandLongMessageID} {
		buffer := make([]byte, 300)
		_ = receiver.SetReadDeadline(time.Now().Add(time.Second))
		count, _, err := receiver.ReadFromUDP(buffer)
		if err != nil {
			t.Fatal(err)
		}
		parsed, err := parseMAVLinkV2Frame(buffer[:count])
		if err != nil || parsed.messageID != expectedID {
			t.Fatalf("safe frame[%d] id=%d err=%v", index, parsed.messageID, err)
		}
	}
}

func TestMAVLinkServiceBuildsUnsignedGCSHeartbeat(t *testing.T) {
	service := NewMAVLinkService(MAVLinkServiceConfig{})
	frame := service.buildHeartbeatFrame()
	parsed, err := parseMAVLinkV2Frame(frame)
	if err != nil || parsed.messageID != mavlinkHeartbeatMessageID || frame[5] != defaultMAVLinkGCSSystemID || frame[6] != defaultMAVLinkGCSComponentID {
		t.Fatalf("GCS heartbeat = %x err=%v", frame, err)
	}
}

type fakeMAVLinkFlightTransport struct {
	frames       [][]byte
	safeRequests []mavlinkSafeStateRequest
}

func (f *fakeMAVLinkFlightTransport) SendFrame(frame []byte) error {
	f.frames = append(f.frames, append([]byte(nil), frame...))
	return nil
}

func (f *fakeMAVLinkFlightTransport) RequestSafeState(reason string, requestDisarm bool) {
	f.safeRequests = append(f.safeRequests, mavlinkSafeStateRequest{reason: reason, requestDisarm: requestDisarm})
}

func (f *fakeMAVLinkFlightTransport) EnterSafeState(_ context.Context, reason string, requestDisarm bool) error {
	f.safeRequests = append(f.safeRequests, mavlinkSafeStateRequest{reason: reason, requestDisarm: requestDisarm})
	return nil
}

func (f *fakeMAVLinkFlightTransport) Close() {}

func mavlinkControlResponseHasCode(t *testing.T, response, code string) bool {
	t.Helper()
	var decoded map[string]interface{}
	if err := json.Unmarshal([]byte(response), &decoded); err != nil {
		t.Fatal(err)
	}
	return decoded["code"] == code
}

func mavlinkControlResponseHasType(t *testing.T, response, kind string) bool {
	t.Helper()
	var decoded map[string]interface{}
	if err := json.Unmarshal([]byte(response), &decoded); err != nil {
		t.Fatal(err)
	}
	return decoded["type"] == kind
}

func testMAVLinkFrame(messageID uint32, payload []byte, systemID, componentID byte) []byte {
	extra, ok := mavlinkCRCExtra(messageID)
	if !ok {
		extra = 0
	}
	frame := make([]byte, len(payload)+12)
	frame[0] = mavlinkV2Magic
	frame[1] = byte(len(payload))
	frame[4] = 7
	frame[5] = systemID
	frame[6] = componentID
	frame[7] = byte(messageID)
	frame[8] = byte(messageID >> 8)
	frame[9] = byte(messageID >> 16)
	copy(frame[10:], payload)
	checksum := mavlinkChecksum(frame[1:10+len(payload)], extra)
	frame[10+len(payload)] = byte(checksum)
	frame[11+len(payload)] = byte(checksum >> 8)
	return frame
}

func testManualControlPayload(target byte) []byte {
	payload := make([]byte, 11)
	negativeAxis := int16(-300)
	binary.LittleEndian.PutUint16(payload[0:2], uint16(int16(math.MaxInt16)))
	binary.LittleEndian.PutUint16(payload[2:4], uint16(int16(200)))
	binary.LittleEndian.PutUint16(payload[4:6], uint16(negativeAxis))
	binary.LittleEndian.PutUint16(payload[6:8], uint16(int16(math.MaxInt16)))
	payload[10] = target
	return payload
}

func testHeartbeatPayload(mode uint32, armed bool) []byte {
	payload := make([]byte, 9)
	binary.LittleEndian.PutUint32(payload[0:4], mode)
	if armed {
		payload[6] = 0x80
	}
	payload[8] = 3
	return payload
}

func testCommandLongPayload(command uint16, param1, param2 float32, systemID, componentID byte) []byte {
	payload := make([]byte, 33)
	binary.LittleEndian.PutUint32(payload[0:4], math.Float32bits(param1))
	binary.LittleEndian.PutUint32(payload[4:8], math.Float32bits(param2))
	binary.LittleEndian.PutUint16(payload[28:30], command)
	payload[30] = systemID
	payload[31] = componentID
	return payload
}

func testSetModePayload(mode uint32, systemID, componentID byte) []byte {
	payload := make([]byte, 6)
	binary.LittleEndian.PutUint32(payload[0:4], mode)
	payload[4] = systemID
	payload[5] = mavlinkCustomModeEnabledBaseMode
	_ = componentID
	return payload
}
