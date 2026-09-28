package companion

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/netip"
	"time"
)

type leaseRequest struct {
	kind, id       string
	sent, deadline time.Time
	arm            []byte
}
type bridgeLease struct {
	epoch             uint64
	sessionID, actor  string
	deadline, renewAt time.Time
}
type leaseState struct {
	Epoch  *uint64 `json:"epoch"`
	TTL    int     `json:"leaseTtlMs"`
	Active *struct {
		SessionID string  `json:"sessionId"`
		Actor     string  `json:"actor"`
		Epoch     *uint64 `json:"epoch"`
	} `json:"activeControl"`
}
type leaseResponse struct {
	Type  string     `json:"type"`
	ID    string     `json:"requestId"`
	Code  string     `json:"code"`
	State leaseState `json:"state"`
}

func (s leaseState) valid() bool {
	return s.Epoch != nil && s.TTL == 5000 && s.Active != nil && s.Active.SessionID != "" && s.Active.Actor != "" && s.Active.Epoch != nil && *s.Active.Epoch == *s.Epoch
}
func (b *UDPBridge) attach(s Session, now time.Time) {
	b.session, b.connectedAt = s, now
}
func (b *UDPBridge) send(kind byte, payload []byte) error {
	if b.session == nil {
		return errors.New("bridge is observing without a WebRTC connection")
	}
	ctx, cancel := context.WithTimeout(context.Background(), b.Limits.Send)
	defer cancel()
	return b.session.Send(ctx, kind, payload)
}
func (b *UDPBridge) request(kind string, now time.Time, arm []byte) error {
	b.serial++ // Never reuse request IDs across WebRTC sessions.
	id := fmt.Sprintf("udp-%d", b.serial)
	request := map[string]any{"type": kind, "requestId": id}
	if kind == "control.activate" {
		request["actor"] = "qgroundcontrol:" + b.source.String()
		request["takeover"] = false
	} else {
		request["epoch"] = b.active.epoch
	}
	payload, _ := json.Marshal(request)
	b.pending = &leaseRequest{kind, id, now, now.Add(b.Limits.Response), append([]byte(nil), arm...)}
	return b.send('J', payload)
}
func (b *UDPBridge) release() {
	active := b.active
	b.active, b.pending, b.disarm, b.frames = nil, nil, nil, nil // Fence uplink before requesting release.
	if active != nil {
		b.serial++
		payload, _ := json.Marshal(map[string]any{"type": "control.release_active", "requestId": fmt.Sprintf("udp-%d", b.serial), "epoch": active.epoch})
		_ = b.send('J', payload) // Disconnect/board expiry is the final boundary if delivery fails.
	}
}
func (b *UDPBridge) detach() {
	b.release()
	b.session = nil
}
func (b *UDPBridge) tick(now time.Time) error {
	if b.source.IsValid() && now.Sub(b.lastSeen) >= b.Limits.Idle {
		// An activation may have won but its response is still in flight. Close
		// that peer, rather than allow a late success to arm a new UDP sender.
		unresolved := b.pending != nil && b.pending.kind == "control.activate"
		b.release()
		b.source = netip.AddrPort{}
		if unresolved {
			return errors.New("sender expired during lease acquisition")
		}
	}
	if b.disarm != nil {
		if !now.Before(b.disarmDeadline) {
			b.release()
		}
		return nil
	}
	if b.pending != nil && !now.Before(b.pending.deadline) {
		return errors.New("board lease response timed out") // Closing the peer also clears any unacknowledged grant.
	}
	if b.active != nil {
		if !now.Before(b.active.deadline) {
			return errors.New("board lease expired")
		}
		if b.pending == nil && !now.Before(b.active.renewAt) {
			return b.request("control.renew_active", now, nil)
		}
	}
	return nil
}
func (b *UDPBridge) uplink(packet udpPacket, now time.Time) error {
	frames, err := SplitMAVLink(packet.payload)
	if err != nil {
		return nil
	}
	if err := b.tick(now); err != nil {
		return err
	}
	if now.Sub(packet.at) >= b.Limits.Idle {
		return nil
	}
	if !b.source.IsValid() {
		b.source = packet.source
	}
	if packet.source != b.source || packet.at.Before(b.lastSeen) {
		return nil
	}
	b.lastSeen = packet.at
	if b.session == nil || packet.at.Before(b.connectedAt) || b.disarm != nil {
		return nil
	}
	if b.active == nil {
		for _, frame := range frames {
			command, recognized := decodeArmCommand(frame)
			if recognized && command.arm && b.pending == nil {
				return b.request("control.activate", now, frame)
			}
		}
		return nil // Every other pre-arm frame is discarded, including parameter requests.
	}
	b.frames = frames // Forward one frame per supervisor turn, keeping deadlines/responses responsive.
	return nil
}

