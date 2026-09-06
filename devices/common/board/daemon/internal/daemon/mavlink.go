package daemon

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"strconv"
	"strings"
	"time"
)

const (
	mavlinkV2Magic                     = byte(0xfd)
	mavlinkV2SignedIncompatibilityFlag = byte(0x01)
	mavlinkHeartbeatMessageID          = uint32(0)
	mavlinkSetModeMessageID            = uint32(11)
	mavlinkManualControlMessageID      = uint32(69)
	mavlinkCommandLongMessageID        = uint32(76)
	mavlinkCommandComponentArmDisarm   = uint16(400)
	mavlinkCommandDoSetMode            = uint16(176)
	mavlinkModeManual                  = uint32(0)
	mavlinkModeHold                    = uint32(4)
	mavlinkCustomModeEnabledBaseMode   = byte(1)
	defaultMAVLinkGCSSystemID          = byte(255)
	defaultMAVLinkGCSComponentID       = byte(190)
	defaultMAVLinkPeerOutboundBuffer   = 32
)

type MAVLinkTarget struct {
	SystemID    uint32
	ComponentID uint32
}

type MAVLinkError struct {
	Code    string `json:"code"`
	Message string `json:"message"`
}

type MAVLinkRuntimeStatus struct {
	LinkState      string
	HeartbeatFresh bool
	Target         *MAVLinkTarget
	Armed          bool
	Mode           *string
	Errors         []MAVLinkError
}

func (s MAVLinkRuntimeStatus) StatusPayload(control *MAVLinkControlState, controlKVSReady bool) map[string]interface{} {
	connected, observers := uint32(0), uint32(0)
	var active interface{}
	if control != nil {
		connected, observers = control.PeerCounts()
		if current := control.Active(); current != nil {
			active = map[string]interface{}{
				"sessionId":  current.SessionID,
				"actor":      current.Actor,
				"epoch":      current.Epoch,
				"leaseTtlMs": float64(DefaultMAVLinkActiveTTLMillis),
			}
		}
	}
	target := map[string]interface{}{"systemId": nil, "componentId": nil}
	if s.Target != nil {
		target["systemId"] = s.Target.SystemID
		target["componentId"] = s.Target.ComponentID
	}
	linkState := s.LinkState
	if linkState == "" {
		linkState = "unavailable"
	}
	errors := s.Errors
	if errors == nil {
		errors = []MAVLinkError{}
	}
	return map[string]interface{}{
		"serviceId": MAVLinkCapability,
		"available": controlKVSReady && linkState == "ready" && s.HeartbeatFresh,
		"link": map[string]interface{}{
			"state":                      linkState,
			"heartbeatFresh":             s.HeartbeatFresh,
			"mavlinkWireProtocolVersion": MAVLinkWireProtocolVersion,
			"dialect":                    MAVLinkDialect,
		},
		"target":        target,
		"armed":         s.Armed,
		"mode":          s.Mode,
		"peers":         map[string]interface{}{"connected": connected, "observers": observers},
		"activeControl": active,
		"errors":        errors,
	}
}

func MAVLinkUnavailableStatus(message string) MAVLinkRuntimeStatus {
	status := MAVLinkRuntimeStatus{LinkState: "unavailable"}
	if strings.TrimSpace(message) != "" {
		status.Errors = []MAVLinkError{{Code: "service_unavailable", Message: message}}
	}
	return status
}

type MAVLinkActiveControl struct {
	SessionID string `json:"sessionId"`
	Actor     string `json:"actor"`
	Epoch     uint64 `json:"epoch"`
	ExpiresAt uint64 `json:"-"`
}

type MAVLinkPeer struct {
	SessionID string
	Outbound  chan []byte
	Dropped   uint64
}

type MAVLinkControlState struct {
	active           *MAVLinkActiveControl
	nextEpoch        uint64
	nextSession      uint64
	leaseTTL         time.Duration
	watchdog         time.Duration
	lastAcceptedAtMS uint64
	watchdogTripped  bool
	peers            map[string]*MAVLinkPeer
}

