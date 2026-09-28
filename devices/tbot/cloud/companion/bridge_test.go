package companion

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"net/netip"
	"testing"
	"time"
)

type recordingSession struct {
	events chan Event
	sent   []Event
	fail   bool
}

func (s *recordingSession) Events() <-chan Event { return s.events }
func (s *recordingSession) Close() error         { return nil }
func (s *recordingSession) Send(ctx context.Context, kind byte, payload []byte) error {
	if s.fail {
		return errors.New("send failed")
	}
	s.sent = append(s.sent, Event{kind, append([]byte(nil), payload...)})
	return ctx.Err()
}

var sender = netip.MustParseAddrPort("127.0.0.1:20000")
var contender = netip.MustParseAddrPort("[::1]:20001")

func bridgeSetup() (*UDPBridge, *recordingSession, time.Time) {
	s := &recordingSession{events: make(chan Event, 64)}
	now := time.Unix(100, 0)
	b := &UDPBridge{Limits: DefaultBridgeLimits(), writeTelemetry: func(netip.AddrPort, []byte) error { return nil }}
	b.attach(s, now)
	return b, s, now
}
func feedUDP(b *UDPBridge, packet udpPacket, now time.Time) error {
	if err := b.uplink(packet, now); err != nil {
		return err
	}
	for len(b.frames) > 0 {
		if err := b.forward(now); err != nil {
			return err
		}
	}
	return nil
}
func packetAt(source netip.AddrPort, frame []byte, now time.Time) udpPacket {
	return udpPacket{source, frame, now}
}
func requestMap(t *testing.T, e Event) map[string]any {
	t.Helper()
	var m map[string]any
	if e.Kind != 'J' || json.Unmarshal(e.Payload, &m) != nil {
		t.Fatalf("not JSON request: %v", e)
	}
	return m
}
func grant(id, kind, actor string, epoch uint64) []byte {
	data, _ := json.Marshal(map[string]any{"type": kind, "requestId": id, "state": map[string]any{"epoch": epoch, "leaseTtlMs": 5000, "activeControl": map[string]any{"sessionId": "board-peer", "actor": actor, "epoch": epoch}}})
	return data
}
func activate(t *testing.T, b *UDPBridge, s *recordingSession, now time.Time, frame []byte) {
	t.Helper()
	if err := feedUDP(b, packetAt(sender, frame, now), now); err != nil {
		t.Fatal(err)
	}
	request := requestMap(t, s.sent[len(s.sent)-1])
	if request["type"] != "control.activate" || request["takeover"] != false {
		t.Fatal("takeover or wrong request", request)
	}
	if err := b.downlink(Event{'J', grant(request["requestId"].(string), "control.activated", request["actor"].(string), 7)}, now); err != nil {
		t.Fatal(err)
	}
	if s.sent[len(s.sent)-1].Kind != 'B' || !bytes.Equal(s.sent[len(s.sent)-1].Payload, frame) {
		t.Fatal("original arm not forwarded after grant")
	}
}
func TestObserverSelectionAndBusyBoard(t *testing.T) {
	b, s, now := bridgeSetup()
	telemetry := unfamiliarFrame(4, true)
	var addresses []netip.AddrPort
	var received [][]byte
	b.writeTelemetry = func(addr netip.AddrPort, frame []byte) error {
		addresses = append(addresses, addr)
		received = append(received, append([]byte(nil), frame...))
		return nil
	}
	if err := feedUDP(b, packetAt(contender, []byte{0xfd}, now), now); err != nil {
		t.Fatal(err)
	}
	if b.source.IsValid() {
		t.Fatal("malformed packet selected sender")
	}
	// Includes a parameter-list request (message 21), entirely held before arm.
	params := unfamiliarFrame(2, false)
	params[7] = 21
	params[8] = 0
	params[9] = 0
	feedUDP(b, packetAt(sender, params, now), now)
	feedUDP(b, packetAt(contender, vector("long-arm"), now.Add(time.Second)), now.Add(time.Second))
	b.downlink(Event{'B', telemetry}, now.Add(time.Second))
	if len(s.sent) != 0 || len(addresses) != 1 || addresses[0] != sender || !bytes.Equal(received[0], telemetry) || !b.lastSeen.Equal(now) {
		t.Fatal("observer/source gate failed")
	}
	feedUDP(b, packetAt(sender, vector("long-arm"), now.Add(time.Second)), now.Add(time.Second))
	req := requestMap(t, s.sent[0])
	if req["takeover"] != false {
		t.Fatal("takeover enabled")
	}
	id := req["requestId"].(string)
	b.downlink(Event{'J', []byte(`{"type":"control.error","requestId":"` + id + `","code":"control_busy"}`)}, now.Add(time.Second))
	if b.active != nil || b.pending != nil || len(s.sent) != 1 {
		t.Fatal("busy board displaced or arm forwarded")
	}
	b.downlink(Event{'B', telemetry}, now.Add(1500*time.Millisecond))
	feedUDP(b, packetAt(sender, params, now.Add(1500*time.Millisecond)), now.Add(1500*time.Millisecond))
	if len(received) != 2 || len(s.sent) != 1 {
		t.Fatal("busy board observer behavior failed")
	}
	activate(t, b, s, now.Add(2*time.Second), vector("int-arm"))
}
func TestActiveOpaqueFramesAndDatagramAtomicity(t *testing.T) {
	b, s, now := bridgeSetup()
	arm := signedFrame(vector("long-arm"), 152)
	// The pre-arm frame after the arm is not buffered/replayed after activation.
	combined := append(append([]byte(nil), arm...), unfamiliarFrame(3, true)...)
	feedUDP(b, packetAt(sender, combined, now), now)
	req := requestMap(t, s.sent[0])
	b.downlink(Event{'J', grant(req["requestId"].(string), "control.activated", req["actor"].(string), 7)}, now)
	if len(s.sent) != 2 || !bytes.Equal(s.sent[1].Payload, arm) {
		t.Fatal("pre-arm traffic replayed")
	}
	known := vector("long-arm")
	unknown := unfamiliarFrame(255, true)
	combined = append(append([]byte(nil), known...), unknown...)
	feedUDP(b, packetAt(sender, combined, now.Add(time.Millisecond)), now.Add(time.Millisecond))
	if len(s.sent) != 4 || !bytes.Equal(s.sent[2].Payload, known) || !bytes.Equal(s.sent[3].Payload, unknown) {
		t.Fatal("active tunnel rewrote or filtered frames")
	}
	feedUDP(b, packetAt(sender, append(combined, 0xfd), now.Add(2*time.Millisecond)), now.Add(2*time.Millisecond))
	if len(s.sent) != 4 {
		t.Fatal("partially forwarded malformed datagram")
	}
	count := 0
	b.writeTelemetry = func(netip.AddrPort, []byte) error { count++; return nil }
	for _, bad := range [][]byte{combined, unknown[:len(unknown)-1], {0xfd}} {
		b.downlink(Event{'B', bad}, now)
	}
	if count != 0 {
		t.Fatal("invalid WebRTC message forwarded")
	}
}
func TestInvalidArmCannotAcquire(t *testing.T) {
	for _, frame := range [][]byte{vector("long-disarm"), vector("int-disarm"), unfamiliarFrame(30, true)} {
		b, s, now := bridgeSetup()
		feedUDP(b, packetAt(sender, frame, now), now)
		if len(s.sent) != 0 {
			t.Fatal("non-arm acquired")
		}
	}
	b, s, now := bridgeSetup()
	frame := vector("long-arm")
	frame[len(frame)-1] ^= 1
	feedUDP(b, packetAt(sender, frame, now), now)
	if len(s.sent) != 0 {
		t.Fatal("CRC-invalid arm acquired")
	}
}
func TestRenewalAndSelectedSenderInactivity(t *testing.T) {
	b, s, now := bridgeSetup()
	activate(t, b, s, now, vector("long-arm"))
	feedUDP(b, packetAt(sender, unfamiliarFrame(0, false), now.Add(time.Second)), now.Add(time.Second))
	b.tick(now.Add(2 * time.Second))
	request := requestMap(t, s.sent[len(s.sent)-1])
	if request["type"] != "control.renew_active" || request["epoch"] != float64(7) {
		t.Fatal("bad renewal", request)
	}
	b.downlink(Event{'J', grant("wrong-id", "control.renewed", b.active.actor, 7)}, now.Add(2*time.Second))
	if b.pending == nil {
		t.Fatal("unmatched response accepted")
	}
	b.downlink(Event{'J', grant(request["requestId"].(string), "control.renewed", b.active.actor, 7)}, now.Add(2*time.Second))
	// Renew again, but traffic from a competing address cannot extend sender life.
	feedUDP(b, packetAt(contender, vector("long-arm"), now.Add(4*time.Second)), now.Add(4*time.Second))
	request = requestMap(t, s.sent[len(s.sent)-1])
	b.downlink(Event{'J', grant(request["requestId"].(string), "control.renewed", b.active.actor, 7)}, now.Add(4*time.Second))
	b.tick(now.Add(6 * time.Second))
	if b.active != nil || b.source.IsValid() || b.pending != nil {
		t.Fatal("other sender kept control alive")
	}
	last := requestMap(t, s.sent[len(s.sent)-1])
	if last["type"] != "control.release_active" {
		t.Fatal("idle did not release")
	}
	count := len(s.sent)
	b.tick(now.Add(10 * time.Second))
	if len(s.sent) != count {
		t.Fatal("renewed after release")
	}
	feedUDP(b, packetAt(contender, unfamiliarFrame(0, false), now.Add(10*time.Second)), now.Add(10*time.Second))
	if b.source != contender || b.active != nil || len(s.sent) != count {
		t.Fatal("replacement sender got implicit control")
	}
}
func TestDisarmReleaseAfterAckOrOneSecond(t *testing.T) {
	for _, name := range []string{"long-disarm", "int-disarm"} {
		for _, ack := range []bool{true, false} {
			t.Run(name+map[bool]string{true: "-ack", false: "-timeout"}[ack], func(t *testing.T) {
				b, s, now := bridgeSetup()
				activate(t, b, s, now, vector("long-arm"))
				disarm := vector(name)
				at := now.Add(100 * time.Millisecond)
				if err := feedUDP(b, packetAt(sender, disarm, at), at); err != nil {
					t.Fatal(err)
				}
				if !bytes.Equal(s.sent[len(s.sent)-1].Payload, disarm) || b.active == nil || b.disarm == nil {
					t.Fatal("disarm not forwarded before waiting")
				}
				count := len(s.sent)
				feedUDP(b, packetAt(sender, vector("long-arm"), at.Add(time.Millisecond)), at.Add(time.Millisecond))
				if len(s.sent) != count {
					t.Fatal("rearmed while waiting for disarm")
				}
				if ack {
					b.downlink(Event{'B', vector("ack")}, at.Add(time.Millisecond))
				} else {
					b.tick(at.Add(time.Second - time.Nanosecond))
					if b.active == nil {
						t.Fatal("released before wait bound")
					}
					b.tick(at.Add(time.Second))
				}
				if b.active != nil || requestMap(t, s.sent[len(s.sent)-1])["type"] != "control.release_active" {
					t.Fatal("did not release")
				}
				feedUDP(b, packetAt(sender, unfamiliarFrame(0, false), at.Add(time.Second)), at.Add(time.Second))
				if b.active != nil {
					t.Fatal("control resumed without arm")
				}
				activate(t, b, s, at.Add(time.Second), vector("int-arm"))
			})
		}
	}
}
func TestDisarmIgnoresInvalidUnrelatedAndInProgressAck(t *testing.T) {
	b, s, now := bridgeSetup()
	activate(t, b, s, now, vector("long-arm"))
	feedUDP(b, packetAt(sender, vector("long-disarm"), now), now)
	bad := vector("ack")
	bad[len(bad)-1] ^= 1
	wrongSystem := vector("ack")
	wrongSystem[5] = 2
	testChecksum(wrongSystem, 143)
	wrongTarget := vector("ack")
	wrongTarget[18] = 1
	testChecksum(wrongTarget, 143)
	inProgress := vector("ack")
	inProgress[12] = 5
	testChecksum(inProgress, 143)
	for _, frame := range [][]byte{bad, wrongSystem, wrongTarget, inProgress} {
		b.downlink(Event{'B', frame}, now)
		if b.active == nil {
			t.Fatal("unrelated ACK released")
		}
	}
	b.downlink(Event{'B', vector("truncated-ack")}, now)
	if b.active != nil {
		t.Fatal("zero-truncated ACK not recognized")
	}
}
func TestLeaseTimeoutErrorsAndSessionFencing(t *testing.T) {
	for _, kind := range []string{"activation-timeout", "renew-timeout", "wrong-epoch", "invalid-state", "send-failure", "pending-idle"} {
		t.Run(kind, func(t *testing.T) {
			b, s, now := bridgeSetup()
			var err error
			if kind == "activation-timeout" || kind == "pending-idle" {
				feedUDP(b, packetAt(sender, vector("long-arm"), now), now)
				when := now.Add(time.Second)
				if kind == "pending-idle" {
					when = now.Add(5 * time.Second)
				}
				err = b.tick(when)
			} else {
				activate(t, b, s, now, vector("long-arm"))
				if kind == "send-failure" {
					s.fail = true
					err = feedUDP(b, packetAt(sender, unfamiliarFrame(0, false), now), now)
				} else {
					b.tick(now.Add(2 * time.Second))
					req := requestMap(t, s.sent[len(s.sent)-1])
					id := req["requestId"].(string)
					switch kind {
					case "renew-timeout":
						err = b.tick(now.Add(3 * time.Second))
					case "wrong-epoch":
						err = b.downlink(Event{'J', grant(id, "control.renewed", b.active.actor, 8)}, now.Add(2*time.Second))
					case "invalid-state":
						err = b.downlink(Event{'J', []byte(`{"type":"control.renewed","requestId":"` + id + `","state":{}}`)}, now.Add(2*time.Second))
					}
				}
			}
			if err == nil {
				t.Fatal("unsafe lease state retained")
			}
			b.detach()
			if b.active != nil || b.pending != nil || b.session != nil {
				t.Fatal("failed peer retained authority")
			}
		})
	}
	b, s, now := bridgeSetup()
	feedUDP(b, packetAt(sender, vector("long-arm"), now), now)
	old := requestMap(t, s.sent[0])
	b.detach()
	replacement := &recordingSession{}
	b.attach(replacement, now.Add(time.Second))
	feedUDP(b, packetAt(sender, vector("long-arm"), now), now.Add(time.Second))
	if len(replacement.sent) != 0 {
		t.Fatal("queued arm replayed after reconnect")
	}
	feedUDP(b, packetAt(sender, vector("long-arm"), now.Add(time.Second)), now.Add(time.Second))
	b.downlink(Event{'J', grant(old["requestId"].(string), "control.activated", old["actor"].(string), 7)}, now.Add(time.Second))
	if b.active != nil || len(replacement.sent) != 1 {
		t.Fatal("old-session grant activated replacement")
	}
}
func TestDetachReleasesBeforeForgettingSession(t *testing.T) {
	b, s, now := bridgeSetup()
	activate(t, b, s, now, vector("long-arm"))
	b.detach()
	if b.active != nil || b.session != nil || requestMap(t, s.sent[len(s.sent)-1])["type"] != "control.release_active" {
		t.Fatal("link loss did not release")
	}
	count := len(s.sent)
	b.detach()
	if len(s.sent) != count {
		t.Fatal("double release")
	}
}

