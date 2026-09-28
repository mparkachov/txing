package companion

import (
	"context"
	"errors"
	"net"
	"net/netip"
	"sync"
	"sync/atomic"
	"time"
)

type udpPacket struct {
	source  netip.AddrPort
	payload []byte
	at      time.Time
}

type BridgeLimits struct{ Idle, Renew, Response, Disarm, Send, Tick time.Duration }

func DefaultBridgeLimits() BridgeLimits {
	return BridgeLimits{5 * time.Second, 2 * time.Second, time.Second, time.Second, 250 * time.Millisecond, 50 * time.Millisecond}
}

// UDPBridge's control state is owned solely by the MAVLink supervisor. UDP
// readers supply bounded, timestamped datagrams; a backlog cannot revive control
// after inactivity or replay an arm from before a WebRTC connection opened.
type UDPBridge struct {
	frames         [][]byte
	Limits         BridgeLimits
	stop           chan struct{}
	stopped        chan struct{}
	conns          [2]*net.UDPConn
	packets        chan udpPacket
	listening      atomic.Bool
	writeTelemetry func(netip.AddrPort, []byte) error
	// The following fields are accessed only by the MAVLink supervisor.
	session        Session
	connectedAt    time.Time
	source         netip.AddrPort
	lastSeen       time.Time
	serial         uint64
	pending        *leaseRequest
	active         *bridgeLease
	disarm         *armCommand
	disarmDeadline time.Time
}

// ListenUDPBridge explicitly binds both families; udp6 is IPv6-only, so an
// IPv6-disabled host fails startup instead of advertising a partial listener.
// Port zero is useful for local kernel-socket tests; production uses 14550.
func ListenUDPBridge(port int) (*UDPBridge, error) {
	v4, err := net.ListenUDP("udp4", &net.UDPAddr{IP: net.IPv4zero, Port: port})
	if err != nil {
		return nil, err
	}
	port = v4.LocalAddr().(*net.UDPAddr).Port
	v6, err := net.ListenUDP("udp6", &net.UDPAddr{IP: net.IPv6unspecified, Port: port})
	if err != nil {
		_ = v4.Close()
		return nil, err
	}
	b := &UDPBridge{Limits: DefaultBridgeLimits(), stop: make(chan struct{}), stopped: make(chan struct{}), conns: [2]*net.UDPConn{v4, v6}, packets: make(chan udpPacket, 64)}
	b.writeTelemetry = func(addr netip.AddrPort, frame []byte) error {
		conn := b.conns[1]
		if addr.Addr().Is4() {
			conn = b.conns[0]
		}
		if err := conn.SetWriteDeadline(time.Now().Add(b.Limits.Send)); err != nil {
			return err
		}
		_, err := conn.WriteToUDPAddrPort(frame, addr)
		return err
	}
	b.listening.Store(true)
	return b, nil
}
func (b *UDPBridge) Listening() bool { return b.listening.Load() }
func (b *UDPBridge) Close() {
	b.listening.Store(false)
	for _, conn := range b.conns {
		if conn != nil {
			_ = conn.Close()
		}
	}
}
func (b *UDPBridge) read(ctx context.Context) error {
	var wg sync.WaitGroup
	errs := make(chan error, 2)
	for _, conn := range b.conns {
		wg.Add(1)
		go func(conn *net.UDPConn) {
			defer wg.Done()
			buffer := make([]byte, 65535)
			for {
				n, source, err := conn.ReadFromUDPAddrPort(buffer)
				if err != nil {
					errs <- err
					return
				}
				packet := udpPacket{netip.AddrPortFrom(source.Addr().Unmap(), source.Port()), append([]byte(nil), buffer[:n]...), time.Now()}
				select {
				case b.packets <- packet:
				default:
				} // UDP is lossy; memory is bounded.
			}
		}(conn)
	}
	var err error
	select {
	case <-ctx.Done():
		err = ctx.Err()
	case <-errs:
		err = errors.New("UDP listener failed")
	}
	b.Close()
	wg.Wait()
	return err
}