func NewMAVLinkControlState(leaseTTL, watchdog time.Duration) *MAVLinkControlState {
	return &MAVLinkControlState{
		leaseTTL: leaseTTL,
		watchdog: watchdog,
		peers:    make(map[string]*MAVLinkPeer),
	}
}

func (s *MAVLinkControlState) OpenPeer() *MAVLinkPeer {
	s.nextSession++
	sessionID := fmt.Sprintf("mavlink-%d", s.nextSession)
	peer := &MAVLinkPeer{
		SessionID: sessionID,
		Outbound:  make(chan []byte, defaultMAVLinkPeerOutboundBuffer),
	}
	s.peers[sessionID] = peer
	return peer
}

// ClosePeer returns true only when the active owner has gone away and a
// neutral/Hold request must be sent immediately.
func (s *MAVLinkControlState) ClosePeer(sessionID string) bool {
	delete(s.peers, sessionID)
	if s.active == nil || s.active.SessionID != sessionID {
		return false
	}
	s.active = nil
	s.lastAcceptedAtMS = 0
	s.watchdogTripped = false
	return true
}

func (s *MAVLinkControlState) Active() *MAVLinkActiveControl {
	if s.active == nil {
		return nil
	}
	copy := *s.active
	return &copy
}

func (s *MAVLinkControlState) PeerCounts() (connected, observers uint32) {
	connected = uint32(len(s.peers))
	observers = connected
	if s.active != nil {
		observers--
	}
	return connected, observers
}

func (s *MAVLinkControlState) State() map[string]interface{} {
	return map[string]interface{}{
		"epoch":         s.nextEpoch,
		"leaseTtlMs":    float64(durationMillis(s.leaseTTL)),
		"activeControl": s.Active(),
	}
}

func (s *MAVLinkControlState) ClearExpired(nowMS uint64) bool {
	if s.active == nil || s.active.ExpiresAt > nowMS {
		return false
	}
	s.active = nil
	s.lastAcceptedAtMS = 0
	s.watchdogTripped = false
	return true
}

// Activate is atomic with respect to the control state. A successful
// takeover intentionally returns safe=false: the safety watchdog owns the
// later neutral/Hold decision and must not be triggered by a handoff.
func (s *MAVLinkControlState) Activate(sessionID, actor string, takeover bool, nowMS uint64) (*MAVLinkActiveControl, error) {
	s.ClearExpired(nowMS)
	if _, ok := s.peers[sessionID]; !ok {
		return nil, errors.New("unknown peer session")
	}
	if s.active != nil && s.active.SessionID != sessionID && !takeover {
		return nil, errMAVLinkControlBusy
	}
	if s.active != nil && s.active.SessionID == sessionID {
		s.active.ExpiresAt = nowMS + durationMillis(s.leaseTTL)
		return s.Active(), nil
	}
	s.nextEpoch++
	s.active = &MAVLinkActiveControl{
		SessionID: sessionID,
		Actor:     actor,
		Epoch:     s.nextEpoch,
		ExpiresAt: nowMS + durationMillis(s.leaseTTL),
	}
	s.lastAcceptedAtMS = 0
	s.watchdogTripped = false
	return s.Active(), nil
}

func (s *MAVLinkControlState) Renew(sessionID string, epoch, nowMS uint64) (*MAVLinkActiveControl, error) {
	if _, err := s.EnsureActive(sessionID, epoch, nowMS); err != nil {
		return nil, err
	}
	s.active.ExpiresAt = nowMS + durationMillis(s.leaseTTL)
	return s.Active(), nil
}

// Release returns true when the caller owned control and therefore needs a
// neutral/Hold request before the rover is left unattended.
func (s *MAVLinkControlState) Release(sessionID string, epoch, nowMS uint64) (bool, error) {
	if _, err := s.EnsureActive(sessionID, epoch, nowMS); err != nil {
		return false, err
	}
	s.active = nil
	s.lastAcceptedAtMS = 0
	s.watchdogTripped = false
	return true, nil
}