// forward processes one queued frame. The supervisor holds further UDP reads
// until this datagram is drained, while still handling lease responses, source
// deadlines and shutdown between frames. No large datagram can monopolize it.
func (b *UDPBridge) forward(now time.Time) error {
	if err := b.tick(now); err != nil {
		return err
	}
	if len(b.frames) == 0 || b.active == nil || b.disarm != nil {
		return nil
	}
	frame := b.frames[0]
	b.frames = b.frames[1:]
	if err := b.send('B', frame); err != nil {
		return err
	}
	command, recognized := decodeArmCommand(frame)
	if recognized && !command.arm {
		b.disarm = &command
		b.disarmDeadline = now.Add(b.Limits.Disarm)
		b.frames = nil // Hold subsequent uplink while disarm finishes.
	}
	return nil
}
func (b *UDPBridge) downlink(event Event, now time.Time) error {
	if err := b.tick(now); err != nil {
		return err
	}
	if event.Kind == 'J' {
		return b.response(event.Payload, now)
	}
	frames, err := SplitMAVLink(event.Payload)
	if err != nil || len(frames) != 1 {
		return nil
	} // WebRTC requires exactly one complete frame.
	frame := frames[0]
	if b.disarm != nil && disarmAcknowledged(frame, *b.disarm) {
		b.release() // Do not let a blocked UDP telemetry write delay control release.
	}
	if b.source.IsValid() {
		_ = b.writeTelemetry(b.source, frame)
	}
	return nil
}
func (b *UDPBridge) response(payload []byte, now time.Time) error {
	var response leaseResponse
	if json.Unmarshal(payload, &response) != nil || b.pending == nil || response.ID != b.pending.id {
		return nil
	}
	pending := b.pending
	if response.Type == "control.error" {
		if pending.kind == "control.activate" && response.Code == "control_busy" {
			b.pending = nil // Remain an observer; retry only on a fresh arm datagram.
			return nil
		}
		return errors.New("board rejected the control lease")
	}
	expected := "control.activated"
	if pending.kind == "control.renew_active" {
		expected = "control.renewed"
	}
	if response.Type != expected {
		return nil
	}
	state := response.State
	if !state.valid() {
		return errors.New("invalid board lease response")
	}
	if pending.kind == "control.activate" {
		// Save the epoch before validating ownership so cleanup can release a
		// malformed grant as well. Board release checks this peer and epoch.
		b.active = &bridgeLease{*state.Epoch, state.Active.SessionID, state.Active.Actor, pending.sent.Add(5 * time.Second), now.Add(b.Limits.Renew)}
		if state.Active.Actor != "qgroundcontrol:"+b.source.String() {
			return errors.New("board lease actor mismatch")
		}
		b.pending = nil
		return b.send('B', pending.arm) // The exact original arm is sent only after the grant.
	}
	if b.active == nil || *state.Epoch != b.active.epoch || state.Active.SessionID != b.active.sessionID || state.Active.Actor != b.active.actor {
		return errors.New("board lease ownership changed")
	}
	b.active.deadline = pending.sent.Add(5 * time.Second)
	b.active.renewAt = now.Add(b.Limits.Renew)
	b.pending = nil
	return nil
}