func TestQueuedFramesYieldToReleaseAndCannotCrossSessions(t *testing.T) {
	b, s, now := bridgeSetup()
	activate(t, b, s, now, vector("long-arm"))
	one := unfamiliarFrame(0, false)
	packet := bytes.Repeat(one, 5000)
	if err := b.uplink(packetAt(sender, packet, now), now); err != nil {
		t.Fatal(err)
	}
	count := len(s.sent)
	if len(b.frames) != 5000 || len(s.sent) != count {
		t.Fatal("large datagram forwarded synchronously")
	}
	if err := b.forward(now); err != nil {
		t.Fatal(err)
	}
	if len(s.sent) != count+1 || len(b.frames) != 4999 {
		t.Fatal("did not yield between frames")
	}
	b.detach()
	replacement := &recordingSession{}
	b.attach(replacement, now.Add(time.Millisecond))
	if err := b.forward(now.Add(time.Millisecond)); err != nil {
		t.Fatal(err)
	}
	if len(b.frames) != 0 || len(replacement.sent) != 0 {
		t.Fatal("queued traffic crossed session/release boundary")
	}
}
func TestMalformedTrafficCannotKeepSenderAlive(t *testing.T) {
	b, s, now := bridgeSetup()
	feedUDP(b, packetAt(sender, unfamiliarFrame(0, false), now), now)
	feedUDP(b, packetAt(sender, []byte{0xfd}, now.Add(4*time.Second)), now.Add(4*time.Second))
	if !b.lastSeen.Equal(now) {
		t.Fatal("malformed traffic extended source lifetime")
	}
	b.tick(now.Add(5 * time.Second))
	if b.source.IsValid() || len(s.sent) != 0 {
		t.Fatal("observer did not expire cleanly")
	}
}
func TestRejectedActivationAndRenewalNeverForwardControl(t *testing.T) {
	for _, kind := range []string{"actor", "ttl", "renew-error", "activation-error"} {
		t.Run(kind, func(t *testing.T) {
			b, s, now := bridgeSetup()
			if kind == "renew-error" {
				activate(t, b, s, now, vector("long-arm"))
				b.tick(now.Add(2 * time.Second))
				now = now.Add(2 * time.Second)
			} else {
				feedUDP(b, packetAt(sender, vector("long-arm"), now), now)
			}
			req := requestMap(t, s.sent[len(s.sent)-1])
			id := req["requestId"].(string)
			payload := grant(id, "control.activated", "qgroundcontrol:"+sender.String(), 7)
			switch kind {
			case "actor":
				payload = grant(id, "control.activated", "office", 7)
			case "ttl":
				payload = bytes.Replace(payload, []byte(`"leaseTtlMs":5000`), []byte(`"leaseTtlMs":6000`), 1)
			case "renew-error", "activation-error":
				payload = []byte(`{"type":"control.error","requestId":"` + id + `","code":"stale_epoch"}`)
			}
			count := len(s.sent)
			if err := b.downlink(Event{'J', payload}, now); err == nil {
				t.Fatal("rejected lease retained authority")
			}
			if len(s.sent) != count {
				t.Fatal("rejected activation forwarded arm")
			}
			b.detach()
		})
	}
}