func (s *MAVLinkControlState) EnsureActive(sessionID string, epoch, nowMS uint64) (*MAVLinkActiveControl, error) {
	s.ClearExpired(nowMS)
	if s.active == nil || s.active.SessionID != sessionID || s.active.Epoch != epoch {
		return nil, errMAVLinkStaleEpoch
	}
	return s.Active(), nil
}

func (s *MAVLinkControlState) AcceptControlFrame(sessionID string, epoch uint64, frame []byte, nowMS uint64) error {
	if err := s.AuthorizeControlFrame(sessionID, epoch, frame, nowMS); err != nil {
		return err
	}
	s.RecordAcceptedControlFrame(frame, nowMS)
	return nil
}

// AuthorizeControlFrame verifies active ownership and complete MAVLink 2 frame
// boundaries without interpreting the MAVLink message. The WebRTC channel is
// an opaque MAVLink tunnel: its active client may use the flight controller's
// full dialect and source identity. Callers record accepted input only after
// the local transport handoff succeeds.
func (s *MAVLinkControlState) AuthorizeControlFrame(sessionID string, epoch uint64, frame []byte, nowMS uint64) error {
	if _, err := s.EnsureActive(sessionID, epoch, nowMS); err != nil {
		return err
	}
	return validateMAVLinkV2TunnelFrame(frame)
}

// RecordAcceptedControlFrame advances the drive-input watchdog only for a
// MANUAL_CONTROL frame. Arm, mode, and heartbeat commands establish or retain
// the active-control session but must not turn a ready-to-drive session back
// into view-only mode merely because the operator is momentarily idle.
func (s *MAVLinkControlState) RecordAcceptedControlFrame(frame []byte, nowMS uint64) {
	parsed, err := parseMAVLinkV2Frame(frame)
	if err != nil || parsed.messageID != mavlinkManualControlMessageID {
		return
	}
	s.lastAcceptedAtMS = nowMS
	s.watchdogTripped = false
}

// WatchdogExpired returns true once per accepted drive-input gap. It does not
// clear active ownership or change flight mode; the runtime requests neutral
// control while the flight controller remains ready for the next input.
func (s *MAVLinkControlState) WatchdogExpired(nowMS uint64) bool {
	if s.active == nil || s.lastAcceptedAtMS == 0 || s.watchdogTripped {
		return false
	}
	if nowMS-s.lastAcceptedAtMS < durationMillis(s.watchdog) {
		return false
	}
	s.watchdogTripped = true
	return true
}

func (s *MAVLinkControlState) BroadcastTelemetry(frame []byte) {
	for _, peer := range s.peers {
		copy := append([]byte(nil), frame...)
		select {
		case peer.Outbound <- copy:
		default:
			peer.Dropped++
		}
	}
}

var (
	errMAVLinkControlBusy = errors.New("active control busy")
	errMAVLinkStaleEpoch  = errors.New("stale active control epoch")
)

type mavlinkControlRequest struct {
	Type      string  `json:"type"`
	RequestID string  `json:"requestId"`
	Actor     string  `json:"actor"`
	Takeover  *bool   `json:"takeover"`
	Epoch     *uint64 `json:"epoch"`
}

type MAVLinkControlResult struct {
	Response      string
	StatusChanged bool
	SafeRequired  bool
}

