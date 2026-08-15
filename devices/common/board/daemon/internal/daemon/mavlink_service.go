package daemon

import (
	"context"
	"encoding/binary"
	"errors"
	"flag"
	"fmt"
	"io"
	"math"
	"net"
	"net/url"
	"os"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	mavlinkv1 "github.com/mparkachov/txing/devices/common/board/daemon/internal/proto/mavlinkv1"
	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
)

const (
	DefaultMAVLinkFCEndpoint      = "udp://127.0.0.1:14550"
	DefaultMAVLinkHeartbeatWindow = 3 * time.Second
	mavlinkServiceReadInterval    = 200 * time.Millisecond
	mavlinkServiceReconnectDelay  = time.Second
	mavlinkServicePeerBuffer      = 64
	mavlinkGCSHeartbeatInterval   = time.Second
)

type MAVLinkServiceConfig struct {
	SocketPath      string
	FCEndpoint      string
	HeartbeatWindow time.Duration
}

// MAVLinkTransport deliberately contains only the byte-stream operations the
// broker needs. v1 supplies UDP for the loopback ArduPilot endpoint; a future
// serial transport can implement this boundary without changing the daemon,
// KVS bridge, or public local gRPC API.
type MAVLinkTransport interface {
	Read([]byte) (int, error)
	Write([]byte) (int, error)
	SetReadDeadline(time.Time) error
	Close() error
}

type MAVLinkTransportFactory func(endpoint string) (MAVLinkTransport, error)

func ParseMAVLinkServiceConfig(args []string, environment map[string]string) (MAVLinkServiceConfig, bool, error) {
	flags := flag.NewFlagSet("txing-board-mavlink", flag.ContinueOnError)
	flags.SetOutput(io.Discard)
	var socketPath, endpoint string
	var heartbeatMS uint64
	var showVersion bool
	flags.StringVar(&socketPath, "socket-path", "", "")
	flags.StringVar(&endpoint, "fc-endpoint", "", "")
	flags.Uint64Var(&heartbeatMS, "heartbeat-window-ms", 0, "")
	flags.BoolVar(&showVersion, "version", false, "")
	if err := flags.Parse(args); err != nil {
		return MAVLinkServiceConfig{}, false, err
	}
	if flags.NArg() != 0 {
		return MAVLinkServiceConfig{}, false, errors.New("unexpected positional arguments")
	}
	if showVersion {
		return MAVLinkServiceConfig{}, true, nil
	}
	if socketPath == "" {
		socketPath = strings.TrimSpace(environment["TXING_MAVLINK_SERVICE_SOCKET_PATH"])
	}
	if socketPath == "" {
		socketPath = DefaultMavlinkServiceSocket
	}
	if endpoint == "" {
		endpoint = strings.TrimSpace(environment["TXING_MAVLINK_FC_ENDPOINT"])
	}
	if endpoint == "" {
		endpoint = DefaultMAVLinkFCEndpoint
	}
	if heartbeatMS == 0 {
		if value := strings.TrimSpace(environment["TXING_MAVLINK_HEARTBEAT_WINDOW_MS"]); value != "" {
			parsed, err := strconv.ParseUint(value, 10, 64)
			if err != nil {
				return MAVLinkServiceConfig{}, false, errors.New("TXING_MAVLINK_HEARTBEAT_WINDOW_MS must be an unsigned integer")
			}
			heartbeatMS = parsed
		}
	}
	if heartbeatMS == 0 {
		heartbeatMS = uint64(DefaultMAVLinkHeartbeatWindow / time.Millisecond)
	}
	if heartbeatMS < 500 {
		return MAVLinkServiceConfig{}, false, errors.New("MAVLink heartbeat window must be at least 500 ms")
	}
	if strings.TrimSpace(socketPath) == "" {
		return MAVLinkServiceConfig{}, false, errors.New("MAVLink socket path must not be empty")
	}
	if _, err := parseMAVLinkUDPEndpoint(endpoint); err != nil {
		return MAVLinkServiceConfig{}, false, err
	}
	return MAVLinkServiceConfig{SocketPath: socketPath, FCEndpoint: endpoint, HeartbeatWindow: time.Duration(heartbeatMS) * time.Millisecond}, false, nil
}

func ProcessEnvironment() map[string]string {
	values := make(map[string]string)
	for _, item := range os.Environ() {
		name, value, ok := strings.Cut(item, "=")
		if ok {
			values[name] = value
		}
	}
	return values
}

