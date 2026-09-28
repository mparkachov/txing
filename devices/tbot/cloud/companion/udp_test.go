package companion

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"github.com/mparkachov/txing/devices/tbot/cloud/agentstatus"
	"net"
	"testing"
	"time"
)

func (s *fakeSession) sentEvents() []Event {
	s.mu.Lock()
	defer s.mu.Unlock()
	return append([]Event(nil), s.sent...)
}
func runtimeWithBridge(t *testing.T) (*Runtime, *fakeCloud, *fakeFactory, *UDPBridge) {
	t.Helper()
	r, c, f := setup()
	b, err := ListenUDPBridge(0)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(b.Close)
	r.Bridge = b
	return r, c, f, b
}
func udpClient(t *testing.T, b *UDPBridge, ipv6 bool) *net.UDPConn {
	t.Helper()
	network, ip := "udp4", net.IPv4(127, 0, 0, 1)
	if ipv6 {
		network, ip = "udp6", net.IPv6loopback
	}
	port := b.conns[0].LocalAddr().(*net.UDPAddr).Port
	conn, err := net.DialUDP(network, nil, &net.UDPAddr{IP: ip, Port: port})
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { conn.Close() })
	return conn
}
func writeUDP(t *testing.T, conn *net.UDPConn, data []byte) {
	t.Helper()
	if _, err := conn.Write(data); err != nil {
		t.Fatal(err)
	}
}
func readUDPFrame(t *testing.T, conn *net.UDPConn, want []byte) {
	t.Helper()
	conn.SetReadDeadline(time.Now().Add(time.Second))
	data := make([]byte, 65535)
	n, err := conn.Read(data)
	if err != nil || !bytes.Equal(data[:n], want) {
		t.Fatal("UDP frame mismatch", err)
	}
}
func waitForRequest(t *testing.T, s *fakeSession, kind string) map[string]any {
	t.Helper()
	var result map[string]any
	until(t, func() bool {
		for _, event := range s.sentEvents() {
			var m map[string]any
			if event.Kind == 'J' && json.Unmarshal(event.Payload, &m) == nil && m["type"] == kind {
				result = m
				return true
			}
		}
		return false
	})
	return result
}
func armRuntime(t *testing.T, f *fakeFactory, conn *net.UDPConn) *fakeSession {
	t.Helper()
	s := f.current("mavlink")
	frame := vector("long-arm")
	writeUDP(t, conn, frame)
	req := waitForRequest(t, s, "control.activate")
	if req["takeover"] != false {
		t.Fatal("takeover requested")
	}
	s.emit(Event{'J', grant(req["requestId"].(string), "control.activated", req["actor"].(string), 7)})
	until(t, func() bool {
		for _, e := range s.sentEvents() {
			if e.Kind == 'B' && bytes.Equal(e.Payload, frame) {
				return true
			}
		}
		return false
	})
	return s
}
func TestKernelUDPBothFamiliesAndReadiness(t *testing.T) {
	for _, v6 := range []bool{false, true} {
		t.Run(map[bool]string{false: "ipv4", true: "ipv6"}[v6], func(t *testing.T) {
			r, c, f, b := runtimeWithBridge(t)
			cancel, done := begin(t, r)
			until(t, func() bool { return r.Snapshot().MAVLink == "connected" })
			conn := udpClient(t, b, v6)
			telemetry := unfamiliarFrame(255, true)
			writeUDP(t, conn, unfamiliarFrame(0, false))
			time.Sleep(10 * time.Millisecond)
			f.current("mavlink").emit(Event{'B', telemetry})
			readUDPFrame(t, conn, telemetry)
			if len(f.current("mavlink").sentEvents()) != 0 {
				t.Fatal("observer acquired control")
			}
			until(t, func() bool {
				c.mu.Lock()
				defer c.mu.Unlock()
				for _, report := range c.reports {
					if report.UDPListening && report.MAVLink == "connected" {
						return true
					}
				}
				return false
			})
			s := armRuntime(t, f, conn)
			unknown := unfamiliarFrame(255, true)
			writeUDP(t, conn, unknown)
			until(t, func() bool {
				for _, e := range s.sentEvents() {
					if e.Kind == 'B' && bytes.Equal(e.Payload, unknown) {
						return true
					}
				}
				return false
			})
			c.level(1, false)
			until(t, func() bool { return r.Snapshot().Video == "connected" })
			f.current("video").emit(Event{'E', []byte("video failed")})
			until(t, func() bool { return f.count("video") >= 2 && r.Snapshot().Video == "connected" })
			if f.current("mavlink") != s {
				t.Fatal("video reset controlling MAVLink")
			}
			cancel()
			select {
			case <-done:
			case <-time.After(time.Second):
				t.Fatal("unbounded shutdown")
			}
			events := s.sentEvents()
			if requestMap(t, events[len(events)-1])["type"] != "control.release_active" {
				t.Fatal("shutdown did not release")
			}
			s.mu.Lock()
			closedErr := s.closedContextError
			s.mu.Unlock()
			if closedErr != nil {
				t.Fatal("worker context canceled before lease release/close")
			}
			if b.Listening() {
				t.Fatal("socket survived shutdown")
			}
			c.mu.Lock()
			last := c.reports[len(c.reports)-1]
			c.mu.Unlock()
			if last.UDPListening || last.MAVLink == "connected" {
				t.Fatal("shutdown readiness retained endpoint")
			}
		})
	}
}
func TestRuntimeEveryLossPathReleasesControl(t *testing.T) {
	for _, kind := range []string{"webrtc", "worker-exit", "redcon3", "redcon4", "death", "fenced", "unverified", "udp-listener"} {
		t.Run(kind, func(t *testing.T) {
			r, c, f, b := runtimeWithBridge(t)
			_, done := begin(t, r)
			until(t, func() bool { return r.Snapshot().MAVLink == "connected" })
			conn := udpClient(t, b, false)
			s := armRuntime(t, f, conn)
			switch kind {
			case "webrtc":
				s.emit(Event{'S', []byte("disconnected")})
			case "worker-exit":
				s.Close()
			case "redcon3":
				c.level(3, false)
			case "redcon4":
				c.level(4, false)
			case "death":
				c.level(2, true)
			case "fenced":
				c.store.mu.Lock()
				c.store.state = agentstatus.Stopped()
				c.store.version++
				c.store.mu.Unlock()
			case "unverified":
				c.mu.Lock()
				c.err = errors.New("authority unavailable")
				c.mu.Unlock()
			case "udp-listener":
				b.Close()
			}
			req := waitForRequest(t, s, "control.release_active")
			if req["epoch"] != float64(7) {
				t.Fatal("wrong release epoch")
			}
			if kind == "webrtc" || kind == "worker-exit" {
				until(t, func() bool { return f.count("mavlink") >= 2 && r.Snapshot().MAVLink == "connected" })
				replacement := f.current("mavlink")
				writeUDP(t, conn, unfamiliarFrame(0, false))
				time.Sleep(10 * time.Millisecond)
				if len(replacement.sentEvents()) != 0 {
					t.Fatal("new WebRTC session retained control")
				}
			} else {
				select {
				case <-done:
				case <-time.After(time.Second):
					t.Fatal("loss did not shut down")
				}
			}
		})
	}
}
func TestUDPListenerFailureAndBindConflict(t *testing.T) {
	b, err := ListenUDPBridge(0)
	if err != nil {
		t.Fatal(err)
	}
	defer b.Close()
	port := b.conns[0].LocalAddr().(*net.UDPAddr).Port
	if other, err := ListenUDPBridge(port); err == nil {
		other.Close()
		t.Fatal("duplicate listener bound")
	}
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() { done <- b.read(ctx) }()
	cancel()
	select {
	case err := <-done:
		if !errors.Is(err, context.Canceled) {
			t.Fatal(err)
		}
	case <-time.After(time.Second):
		t.Fatal("reader stuck")
	}
	if b.Listening() {
		t.Fatal("reader did not clear readiness")
	}
}

func TestIPv6BindFailureClosesIPv4Listener(t *testing.T) {
	occupied, err := net.ListenUDP("udp6", &net.UDPAddr{IP: net.IPv6unspecified})
	if err != nil {
		t.Fatal(err)
	}
	defer occupied.Close()
	port := occupied.LocalAddr().(*net.UDPAddr).Port
	if bridge, err := ListenUDPBridge(port); err == nil {
		bridge.Close()
		t.Fatal("advertised readiness without IPv6")
	}
	v4, err := net.ListenUDP("udp4", &net.UDPAddr{IP: net.IPv4zero, Port: port})
	if err != nil {
		t.Fatal("failed startup leaked IPv4 socket", err)
	}
	v4.Close()
}