func (s *MAVLinkControlState) HandleControlMessage(sessionID, encoded string, nowMS uint64) MAVLinkControlResult {
	request, err := parseMAVLinkControlRequest(encoded)
	if err != nil {
		return MAVLinkControlResult{Response: mavlinkControlError(request.RequestID, "invalid_request", "invalid MAVLink control request")}
	}
	switch request.Type {
	case "control.get_state":
		return MAVLinkControlResult{Response: mavlinkControlSuccess("control.state", request.RequestID, s.State())}
	case "control.activate":
		if request.Takeover == nil || strings.TrimSpace(request.Actor) == "" {
			return MAVLinkControlResult{Response: mavlinkControlError(request.RequestID, "invalid_request", "activate requires actor and takeover")}
		}
		if _, err := s.Activate(sessionID, strings.TrimSpace(request.Actor), *request.Takeover, nowMS); err != nil {
			return MAVLinkControlResult{Response: mavlinkControlErrorFor(request.RequestID, err)}
		}
		return MAVLinkControlResult{Response: mavlinkControlSuccess("control.activated", request.RequestID, s.State()), StatusChanged: true}
	case "control.renew_active":
		if request.Epoch == nil {
			return MAVLinkControlResult{Response: mavlinkControlError(request.RequestID, "invalid_request", "renew_active requires epoch")}
		}
		if _, err := s.Renew(sessionID, *request.Epoch, nowMS); err != nil {
			return MAVLinkControlResult{Response: mavlinkControlErrorFor(request.RequestID, err)}
		}
		// Renewal extends only the daemon-local expiry. The externally reported
		// control identity and lease duration remain unchanged, so publishing a
		// named-shadow update here would create periodic no-op shadow writes.
		return MAVLinkControlResult{Response: mavlinkControlSuccess("control.renewed", request.RequestID, s.State())}
	case "control.release_active":
		if request.Epoch == nil {
			return MAVLinkControlResult{Response: mavlinkControlError(request.RequestID, "invalid_request", "release_active requires epoch")}
		}
		safe, err := s.Release(sessionID, *request.Epoch, nowMS)
		if err != nil {
			return MAVLinkControlResult{Response: mavlinkControlErrorFor(request.RequestID, err)}
		}
		return MAVLinkControlResult{Response: mavlinkControlSuccess("control.released", request.RequestID, s.State()), StatusChanged: true, SafeRequired: safe}
	default:
		return MAVLinkControlResult{Response: mavlinkControlError(request.RequestID, "invalid_request", "unsupported MAVLink control request")}
	}
}

func parseMAVLinkControlRequest(encoded string) (mavlinkControlRequest, error) {
	decoder := json.NewDecoder(bytes.NewBufferString(encoded))
	decoder.UseNumber()
	var raw map[string]interface{}
	if err := decoder.Decode(&raw); err != nil {
		return mavlinkControlRequest{}, err
	}
	var extra interface{}
	if err := decoder.Decode(&extra); err != io.EOF || len(raw) == 0 {
		return mavlinkControlRequest{}, errors.New("invalid request object")
	}
	typeName, ok := raw["type"].(string)
	if !ok {
		return mavlinkControlRequest{}, errors.New("request type is required")
	}
	requestID, ok := raw["requestId"].(string)
	if !ok || len(requestID) == 0 || len(requestID) > 128 {
		return mavlinkControlRequest{}, errors.New("request ID is invalid")
	}
	allowed := map[string]struct{}{"type": {}, "requestId": {}}
	request := mavlinkControlRequest{Type: typeName, RequestID: requestID}
	switch typeName {
	case "control.get_state":
	case "control.activate":
		allowed["actor"] = struct{}{}
		allowed["takeover"] = struct{}{}
		actor, actorOK := raw["actor"].(string)
		takeover, takeoverOK := raw["takeover"].(bool)
		if !actorOK || len(strings.TrimSpace(actor)) == 0 || len(actor) > 256 || !takeoverOK {
			return request, errors.New("activate request is invalid")
		}
		request.Actor = actor
		request.Takeover = &takeover
	case "control.renew_active", "control.release_active":
		allowed["epoch"] = struct{}{}
		epochValue, epochOK := raw["epoch"].(json.Number)
		if !epochOK {
			return request, errors.New("epoch is required")
		}
		epoch, err := strconv.ParseUint(epochValue.String(), 10, 64)
		if err != nil {
			return request, errors.New("epoch is invalid")
		}
		request.Epoch = &epoch
	default:
		return request, errors.New("unsupported request type")
	}
	for key := range raw {
		if _, ok := allowed[key]; !ok {
			return request, errors.New("request has unsupported fields")
		}
	}
	return request, nil
}