func RunMAVLinkService(ctx context.Context, config MAVLinkServiceConfig) error {
	service := NewMAVLinkService(config)
	listener, err := bindUnixListener(config.SocketPath)
	if err != nil {
		return err
	}
	defer os.Remove(config.SocketPath)
	server := grpc.NewServer()
	mavlinkv1.RegisterBoardMavlinkServer(server, service)
	serveDone := make(chan error, 1)
	go func() { serveDone <- server.Serve(listener) }()
	service.Start(ctx)
	defer service.Stop()
	select {
	case <-ctx.Done():
		// The daemon keeps Exchange open for the lifetime of its local transport.
		// Stop it explicitly so a service shutdown cannot wait on that stream.
		server.Stop()
		<-serveDone
		return ctx.Err()
	case err := <-serveDone:
		return err
	}
}

// MAVLinkService owns exactly one local flight-controller UDP transport and
// exposes complete MAVLink frames to the daemon through BoardMavlink. It has
// no cloud-peer or control-lease knowledge.
type MAVLinkService struct {
	mavlinkv1.UnimplementedBoardMavlinkServer
	config       MAVLinkServiceConfig
	mu           sync.RWMutex
	status       MAVLinkRuntimeStatus
	lastBeat     time.Time
	transport    MAVLinkTransport
	newTransport MAVLinkTransportFactory
	peers        map[uint64]*mavlinkServicePeer
	nextPeerID   uint64
	sequence     atomic.Uint32
	cancel       context.CancelFunc
	done         chan struct{}
	stopOnce     sync.Once
}

type mavlinkServicePeer struct {
	outbound chan []byte
}

func NewMAVLinkService(config MAVLinkServiceConfig) *MAVLinkService {
	return &MAVLinkService{
		config:       config,
		status:       MAVLinkRuntimeStatus{LinkState: "starting"},
		peers:        make(map[uint64]*mavlinkServicePeer),
		done:         make(chan struct{}),
		newTransport: openMAVLinkUDPTransport,
	}
}

func (s *MAVLinkService) Start(parent context.Context) {
	ctx, cancel := context.WithCancel(parent)
	s.cancel = cancel
	go s.run(ctx)
}

func (s *MAVLinkService) Stop() {
	s.stopOnce.Do(func() {
		if s.cancel != nil {
			s.cancel()
		}
		<-s.done
	})
}

func (s *MAVLinkService) GetStatus(_ context.Context, _ *mavlinkv1.GetStatusRequest) (*mavlinkv1.MavlinkStatus, error) {
	s.mu.Lock()
	s.refreshHeartbeatLocked(time.Now())
	value := s.status
	s.mu.Unlock()
	return mavlinkStatusToProto(value), nil
}

func (s *MAVLinkService) Exchange(stream grpc.BidiStreamingServer[mavlinkv1.MavlinkFrame, mavlinkv1.MavlinkFrame]) error {
	peerID, peer := s.addPeer()
	defer s.removePeer(peerID)
	receiveDone := make(chan error, 1)
	go func() {
		for {
			message, err := stream.Recv()
			if err != nil {
				select {
				case receiveDone <- err:
				case <-stream.Context().Done():
				}
				return
			}
			if err := validateMAVLinkServiceFrame(message.GetFrame()); err != nil {
				select {
				case receiveDone <- status.Error(codes.InvalidArgument, err.Error()):
				case <-stream.Context().Done():
				}
				return
			}
			if err := s.sendFrame(message.GetFrame()); err != nil {
				select {
				case receiveDone <- status.Error(codes.Unavailable, err.Error()):
				case <-stream.Context().Done():
				}
				return
			}
		}
	}()
	for {
		select {
		case frame := <-peer.outbound:
			if err := stream.Send(&mavlinkv1.MavlinkFrame{Frame: frame}); err != nil {
				return err
			}
		case err := <-receiveDone:
			if errors.Is(err, io.EOF) {
				return nil
			}
			return err
		case <-stream.Context().Done():
			return stream.Context().Err()
		}
	}
}

func (s *MAVLinkService) EnterSafeState(_ context.Context, request *mavlinkv1.EnterSafeStateRequest) (*mavlinkv1.EnterSafeStateResponse, error) {
	s.mu.RLock()
	target := s.status.Target
	s.mu.RUnlock()
	response := &mavlinkv1.EnterSafeStateResponse{}
	if target == nil {
		response.Errors = []*mavlinkv1.MavlinkError{{Code: "target_unavailable", Message: "flight-controller target is unavailable"}}
		return response, nil
	}
	appendError := func(code string, err error) {
		if err != nil {
			response.Errors = append(response.Errors, &mavlinkv1.MavlinkError{Code: code, Message: err.Error()})
		}
	}
	if err := s.sendFrame(s.buildManualControlFrame(*target, 0, 0)); err == nil {
		response.NeutralRequested = true
	} else {
		appendError("neutral_failed", err)
	}
	if err := s.sendFrame(s.buildModeFrame(*target, mavlinkModeHold)); err == nil {
		response.HoldRequested = true
	} else {
		appendError("hold_failed", err)
	}
	if request.GetRequestDisarm() {
		if err := s.sendFrame(s.buildArmDisarmFrame(*target, false)); err == nil {
			response.DisarmRequested = true
		} else {
			appendError("disarm_failed", err)
		}
		s.mu.RLock()
		response.DisarmConfirmed = !s.status.Armed
		s.mu.RUnlock()
	}
	return response, nil
}

func (s *MAVLinkService) run(ctx context.Context) {
	defer close(s.done)
	for {
		if ctx.Err() != nil {
			s.closeTransport()
			return
		}
		connection, err := s.openTransport()
		if err != nil {
			s.setUnavailable(err)
			if !waitMAVLinkFlightRetry(ctx, mavlinkServiceReconnectDelay) {
				return
			}
			continue
		}
		s.mu.Lock()
		s.transport = connection
		s.status.LinkState = "starting"
		s.status.Errors = nil
		s.mu.Unlock()
		err = s.readTransport(ctx, connection)
		s.mu.Lock()
		if s.transport == connection {
			s.transport = nil
		}
		s.mu.Unlock()
		_ = connection.Close()
		if err != nil && ctx.Err() == nil {
			s.setUnavailable(err)
		}
	}
}

func openMAVLinkUDPTransport(value string) (MAVLinkTransport, error) {
	endpoint, err := parseMAVLinkUDPEndpoint(value)
	if err != nil {
		return nil, err
	}
	connection, err := net.DialUDP("udp", nil, endpoint)
	if err != nil {
		return nil, fmt.Errorf("connect MAVLink UDP endpoint: %w", err)
	}
	return connection, nil
}

func (s *MAVLinkService) openTransport() (MAVLinkTransport, error) {
	if s.newTransport == nil {
		return nil, errors.New("MAVLink transport factory is unavailable")
	}
	return s.newTransport(s.config.FCEndpoint)
}

func (s *MAVLinkService) readTransport(ctx context.Context, connection MAVLinkTransport) error {
	buffer := make([]byte, 4096)
	lastGCSHeartbeat := time.Time{}
	for {
		if ctx.Err() != nil {
			return ctx.Err()
		}
		_ = connection.SetReadDeadline(time.Now().Add(mavlinkServiceReadInterval))
		count, err := connection.Read(buffer)
		if err != nil {
			if errors.Is(err, net.ErrClosed) {
				return err
			}
			if timeout, ok := err.(net.Error); ok && timeout.Timeout() {
				now := time.Now()
				if lastGCSHeartbeat.IsZero() || now.Sub(lastGCSHeartbeat) >= mavlinkGCSHeartbeatInterval {
					if heartbeatErr := s.sendFrame(s.buildHeartbeatFrame()); heartbeatErr != nil {
						return heartbeatErr
					}
					lastGCSHeartbeat = now
				}
				s.mu.Lock()
				s.refreshHeartbeatLocked(now)
				s.mu.Unlock()
				continue
			}
			return fmt.Errorf("read MAVLink UDP frame: %w", err)
		}
		for _, frame := range splitMAVLinkV2Datagram(buffer[:count]) {
			s.observeFrame(frame)
			s.broadcast(frame)
		}
	}
}

func (s *MAVLinkService) observeFrame(frame []byte) {
	if len(frame) < 12 || frame[0] != mavlinkV2Magic {
		return
	}
	messageID := uint32(frame[7]) | uint32(frame[8])<<8 | uint32(frame[9])<<16
	if messageID != mavlinkHeartbeatMessageID || int(frame[1]) < 9 {
		return
	}
	payload := frame[10 : 10+int(frame[1])]
	mode := mavlinkModeName(binary.LittleEndian.Uint32(payload[:4]))
	armed := payload[6]&0x80 != 0
	s.mu.Lock()
	s.lastBeat = time.Now()
	s.status.LinkState = "ready"
	s.status.HeartbeatFresh = true
	s.status.Target = &MAVLinkTarget{SystemID: uint32(frame[5]), ComponentID: uint32(frame[6])}
	s.status.Armed = armed
	s.status.Mode = &mode
	s.status.Errors = nil
	s.mu.Unlock()
}