func mavlinkControlSuccess(kind, requestID string, state map[string]interface{}) string {
	encoded, _ := json.Marshal(map[string]interface{}{
		"type":      kind,
		"requestId": requestID,
		"state":     state,
	})
	return string(encoded)
}

func mavlinkControlError(requestID, code, message string) string {
	encoded, _ := json.Marshal(map[string]string{
		"type":      "control.error",
		"requestId": requestID,
		"code":      code,
		"message":   message,
	})
	return string(encoded)
}

func mavlinkControlErrorFor(requestID string, err error) string {
	if errors.Is(err, errMAVLinkControlBusy) {
		return mavlinkControlError(requestID, "control_busy", err.Error())
	}
	if errors.Is(err, errMAVLinkStaleEpoch) {
		return mavlinkControlError(requestID, "stale_epoch", err.Error())
	}
	return mavlinkControlError(requestID, "invalid_request", err.Error())
}

type parsedMAVLinkFrame struct {
	messageID uint32
	payload   []byte
}

// validateMAVLinkV2TunnelFrame intentionally validates only boundaries. The
// tunnel cannot validate a generic MAVLink checksum without selecting a
// dialect, and selecting a dialect would reintroduce message filtering. The
// flight controller remains the protocol authority and discards invalid frames.
func validateMAVLinkV2TunnelFrame(frame []byte) error {
	if len(frame) < 12 || frame[0] != mavlinkV2Magic {
		return errors.New("MAVLink tunnel requires a complete MAVLink 2 frame")
	}
	expectedLength := int(frame[1]) + 12
	if frame[2]&mavlinkV2SignedIncompatibilityFlag != 0 {
		expectedLength += 13
	}
	if len(frame) != expectedLength {
		return errors.New("MAVLink 2 frame length is invalid")
	}
	return nil
}

func parseMAVLinkV2Frame(frame []byte) (parsedMAVLinkFrame, error) {
	if err := validateMAVLinkV2TunnelFrame(frame); err != nil {
		return parsedMAVLinkFrame{}, err
	}
	payloadLength := int(frame[1])
	messageID := uint32(frame[7]) | uint32(frame[8])<<8 | uint32(frame[9])<<16
	extra, ok := mavlinkCRCExtra(messageID)
	if !ok {
		return parsedMAVLinkFrame{}, fmt.Errorf("unsupported MAVLink common message %d", messageID)
	}
	checksum := uint16(frame[10+payloadLength]) | uint16(frame[11+payloadLength])<<8
	calculated := mavlinkChecksum(frame[1:10+payloadLength], extra)
	if checksum != calculated {
		return parsedMAVLinkFrame{}, errors.New("MAVLink frame checksum is invalid")
	}
	return parsedMAVLinkFrame{messageID: messageID, payload: frame[10 : 10+payloadLength]}, nil
}

func mavlinkCRCExtra(messageID uint32) (byte, bool) {
	switch messageID {
	case mavlinkHeartbeatMessageID:
		return 50, true
	case mavlinkSetModeMessageID:
		return 89, true
	case mavlinkManualControlMessageID:
		return 243, true
	case mavlinkCommandLongMessageID:
		return 152, true
	default:
		return 0, false
	}
}

func mavlinkChecksum(data []byte, extra byte) uint16 {
	checksum := uint16(0xffff)
	for _, value := range data {
		checksum = mavlinkCRCAccumulate(value, checksum)
	}
	return mavlinkCRCAccumulate(extra, checksum)
}

func mavlinkCRCAccumulate(value byte, checksum uint16) uint16 {
	temp := uint8(value) ^ uint8(checksum&0xff)
	temp ^= temp << 4
	return (checksum >> 8) ^ (uint16(temp) << 8) ^ (uint16(temp) << 3) ^ (uint16(temp) >> 4)
}