func (s *MAVLinkService) refreshHeartbeatLocked(now time.Time) {
	if s.lastBeat.IsZero() {
		s.status.HeartbeatFresh = false
		return
	}
	if now.Sub(s.lastBeat) > s.config.HeartbeatWindow {
		s.status.HeartbeatFresh = false
		if s.status.LinkState == "ready" {
			s.status.LinkState = "degraded"
		}
	}
}

func (s *MAVLinkService) setUnavailable(err error) {
	s.mu.Lock()
	s.status = MAVLinkUnavailableStatus(err.Error())
	s.mu.Unlock()
}

func (s *MAVLinkService) closeTransport() {
	s.mu.Lock()
	connection := s.transport
	s.transport = nil
	s.mu.Unlock()
	if connection != nil {
		_ = connection.Close()
	}
}

func (s *MAVLinkService) sendFrame(frame []byte) error {
	s.mu.RLock()
	connection := s.transport
	s.mu.RUnlock()
	if connection == nil {
		return errors.New("MAVLink UDP transport is unavailable")
	}
	if _, err := connection.Write(frame); err != nil {
		return fmt.Errorf("write MAVLink UDP frame: %w", err)
	}
	return nil
}

func (s *MAVLinkService) addPeer() (uint64, *mavlinkServicePeer) {
	peer := &mavlinkServicePeer{outbound: make(chan []byte, mavlinkServicePeerBuffer)}
	s.mu.Lock()
	s.nextPeerID++
	id := s.nextPeerID
	s.peers[id] = peer
	s.mu.Unlock()
	return id, peer
}

func (s *MAVLinkService) removePeer(id uint64) {
	s.mu.Lock()
	delete(s.peers, id)
	s.mu.Unlock()
}

func (s *MAVLinkService) broadcast(frame []byte) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	for _, peer := range s.peers {
		copy := append([]byte(nil), frame...)
		select {
		case peer.outbound <- copy:
		default:
			// Slow consumers never delay the UDP reader or another observer.
		}
	}
}

func (s *MAVLinkService) buildManualControlFrame(target MAVLinkTarget, steering, throttle int16) []byte {
	payload := make([]byte, 11)
	binary.LittleEndian.PutUint16(payload[0:2], uint16(int16(math.MaxInt16)))
	binary.LittleEndian.PutUint16(payload[2:4], uint16(steering))
	binary.LittleEndian.PutUint16(payload[4:6], uint16(throttle))
	binary.LittleEndian.PutUint16(payload[6:8], uint16(int16(math.MaxInt16)))
	payload[10] = byte(target.SystemID)
	return s.buildFrame(mavlinkManualControlMessageID, payload)
}

func (s *MAVLinkService) buildHeartbeatFrame() []byte {
	payload := make([]byte, 9)
	payload[4] = 6 // MAV_TYPE_GCS
	payload[5] = 8 // MAV_AUTOPILOT_INVALID
	payload[7] = 4 // MAV_STATE_ACTIVE
	payload[8] = 3 // MAVLink version 2.0
	return s.buildFrame(mavlinkHeartbeatMessageID, payload)
}

func (s *MAVLinkService) buildModeFrame(target MAVLinkTarget, mode uint32) []byte {
	payload := make([]byte, 33)
	binary.LittleEndian.PutUint32(payload[0:4], math.Float32bits(float32(mavlinkCustomModeEnabledBaseMode)))
	binary.LittleEndian.PutUint32(payload[4:8], math.Float32bits(float32(mode)))
	binary.LittleEndian.PutUint16(payload[28:30], mavlinkCommandDoSetMode)
	payload[30] = byte(target.SystemID)
	payload[31] = byte(target.ComponentID)
	return s.buildFrame(mavlinkCommandLongMessageID, payload)
}

func (s *MAVLinkService) buildArmDisarmFrame(target MAVLinkTarget, arm bool) []byte {
	payload := make([]byte, 33)
	if arm {
		binary.LittleEndian.PutUint32(payload[0:4], math.Float32bits(1))
	}
	binary.LittleEndian.PutUint16(payload[28:30], mavlinkCommandComponentArmDisarm)
	payload[30] = byte(target.SystemID)
	payload[31] = byte(target.ComponentID)
	return s.buildFrame(mavlinkCommandLongMessageID, payload)
}

func (s *MAVLinkService) buildFrame(messageID uint32, payload []byte) []byte {
	sequence := byte(s.sequence.Add(1))
	extra, _ := mavlinkCRCExtra(messageID)
	frame := make([]byte, len(payload)+12)
	frame[0] = mavlinkV2Magic
	frame[1] = byte(len(payload))
	frame[4] = sequence
	frame[5] = defaultMAVLinkGCSSystemID
	frame[6] = defaultMAVLinkGCSComponentID
	frame[7] = byte(messageID)
	frame[8] = byte(messageID >> 8)
	frame[9] = byte(messageID >> 16)
	copy(frame[10:], payload)
	checksum := mavlinkChecksum(frame[1:10+len(payload)], extra)
	frame[10+len(payload)] = byte(checksum)
	frame[11+len(payload)] = byte(checksum >> 8)
	return frame
}

func parseMAVLinkUDPEndpoint(value string) (*net.UDPAddr, error) {
	parsed, err := url.Parse(value)
	if err != nil || parsed.Scheme != "udp" || parsed.Host == "" || parsed.Path != "" || parsed.RawQuery != "" || parsed.Fragment != "" {
		return nil, errors.New("MAVLink flight-controller endpoint must be udp://127.0.0.1:14550")
	}
	host, portText, err := net.SplitHostPort(parsed.Host)
	if err != nil || host != "127.0.0.1" || portText != "14550" {
		return nil, errors.New("MAVLink flight-controller endpoint must be udp://127.0.0.1:14550")
	}
	return net.ResolveUDPAddr("udp", parsed.Host)
}

func validateMAVLinkServiceFrame(frame []byte) error {
	if len(frame) < 12 || frame[0] != mavlinkV2Magic || frame[2]&mavlinkV2SignedIncompatibilityFlag != 0 {
		return errors.New("MAVLink service accepts complete unsigned MAVLink 2 frames only")
	}
	if len(frame) != int(frame[1])+12 {
		return errors.New("MAVLink service frame length is invalid")
	}
	return nil
}

func splitMAVLinkV2Datagram(datagram []byte) [][]byte {
	frames := make([][]byte, 0, 1)
	for len(datagram) >= 12 {
		if datagram[0] != mavlinkV2Magic || datagram[2]&mavlinkV2SignedIncompatibilityFlag != 0 {
			return frames
		}
		length := int(datagram[1]) + 12
		if len(datagram) < length {
			return frames
		}
		frames = append(frames, append([]byte(nil), datagram[:length]...))
		datagram = datagram[length:]
	}
	return frames
}

func mavlinkModeName(mode uint32) string {
	switch mode {
	case mavlinkModeManual:
		return "manual"
	case mavlinkModeHold:
		return "hold"
	default:
		return fmt.Sprintf("custom-%d", mode)
	}
}

func mavlinkStatusToProto(value MAVLinkRuntimeStatus) *mavlinkv1.MavlinkStatus {
	result := &mavlinkv1.MavlinkStatus{
		LinkState:                  mavlinkLinkStateProto(value.LinkState),
		HeartbeatFresh:             value.HeartbeatFresh,
		Armed:                      value.Armed,
		MavlinkWireProtocolVersion: MAVLinkWireProtocolVersion,
		Errors:                     make([]*mavlinkv1.MavlinkError, 0, len(value.Errors)),
	}
	if value.Target != nil {
		result.Target = &mavlinkv1.MavlinkTarget{SystemId: value.Target.SystemID, ComponentId: value.Target.ComponentID}
	}
	if value.Mode != nil {
		result.Mode = *value.Mode
	}
	for _, item := range value.Errors {
		result.Errors = append(result.Errors, &mavlinkv1.MavlinkError{Code: item.Code, Message: item.Message})
	}
	return result
}

func mavlinkLinkStateProto(value string) mavlinkv1.LinkState {
	switch value {
	case "starting":
		return mavlinkv1.LinkState_LINK_STATE_STARTING
	case "ready":
		return mavlinkv1.LinkState_LINK_STATE_READY
	case "degraded":
		return mavlinkv1.LinkState_LINK_STATE_DEGRADED
	default:
		return mavlinkv1.LinkState_LINK_STATE_UNAVAILABLE
	}
}
