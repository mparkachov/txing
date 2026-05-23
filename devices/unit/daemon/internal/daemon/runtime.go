package daemon

import (
	"bytes"
	"context"
	"crypto/tls"
	"crypto/x509"
	"encoding/binary"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/service/cloudwatchlogs"
	cwtypes "github.com/aws/aws-sdk-go-v2/service/cloudwatchlogs/types"
	"github.com/aws/aws-sdk-go-v2/service/iotdataplane"
	"github.com/aws/smithy-go"
	boardvideov1 "github.com/mparkachov/txing/devices/unit/daemon/internal/proto/boardvideov1"
	hardwarev1 "github.com/mparkachov/txing/devices/unit/daemon/internal/proto/hardwarev1"
	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/grpc/status"
	"google.golang.org/protobuf/types/known/timestamppb"
)

const (
	DefaultMCPResponseTimeoutMillis          = uint32(7000)
	videoStatusHeartbeatSeconds              = 5
	cloudWatchLogBatchMaxEvents              = 100
	cloudWatchLogBatchMaxBytes               = 256 * 1024
	cloudWatchLogEventOverheadBytes          = 26
	cloudWatchLogFlushInterval               = 2 * time.Second
	cloudWatchLogShutdownTimeout             = 5 * time.Second
	videoCredentialRestartMargin             = 300 * time.Second
	videoCredentialRestartMinDelay           = 30 * time.Second
	boardVideoBridgeProtocolVersion          = "1"
	defaultBoardVideoWorkerTransport         = "webrtc-datachannel"
	defaultMCPBridgeSessionClosedReason      = "MCP bridge session closed"
	defaultMCPWebRTCDataChannelClosedReason  = "MCP WebRTC data channel closed"
	defaultMCPWebRTCDataChannelErrorDetail   = "MCP WebRTC data channel error"
	defaultBoardVideoWorkerErrorDetail       = "board video worker reported an error"
	defaultNativeKVSWorkerErrorDetail        = "native KVS worker reported an error"
	defaultHardwareWorkerCommandStopReason   = "daemon-policy"
	defaultHardwareWorkerCommandIDPrefix     = "cmd_vel-"
	defaultCloudWatchLogsProviderUnavailable = "CloudWatch Logs client is not configured"
	mqttKeepAliveSeconds                     = 60
	mqttPublishQoS                           = 1
)

type PublishedMessage struct {
	Topic   string
	Payload []byte
	Retain  bool
}

type Publisher interface {
	Publish(context.Context, PublishedMessage) error
}

type RuntimeMqttEvent struct {
	Topic        string
	Payload      []byte
	Disconnected bool
}

type MQTTPublisher struct {
	conn     net.Conn
	incoming chan RuntimeMqttEvent
	done     chan struct{}
	stopping atomic.Bool
	packetID atomic.Uint32
	writeMu  sync.Mutex
}

func ConnectMQTT(ctx context.Context, runtimeConfig RuntimeConfig) (*MQTTPublisher, <-chan RuntimeMqttEvent, error) {
	cert, err := tls.LoadX509KeyPair(runtimeConfig.IoTCertFile, runtimeConfig.IoTPrivateKeyFile)
	if err != nil {
		return nil, nil, fmt.Errorf("load MQTT client identity: %w", err)
	}
	rootPEM, err := os.ReadFile(runtimeConfig.IoTRootCAFile)
	if err != nil {
		return nil, nil, fmt.Errorf("read MQTT root CA %s: %w", runtimeConfig.IoTRootCAFile, err)
	}
	roots := x509.NewCertPool()
	if !roots.AppendCertsFromPEM(rootPEM) {
		return nil, nil, errors.New("load MQTT root CA")
	}
	dialer := &net.Dialer{}
	conn, err := tls.DialWithDialer(dialer, "tcp", fmt.Sprintf("%s:%d", runtimeConfig.IoTEndpoint, MQTTPort), &tls.Config{
		ServerName:   runtimeConfig.IoTEndpoint,
		Certificates: []tls.Certificate{cert},
		RootCAs:      roots,
		MinVersion:   tls.VersionTLS12,
	})
	if err != nil {
		return nil, nil, fmt.Errorf("connect MQTT mTLS: %w", err)
	}
	publisher := &MQTTPublisher{conn: conn, incoming: make(chan RuntimeMqttEvent, 32), done: make(chan struct{})}
	if err := publisher.writePacket(ctx, mqttPacketConnect(runtimeConfig.ClientID)); err != nil {
		_ = conn.Close()
		return nil, nil, err
	}
	packetType, _, payload, err := readMQTTPacket(conn)
	if err != nil {
		_ = conn.Close()
		return nil, nil, fmt.Errorf("read MQTT CONNACK: %w", err)
	}
	if packetType != 2 || len(payload) < 2 || payload[1] != 0 {
		_ = conn.Close()
		return nil, nil, fmt.Errorf("MQTT connection failed: connack=%x", payload)
	}
	go publisher.readLoop()
	go publisher.pingLoop()
	return publisher, publisher.incoming, nil
}

func (p *MQTTPublisher) Subscribe(ctx context.Context, topicFilter string) error {
	packetID := p.nextPacketID()
	return p.writePacket(ctx, mqttPacketSubscribe(packetID, topicFilter))
}

func (p *MQTTPublisher) Publish(ctx context.Context, message PublishedMessage) error {
	packetID := p.nextPacketID()
	return p.writePacket(ctx, mqttPacketPublish(packetID, message.Topic, message.Payload, message.Retain))
}

func (p *MQTTPublisher) Stop() error {
	p.stopping.Store(true)
	_ = p.writePacket(context.Background(), []byte{0xe0, 0x00})
	err := p.conn.Close()
	<-p.done
	return err
}

func (p *MQTTPublisher) nextPacketID() uint16 {
	next := uint16(p.packetID.Add(1) & 0xffff)
	if next == 0 {
		next = uint16(p.packetID.Add(1) & 0xffff)
	}
	return next
}

func (p *MQTTPublisher) writePacket(ctx context.Context, packet []byte) error {
	p.writeMu.Lock()
	defer p.writeMu.Unlock()
	if deadline, ok := ctx.Deadline(); ok {
		_ = p.conn.SetWriteDeadline(deadline)
		defer p.conn.SetWriteDeadline(time.Time{})
	}
	_, err := p.conn.Write(packet)
	return err
}

func (p *MQTTPublisher) readLoop() {
	defer close(p.done)
	for {
		packetType, flags, payload, err := readMQTTPacket(p.conn)
		if err != nil {
			if !p.stopping.Load() {
				p.incoming <- RuntimeMqttEvent{Disconnected: true}
			}
			close(p.incoming)
			return
		}
		if packetType == 3 {
			topic, packetID, body, qos, ok := parseMQTTPublish(flags, payload)
			if ok {
				if qos == 1 {
					_ = p.writePacket(context.Background(), mqttPacketPubAck(packetID))
				}
				p.incoming <- RuntimeMqttEvent{Topic: topic, Payload: body}
			}
		}
	}
}

func (p *MQTTPublisher) pingLoop() {
	ticker := time.NewTicker(time.Duration(mqttKeepAliveSeconds/2) * time.Second)
	defer ticker.Stop()
	for {
		select {
		case <-ticker.C:
			if p.stopping.Load() {
				return
			}
			_ = p.writePacket(context.Background(), []byte{0xc0, 0x00})
		case <-p.done:
			return
		}
	}
}

type RuntimeMcpOpenEvent struct {
	SessionID string
	Transport string
	PeerID    string
}

type RuntimeMcpRequestEvent struct {
	SessionID string
	Payload   string
	Response  chan *string
}

type RuntimeMcpCloseEvent struct {
	SessionID string
	Reason    string
}

type CapabilityManager struct {
	capabilities []string
	seq          uint64
}

func NewCapabilityManager(capabilityNames []string) (*CapabilityManager, error) {
	seen := make(map[string]struct{}, len(capabilityNames))
	for _, capability := range capabilityNames {
		if err := validateCapabilityNamePublic(capability); err != nil {
			return nil, err
		}
		seen[capability] = struct{}{}
	}
	if len(seen) == 0 {
		return nil, errors.New("at least one capability is required")
	}
	capabilities := make([]string, 0, len(seen))
	for capability := range seen {
		capabilities = append(capabilities, capability)
	}
	sort.Strings(capabilities)
	return &CapabilityManager{capabilities: capabilities}, nil
}

func (m *CapabilityManager) PublishState(ctx context.Context, publisher Publisher, thingName string, availability map[string]bool, ttl time.Duration, observedAtMS uint64) error {
	m.seq++
	topic, err := BuildCapabilityStateTopic(thingName)
	if err != nil {
		return err
	}
	payload := BuildCapabilityStatePayload(thingName, m.capabilities, availability, durationMillis(ttl), observedAtMS, m.seq)
	encoded, err := json.Marshal(payload)
	if err != nil {
		return err
	}
	return publisher.Publish(ctx, PublishedMessage{Topic: topic, Payload: encoded, Retain: true})
}

func (m *CapabilityManager) Seq() uint64 {
	return m.seq
}

type Vector3 struct {
	X float64 `json:"x"`
	Y float64 `json:"y"`
	Z float64 `json:"z"`
}

type Twist struct {
	Linear  Vector3 `json:"linear"`
	Angular Vector3 `json:"angular"`
}

type DriveState struct {
	LeftSpeed  int32  `json:"leftSpeed"`
	RightSpeed int32  `json:"rightSpeed"`
	Sequence   uint64 `json:"sequence"`
}

type HardwareStatusSnapshot struct {
	ActuatorReady bool
	Motion        DriveState
}

type HardwareClient interface {
	GetStatus(context.Context) (HardwareStatusSnapshot, error)
	ApplyVelocity(context.Context, Twist, uint64) (DriveState, error)
	Stop(context.Context) (DriveState, error)
}

type GRPCHardwareClient struct {
	socketPath string
	timeout    time.Duration
	mu         sync.Mutex
	conn       *grpc.ClientConn
	client     hardwarev1.UnitHardwareClient
}

func NewGRPCHardwareClient(socketPath string, timeout time.Duration) *GRPCHardwareClient {
	return &GRPCHardwareClient{socketPath: socketPath, timeout: timeout}
}

func (c *GRPCHardwareClient) ensureClient(ctx context.Context) (hardwarev1.UnitHardwareClient, error) {
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.client != nil {
		return c.client, nil
	}
	dialCtx, cancel := context.WithTimeout(ctx, c.timeout)
	defer cancel()
	conn, err := grpc.DialContext(dialCtx, "unix://"+c.socketPath, grpc.WithTransportCredentials(insecure.NewCredentials()), grpc.WithBlock())
	if err != nil {
		return nil, fmt.Errorf("connect to hardware worker: %w", err)
	}
	c.conn = conn
	c.client = hardwarev1.NewUnitHardwareClient(conn)
	return c.client, nil
}

func (c *GRPCHardwareClient) dropClient() {
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.conn != nil {
		_ = c.conn.Close()
	}
	c.conn = nil
	c.client = nil
}

func (c *GRPCHardwareClient) GetStatus(ctx context.Context) (HardwareStatusSnapshot, error) {
	client, err := c.ensureClient(ctx)
	if err != nil {
		return HardwareStatusSnapshot{}, err
	}
	callCtx, cancel := context.WithTimeout(ctx, c.timeout)
	defer cancel()
	response, err := client.GetStatus(callCtx, &hardwarev1.GetStatusRequest{})
	if err != nil {
		c.dropClient()
		return HardwareStatusSnapshot{}, fmt.Errorf("hardware worker status failed: %w", err)
	}
	return hardwareStatusFromProto(response), nil
}

func (c *GRPCHardwareClient) ApplyVelocity(ctx context.Context, twist Twist, deadlineUnixMS uint64) (DriveState, error) {
	client, err := c.ensureClient(ctx)
	if err != nil {
		return DriveState{}, err
	}
	callCtx, cancel := context.WithTimeout(ctx, c.timeout)
	defer cancel()
	response, err := client.ApplyVelocity(callCtx, &hardwarev1.ApplyVelocityRequest{
		Twist:          twistToProto(twist),
		DeadlineUnixMs: deadlineUnixMS,
		CommandId:      fmt.Sprintf("%s%d", defaultHardwareWorkerCommandIDPrefix, deadlineUnixMS),
	})
	if err != nil {
		c.dropClient()
		return DriveState{}, fmt.Errorf("hardware worker apply velocity failed: %w", err)
	}
	return motionFromProto(response.GetMotion()), nil
}

func (c *GRPCHardwareClient) Stop(ctx context.Context) (DriveState, error) {
	client, err := c.ensureClient(ctx)
	if err != nil {
		return DriveState{}, err
	}
	callCtx, cancel := context.WithTimeout(ctx, c.timeout)
	defer cancel()
	response, err := client.Stop(callCtx, &hardwarev1.StopRequest{Reason: defaultHardwareWorkerCommandStopReason})
	if err != nil {
		c.dropClient()
		return DriveState{}, fmt.Errorf("hardware worker stop failed: %w", err)
	}
	return motionFromProto(response.GetMotion()), nil
}

type CmdVelController struct {
	client     HardwareClient
	driveState DriveState
}

func NewCmdVelController(client HardwareClient) *CmdVelController {
	return &CmdVelController{client: client}
}

func NewCmdVelControllerFromConfig(config RuntimeConfig) *CmdVelController {
	return NewCmdVelController(NewGRPCHardwareClient(config.HardwareWorkerSocketPath, config.HardwareWorkerTimeout))
}

func (c *CmdVelController) DriveState() DriveState {
	return c.driveState
}

func (c *CmdVelController) PublishTwist(ctx context.Context, twist Twist, deadlineUnixMS uint64) (DriveState, error) {
	motion, err := c.client.ApplyVelocity(ctx, twist, deadlineUnixMS)
	if err != nil {
		return DriveState{}, err
	}
	c.driveState = motion
	return c.driveState, nil
}

func (c *CmdVelController) Stop(ctx context.Context, _ bool) (DriveState, error) {
	motion, err := c.client.Stop(ctx)
	if err != nil {
		return DriveState{}, err
	}
	c.driveState = motion
	return c.driveState, nil
}

func (c *CmdVelController) RefreshStatus(ctx context.Context) (bool, error) {
	status, err := c.client.GetStatus(ctx)
	if err != nil {
		return false, err
	}
	changed := c.driveState != status.Motion
	c.driveState = status.Motion
	if !status.ActuatorReady {
		return changed, errors.New("hardware worker actuator unavailable")
	}
	return changed, nil
}

type ActiveControlState struct {
	SessionID   string  `json:"sessionId"`
	Actor       *string `json:"actor"`
	Transport   string  `json:"transport"`
	SinceMS     uint64  `json:"sinceMs"`
	ExpiresAtMS uint64  `json:"expiresAtMs"`
	Epoch       uint64  `json:"epoch"`
}

type RobotControlReport struct {
	ActiveRequired       bool                `json:"activeRequired"`
	ActiveTTLMS          uint64              `json:"activeTtlMs"`
	ActiveHeldByCaller   bool                `json:"activeHeldByCaller"`
	ActiveOwnerSessionID *string             `json:"activeOwnerSessionId"`
	ActiveExpiresAtMS    *uint64             `json:"activeExpiresAtMs"`
	ActiveEpoch          *uint64             `json:"activeEpoch"`
	ActiveControl        *ActiveControlState `json:"activeControl"`
}

type RobotVideoReport struct {
	Available       bool    `json:"available"`
	Ready           bool    `json:"ready"`
	Status          string  `json:"status"`
	ViewerConnected bool    `json:"viewerConnected"`
	LastError       *string `json:"lastError"`
}

type RobotStateReport struct {
	Control RobotControlReport `json:"control"`
	Motion  DriveState         `json:"motion"`
	Video   RobotVideoReport   `json:"video"`
}

type VideoRuntimeState struct {
	Available       bool
	Ready           bool
	Status          string
	ViewerConnected bool
	LastError       *string
	UpdatedAtMS     uint64
}

func VideoRuntimeStarting(observedAtMS uint64) VideoRuntimeState {
	return VideoRuntimeState{Available: true, Ready: false, Status: VideoStatusStarting, UpdatedAtMS: observedAtMS}
}

func VideoRuntimeUnavailable(observedAtMS uint64) VideoRuntimeState {
	return VideoRuntimeState{Available: false, Ready: false, Status: VideoStatusUnavailable, UpdatedAtMS: observedAtMS}
}

func (s VideoRuntimeState) RobotReport() RobotVideoReport {
	return RobotVideoReport{
		Available:       s.Available,
		Ready:           s.Ready,
		Status:          s.Status,
		ViewerConnected: s.ViewerConnected,
		LastError:       s.LastError,
	}
}

type VideoWorkerEventKind string

const (
	VideoWorkerStarting             VideoWorkerEventKind = "starting"
	VideoWorkerReady                VideoWorkerEventKind = "ready"
	VideoWorkerViewerConnected      VideoWorkerEventKind = "viewer-connected"
	VideoWorkerMCPDataChannelOpen   VideoWorkerEventKind = "mcp-open"
	VideoWorkerMCPDataChannelClosed VideoWorkerEventKind = "mcp-closed"
	VideoWorkerMCPDataChannelError  VideoWorkerEventKind = "mcp-error"
	VideoWorkerError                VideoWorkerEventKind = "error"
)

type VideoWorkerEvent struct {
	Kind          VideoWorkerEventKind
	WorkerVersion string
	Connected     bool
	SessionID     string
	Reason        string
	Detail        string
}

func (s *VideoRuntimeState) ApplyEvent(event VideoWorkerEvent, observedAtMS uint64) {
	switch event.Kind {
	case VideoWorkerStarting:
		*s = VideoRuntimeStarting(observedAtMS)
	case VideoWorkerReady:
		s.Available = true
		s.Ready = true
		s.Status = VideoStatusReady
		s.LastError = nil
		s.UpdatedAtMS = observedAtMS
	case VideoWorkerViewerConnected:
		s.ViewerConnected = event.Connected
		s.UpdatedAtMS = observedAtMS
	case VideoWorkerError:
		detail := event.Detail
		if strings.TrimSpace(detail) == "" {
			detail = defaultBoardVideoWorkerErrorDetail
		}
		s.Available = true
		s.Ready = false
		s.Status = VideoStatusError
		s.LastError = &detail
		s.UpdatedAtMS = observedAtMS
	default:
		s.UpdatedAtMS = observedAtMS
	}
}

type MCPTransportMode string

const (
	MCPTransportMQTT              MCPTransportMode = "mqtt-jsonrpc"
	MCPTransportWebRTCDataChannel MCPTransportMode = "webrtc-datachannel"
)

type McpServer struct {
	active    *ActiveControlState
	nextEpoch uint64
	activeTTL time.Duration
}

func NewMcpServer(activeTTL time.Duration) *McpServer {
	return &McpServer{activeTTL: activeTTL}
}

func (s *McpServer) Status(nowMS uint64) map[string]interface{} {
	return map[string]interface{}{
		"serviceId":       MCPCapability,
		"available":       true,
		"status":          "ready",
		"protocolVersion": MCPProtocolVersion,
		"observedAtMs":    nowMS,
		"activeControl":   s.active,
	}
}

func (s *McpServer) ClearExpired(nowMS uint64) bool {
	if s.active != nil && s.active.ExpiresAtMS <= nowMS {
		s.active = nil
		return true
	}
	return false
}

func (s *McpServer) Activate(sessionID string, actor *string, transport string, takeover bool, nowMS uint64) (ActiveControlState, bool, error) {
	stopRequired := s.ClearExpired(nowMS)
	if s.active != nil {
		if s.active.SessionID != sessionID {
			if !takeover {
				return ActiveControlState{}, stopRequired, errors.New("active control busy")
			}
			stopRequired = true
		} else {
			return *s.active, stopRequired, nil
		}
	}
	s.nextEpoch++
	active := ActiveControlState{
		SessionID:   sessionID,
		Actor:       actor,
		Transport:   transport,
		SinceMS:     nowMS,
		ExpiresAtMS: nowMS + durationMillis(s.activeTTL),
		Epoch:       s.nextEpoch,
	}
	s.active = &active
	return active, stopRequired, nil
}

func (s *McpServer) ClearActive() bool {
	if s.active == nil {
		return false
	}
	s.active = nil
	return true
}

func (s *McpServer) CloseSession(sessionID string) bool {
	if s.active != nil && s.active.SessionID == sessionID {
		return s.ClearActive()
	}
	return false
}

func (s *McpServer) RenewActive(sessionID string, epoch, nowMS uint64) (ActiveControlState, error) {
	if _, err := s.EnsureActive(sessionID, epoch, nowMS); err != nil {
		return ActiveControlState{}, err
	}
	s.active.ExpiresAtMS = nowMS + durationMillis(s.activeTTL)
	return *s.active, nil
}

func (s *McpServer) ReleaseActive(sessionID string, epoch, nowMS uint64) (bool, error) {
	if _, err := s.EnsureActive(sessionID, epoch, nowMS); err != nil {
		return false, err
	}
	s.active = nil
	return true, nil
}

func (s *McpServer) EnsureActive(sessionID string, epoch, nowMS uint64) (ActiveControlState, error) {
	s.ClearExpired(nowMS)
	if s.active == nil {
		return ActiveControlState{}, errors.New("no active control")
	}
	if s.active.SessionID != sessionID {
		return ActiveControlState{}, errors.New("no active control")
	}
	if s.active.Epoch != epoch {
		return ActiveControlState{}, errors.New("stale active control epoch")
	}
	return *s.active, nil
}

func (s *McpServer) RobotState(callerSessionID string, motion DriveState, video RobotVideoReport) RobotStateReport {
	var owner *string
	var expires *uint64
	var epoch *uint64
	var activeCopy *ActiveControlState
	heldByCaller := false
	if s.active != nil {
		copy := *s.active
		activeCopy = &copy
		owner = &copy.SessionID
		expires = &copy.ExpiresAtMS
		epoch = &copy.Epoch
		heldByCaller = copy.SessionID == callerSessionID
	}
	return RobotStateReport{
		Control: RobotControlReport{
			ActiveRequired:       true,
			ActiveTTLMS:          durationMillis(s.activeTTL),
			ActiveHeldByCaller:   heldByCaller,
			ActiveOwnerSessionID: owner,
			ActiveExpiresAtMS:    expires,
			ActiveEpoch:          epoch,
			ActiveControl:        activeCopy,
		},
		Motion: motion,
		Video:  video,
	}
}

type RuntimeState struct {
	config            RuntimeConfig
	capabilityManager *CapabilityManager
	mcp               *McpServer
	cmdVel            *CmdVelController
	video             VideoRuntimeState
}

func NewRuntimeState(config RuntimeConfig) (*RuntimeState, error) {
	return NewRuntimeStateWithHardware(config, nil)
}

func NewRuntimeStateWithHardware(config RuntimeConfig, hardware HardwareClient) (*RuntimeState, error) {
	manager, err := NewCapabilityManager(config.Capabilities)
	if err != nil {
		return nil, err
	}
	if hardware == nil {
		hardware = NewGRPCHardwareClient(config.HardwareWorkerSocketPath, config.HardwareWorkerTimeout)
	}
	return &RuntimeState{
		config:            config,
		capabilityManager: manager,
		mcp:               NewMcpServer(time.Duration(DefaultMCPActiveTTLMillis) * time.Millisecond),
		cmdVel:            NewCmdVelController(hardware),
		video:             VideoRuntimeStarting(0),
	}, nil
}

func (s *RuntimeState) PublishOnline(ctx context.Context, publisher Publisher, addresses DefaultRouteAddresses, observedAtMS uint64) error {
	if err := s.publishBoardShadow(ctx, publisher, BuildOnlineBoardReport(addresses)); err != nil {
		return err
	}
	if err := s.publishMCPDiscovery(ctx, publisher, observedAtMS); err != nil {
		return err
	}
	if s.videoEnabled() {
		s.video = VideoRuntimeStarting(observedAtMS)
		if err := s.publishVideoDiscovery(ctx, publisher); err != nil {
			return err
		}
		if err := s.publishVideoStatusAndShadow(ctx, publisher); err != nil {
			return err
		}
	}
	return s.publishCapabilities(ctx, publisher, s.onlineCapabilities(), observedAtMS)
}

func RunConnectedRuntime(ctx context.Context, config RuntimeConfig, publisher interface {
	Publisher
	Subscribe(context.Context, string) error
}, incoming <-chan RuntimeMqttEvent) error {
	state, err := NewRuntimeState(config)
	if err != nil {
		return err
	}
	videoEvents := make(chan VideoWorkerEvent, 32)
	mcpEvents := make(chan interface{}, 32)
	var bridge *BoardVideoBridgeServerHandle
	if capabilityEnabled(config.Capabilities, VideoCapability) {
		bridge, err = StartBoardVideoBridgeServer(config, videoEvents, mcpEvents)
		if err != nil {
			return err
		}
		defer bridge.Shutdown()
	}
	subscription, err := BuildMCPSessionC2SSubscription(config.ThingID)
	if err != nil {
		return err
	}
	if err := publisher.Subscribe(ctx, subscription); err != nil {
		return err
	}
	if err := state.PublishOnline(ctx, publisher, DiscoverDefaultRouteAddresses(), nowMillis()); err != nil {
		return err
	}
	heartbeat := time.NewTicker(config.Heartbeat)
	defer heartbeat.Stop()
	watchdog := time.NewTicker(100 * time.Millisecond)
	defer watchdog.Stop()
	videoStatus := time.NewTicker(videoStatusHeartbeatSeconds * time.Second)
	defer videoStatus.Stop()

	for {
		select {
		case <-ctx.Done():
			_ = state.PublishOffline(context.Background(), publisher, nowMillis())
			return ctx.Err()
		case event, ok := <-incoming:
			if !ok {
				_ = state.PublishOffline(context.Background(), publisher, nowMillis())
				return nil
			}
			_ = state.HandleMQTTEvent(ctx, publisher, event, nowMillis())
		case event := <-videoEvents:
			_ = state.HandleVideoEvent(ctx, publisher, event, nowMillis())
		case event := <-mcpEvents:
			_ = state.HandleMCPIPCEvent(ctx, publisher, event, nowMillis())
		case <-heartbeat.C:
			_ = state.RefreshCapabilities(ctx, publisher, nowMillis())
		case <-watchdog.C:
			_ = state.TickWatchdogs(ctx, publisher, nowMillis())
		case <-videoStatus.C:
			_ = state.RefreshVideoStatus(ctx, publisher, nowMillis())
		}
	}
}

func (s *RuntimeState) RefreshCapabilities(ctx context.Context, publisher Publisher, observedAtMS uint64) error {
	if err := s.publishMCPStatus(ctx, publisher, observedAtMS); err != nil {
		return err
	}
	return s.publishCapabilities(ctx, publisher, s.onlineCapabilities(), observedAtMS)
}

func (s *RuntimeState) RefreshVideoStatus(ctx context.Context, publisher Publisher, observedAtMS uint64) error {
	if !s.videoEnabled() {
		return nil
	}
	s.video.UpdatedAtMS = observedAtMS
	return s.publishVideoStatusAndShadow(ctx, publisher)
}

func (s *RuntimeState) PublishOffline(ctx context.Context, publisher Publisher, observedAtMS uint64) error {
	_, _ = s.cmdVel.Stop(ctx, true)
	if err := s.publishBoardShadow(ctx, publisher, BuildOfflineBoardReport()); err != nil {
		return err
	}
	if err := s.publishMCPUnavailable(ctx, publisher, observedAtMS); err != nil {
		return err
	}
	if s.videoEnabled() {
		s.video = VideoRuntimeUnavailable(observedAtMS)
		if err := s.publishVideoStatusAndShadow(ctx, publisher); err != nil {
			return err
		}
	}
	return s.publishCapabilities(ctx, publisher, s.offlineCapabilities(), observedAtMS)
}

func (s *RuntimeState) CapabilitySeq() uint64 {
	return s.capabilityManager.Seq()
}

func (s *RuntimeState) TickWatchdogs(ctx context.Context, publisher Publisher, observedAtMS uint64) error {
	changed := s.mcp.ClearExpired(observedAtMS)
	if changed {
		_, _ = s.cmdVel.Stop(ctx, true)
	}
	motionChanged, _ := s.cmdVel.RefreshStatus(ctx)
	if changed || motionChanged {
		return s.publishMCPStatus(ctx, publisher, observedAtMS)
	}
	return nil
}

func (s *RuntimeState) HandleMQTTEvent(ctx context.Context, publisher Publisher, event RuntimeMqttEvent, observedAtMS uint64) error {
	if event.Disconnected {
		s.mcp.active = nil
		_, _ = s.cmdVel.Stop(ctx, true)
		return nil
	}
	return s.handleMCPPublish(ctx, publisher, event.Topic, event.Payload, observedAtMS)
}

func (s *RuntimeState) HandleVideoEvent(ctx context.Context, publisher Publisher, event VideoWorkerEvent, observedAtMS uint64) error {
	if !s.videoEnabled() {
		return nil
	}
	previousTransport := s.mcpTransportMode()
	s.video.ApplyEvent(event, observedAtMS)
	mcpStatusChanged := false
	switch event.Kind {
	case VideoWorkerMCPDataChannelClosed:
		mcpStatusChanged = s.stopIfRequired(ctx, s.mcp.CloseSession(event.SessionID))
	case VideoWorkerMCPDataChannelError:
		if strings.TrimSpace(event.SessionID) != "" {
			mcpStatusChanged = s.stopIfRequired(ctx, s.mcp.CloseSession(event.SessionID))
		}
	}
	nextTransport := s.mcpTransportMode()
	if previousTransport != nextTransport {
		_ = s.stopIfRequired(ctx, s.mcp.ClearActive())
		if err := s.publishMCPDiscovery(ctx, publisher, observedAtMS); err != nil {
			return err
		}
	}
	if mcpStatusChanged {
		if err := s.publishMCPStatus(ctx, publisher, observedAtMS); err != nil {
			return err
		}
	}
	if err := s.publishVideoStatusAndShadow(ctx, publisher); err != nil {
		return err
	}
	return s.publishCapabilities(ctx, publisher, s.onlineCapabilities(), observedAtMS)
}

func (s *RuntimeState) HandleMCPIPCEvent(ctx context.Context, publisher Publisher, event interface{}, observedAtMS uint64) error {
	switch typed := event.(type) {
	case RuntimeMcpOpenEvent:
		return nil
	case RuntimeMcpRequestEvent:
		updatesStatus := false
		response := s.handleMCPIPCRequest(ctx, typed.SessionID, typed.Payload, observedAtMS, &updatesStatus)
		if typed.Response != nil {
			typed.Response <- response
		}
		if updatesStatus {
			_ = s.publishMCPStatus(ctx, publisher, observedAtMS)
		}
	case RuntimeMcpCloseEvent:
		if s.stopIfRequired(ctx, s.mcp.CloseSession(typed.SessionID)) {
			return s.publishMCPStatus(ctx, publisher, observedAtMS)
		}
	default:
		return fmt.Errorf("unsupported MCP IPC event %T", event)
	}
	return nil
}

func (s *RuntimeState) handleMCPIPCRequest(ctx context.Context, sessionID, payload string, observedAtMS uint64, updatesStatus *bool) *string {
	var request map[string]interface{}
	if err := json.Unmarshal([]byte(payload), &request); err != nil {
		response := jsonRPCErrorResponse(nil, jsonRPCError(-32700, "parse error: "+err.Error()))
		encoded, _ := json.Marshal(response)
		value := string(encoded)
		return &value
	}
	id := request["id"]
	result, err := s.handleMCPJSONRPCRequest(ctx, sessionID, request, observedAtMS)
	if err != nil {
		response := jsonRPCErrorResponse(id, jsonRPCError(-32603, "internal error: "+err.Error()))
		encoded, _ := json.Marshal(response)
		value := string(encoded)
		return &value
	}
	*updatesStatus = result.UpdatesStatus
	if result.Response == nil {
		return nil
	}
	encoded, err := json.Marshal(result.Response)
	if err != nil {
		response := jsonRPCErrorResponse(id, jsonRPCError(-32603, "internal error: "+err.Error()))
		encoded, _ = json.Marshal(response)
	}
	value := string(encoded)
	return &value
}

func (s *RuntimeState) publishCapabilities(ctx context.Context, publisher Publisher, availability map[string]bool, observedAtMS uint64) error {
	return s.capabilityManager.PublishState(ctx, publisher, s.config.ThingID, availability, s.config.CapabilityTTL, observedAtMS)
}

func (s *RuntimeState) onlineCapabilities() map[string]bool {
	return map[string]bool{BoardCapability: true, MCPCapability: true, VideoCapability: s.video.Ready}
}

func (s *RuntimeState) offlineCapabilities() map[string]bool {
	return map[string]bool{BoardCapability: false, MCPCapability: false, VideoCapability: false}
}

func (s *RuntimeState) videoEnabled() bool {
	for _, capability := range s.config.Capabilities {
		if capability == VideoCapability {
			return true
		}
	}
	return false
}

func (s *RuntimeState) stopIfRequired(ctx context.Context, required bool) bool {
	if required {
		_, _ = s.cmdVel.Stop(ctx, true)
	}
	return required
}

func (s *RuntimeState) mcpTransportMode() MCPTransportMode {
	if s.videoEnabled() && s.video.Ready {
		return MCPTransportWebRTCDataChannel
	}
	return MCPTransportMQTT
}

func (s *RuntimeState) mcpDescriptor() map[string]interface{} {
	return MCPDescriptor(s.config, string(s.mcpTransportMode()))
}

func (s *RuntimeState) publishMCPDiscovery(ctx context.Context, publisher Publisher, observedAtMS uint64) error {
	descriptor := s.mcpDescriptor()
	statusPayload := s.mcp.Status(observedAtMS)
	descriptorTopic, _ := BuildMCPDescriptorTopic(s.config.ThingID)
	statusTopic, _ := BuildMCPStatusTopic(s.config.ThingID)
	if err := publishJSON(ctx, publisher, descriptorTopic, descriptor, true); err != nil {
		return err
	}
	if err := publishJSON(ctx, publisher, statusTopic, statusPayload, true); err != nil {
		return err
	}
	return s.publishMCPShadow(ctx, publisher, descriptor, statusPayload)
}

func (s *RuntimeState) publishMCPStatus(ctx context.Context, publisher Publisher, observedAtMS uint64) error {
	statusPayload := s.mcp.Status(observedAtMS)
	statusTopic, _ := BuildMCPStatusTopic(s.config.ThingID)
	if err := publishJSON(ctx, publisher, statusTopic, statusPayload, true); err != nil {
		return err
	}
	return s.publishMCPShadow(ctx, publisher, s.mcpDescriptor(), statusPayload)
}

func (s *RuntimeState) publishMCPUnavailable(ctx context.Context, publisher Publisher, observedAtMS uint64) error {
	statusPayload := map[string]interface{}{
		"serviceId":       MCPCapability,
		"available":       false,
		"status":          "offline",
		"protocolVersion": MCPProtocolVersion,
		"observedAtMs":    observedAtMS,
		"activeControl":   nil,
	}
	statusTopic, _ := BuildMCPStatusTopic(s.config.ThingID)
	if err := publishJSON(ctx, publisher, statusTopic, statusPayload, true); err != nil {
		return err
	}
	return s.publishMCPShadow(ctx, publisher, s.mcpDescriptor(), statusPayload)
}

func (s *RuntimeState) publishMCPShadow(ctx context.Context, publisher Publisher, descriptor, statusPayload map[string]interface{}) error {
	topic, _ := BuildMCPShadowUpdateTopic(s.config.ThingID)
	return publishJSON(ctx, publisher, topic, map[string]interface{}{
		"state": map[string]interface{}{"reported": map[string]interface{}{"descriptor": descriptor, "status": statusPayload}},
	}, false)
}

func (s *RuntimeState) publishVideoDiscovery(ctx context.Context, publisher Publisher) error {
	topic, _ := BuildVideoDescriptorTopic(s.config.ThingID)
	return publishJSON(ctx, publisher, topic, s.videoDescriptor(), true)
}

func (s *RuntimeState) publishVideoStatusAndShadow(ctx context.Context, publisher Publisher) error {
	descriptor := s.videoDescriptor()
	statusPayload := s.videoStatus()
	statusTopic, _ := BuildVideoStatusTopic(s.config.ThingID)
	if err := publishJSON(ctx, publisher, statusTopic, statusPayload, true); err != nil {
		return err
	}
	return s.publishVideoShadow(ctx, publisher, descriptor, statusPayload)
}

func (s *RuntimeState) publishVideoShadow(ctx context.Context, publisher Publisher, descriptor, statusPayload map[string]interface{}) error {
	topic, _ := BuildVideoShadowUpdateTopic(s.config.ThingID)
	return publishJSON(ctx, publisher, topic, map[string]interface{}{
		"state": map[string]interface{}{"reported": map[string]interface{}{"descriptor": descriptor, "status": statusPayload}},
	}, false)
}

func (s *RuntimeState) videoDescriptor() map[string]interface{} {
	return VideoDescriptor(s.config)
}

func (s *RuntimeState) videoStatus() map[string]interface{} {
	return map[string]interface{}{
		"serviceId":       VideoCapability,
		"available":       s.video.Available,
		"ready":           s.video.Ready,
		"status":          s.video.Status,
		"viewerConnected": s.video.ViewerConnected,
		"lastError":       s.video.LastError,
		"updatedAtMs":     s.video.UpdatedAtMS,
	}
}

func (s *RuntimeState) handleMCPPublish(ctx context.Context, publisher Publisher, topic string, payload []byte, observedAtMS uint64) error {
	sessionID, ok := ParseMCPSessionC2STopic(s.config.ThingID, topic)
	if !ok {
		return nil
	}
	var request map[string]interface{}
	if err := json.Unmarshal(payload, &request); err != nil {
		return fmt.Errorf("parse MCP JSON-RPC request: %w", err)
	}
	if s.mcpTransportMode() == MCPTransportWebRTCDataChannel {
		response := jsonRPCErrorResponse(request["id"], jsonRPCError(-32000, "MCP is available only over WebRTC data channel while video is ready"))
		return s.publishMCPResponse(ctx, publisher, sessionID, response)
	}
	result, err := s.handleMCPJSONRPCRequest(ctx, sessionID, request, observedAtMS)
	if err != nil {
		return err
	}
	if result.Response != nil {
		if err := s.publishMCPResponse(ctx, publisher, sessionID, result.Response); err != nil {
			return err
		}
	}
	if result.UpdatesStatus {
		return s.publishMCPStatus(ctx, publisher, observedAtMS)
	}
	return nil
}

type mcpJSONRPCHandleResult struct {
	Response      map[string]interface{}
	UpdatesStatus bool
}

func (s *RuntimeState) handleMCPJSONRPCRequest(ctx context.Context, sessionID string, request map[string]interface{}, observedAtMS uint64) (mcpJSONRPCHandleResult, error) {
	method, ok := request["method"].(string)
	if !ok {
		return mcpJSONRPCHandleResult{Response: jsonRPCErrorResponse(request["id"], jsonRPCError(-32600, "invalid request"))}, nil
	}
	id, hasID := request["id"]
	if !hasID {
		return mcpJSONRPCHandleResult{}, nil
	}
	var result interface{}
	var jsonErr map[string]interface{}
	switch method {
	case "initialize":
		result = map[string]interface{}{"protocolVersion": MCPProtocolVersion, "serverInfo": map[string]interface{}{"name": "txing-unit-daemon", "version": DaemonVersion}, "capabilities": map[string]interface{}{"tools": map[string]interface{}{}}}
	case "tools/list":
		result = map[string]interface{}{"tools": []map[string]string{{"name": "control.get_state"}, {"name": "control.activate"}, {"name": "control.renew_active"}, {"name": "control.release_active"}, {"name": "cmd_vel.publish"}, {"name": "cmd_vel.stop"}, {"name": "robot.get_state"}}}
	case "tools/call":
		params, _ := request["params"].(map[string]interface{})
		result, jsonErr = s.handleMCPToolCall(ctx, sessionID, params, observedAtMS)
	default:
		jsonErr = jsonRPCError(-32601, "method not found")
	}
	var response map[string]interface{}
	if jsonErr != nil {
		response = jsonRPCErrorResponse(id, jsonErr)
	} else {
		response = jsonRPCSuccess(id, result)
	}
	return mcpJSONRPCHandleResult{Response: response, UpdatesStatus: mcpRequestUpdatesStatus(method, request["params"])}, nil
}

func (s *RuntimeState) handleMCPToolCall(ctx context.Context, sessionID string, params map[string]interface{}, observedAtMS uint64) (interface{}, map[string]interface{}) {
	name, _ := params["name"].(string)
	if strings.TrimSpace(name) == "" {
		return nil, jsonRPCError(-32602, "MCP tools/call requires a tool name")
	}
	arguments, _ := params["arguments"].(map[string]interface{})
	if arguments == nil {
		arguments = map[string]interface{}{}
	}
	structured, err := s.handleMCPTool(ctx, sessionID, name, arguments, observedAtMS)
	if err != nil {
		return nil, toolErrorToJSONRPCError(name, err)
	}
	return map[string]interface{}{"structuredContent": structured, "content": []map[string]interface{}{{"type": "json", "json": structured}}}, nil
}

func (s *RuntimeState) handleMCPTool(ctx context.Context, sessionID, name string, arguments map[string]interface{}, observedAtMS uint64) (interface{}, error) {
	switch name {
	case "control.get_state":
		return s.mcp.RobotState(sessionID, s.cmdVel.DriveState(), s.video.RobotReport()).Control, nil
	case "control.activate":
		var actor *string
		if value, ok := arguments["actor"].(string); ok && strings.TrimSpace(value) != "" {
			trimmed := strings.TrimSpace(value)
			actor = &trimmed
		}
		takeover, _ := arguments["takeover"].(bool)
		active, stopRequired, err := s.mcp.Activate(sessionID, actor, string(s.mcpTransportMode()), takeover, observedAtMS)
		if err != nil {
			return nil, err
		}
		s.stopIfRequired(ctx, stopRequired)
		return map[string]interface{}{"activeControl": active, "activeTtlMs": DefaultMCPActiveTTLMillis}, nil
	case "control.renew_active":
		epoch, err := parseEpochArgument(arguments)
		if err != nil {
			return nil, err
		}
		active, err := s.mcp.RenewActive(sessionID, epoch, observedAtMS)
		if err != nil {
			return nil, err
		}
		return map[string]interface{}{"activeControl": active, "activeTtlMs": DefaultMCPActiveTTLMillis}, nil
	case "control.release_active":
		epoch, err := parseEpochArgument(arguments)
		if err != nil {
			return nil, err
		}
		stopRequired, err := s.mcp.ReleaseActive(sessionID, epoch, observedAtMS)
		if err != nil {
			return nil, err
		}
		s.stopIfRequired(ctx, stopRequired)
		return map[string]interface{}{"motion": s.cmdVel.DriveState()}, nil
	case "cmd_vel.publish":
		epoch, err := parseEpochArgument(arguments)
		if err != nil {
			return nil, err
		}
		active, err := s.mcp.EnsureActive(sessionID, epoch, observedAtMS)
		if err != nil {
			return nil, err
		}
		twistValue, ok := arguments["twist"]
		if !ok {
			return nil, errors.New("cmd_vel.publish requires twist")
		}
		encoded, _ := json.Marshal(twistValue)
		var twist Twist
		if err := json.Unmarshal(encoded, &twist); err != nil {
			return nil, fmt.Errorf("parse cmd_vel twist: %w", err)
		}
		motion, err := s.cmdVel.PublishTwist(ctx, twist, active.ExpiresAtMS)
		if err != nil {
			return nil, err
		}
		state := s.mcp.RobotState(sessionID, motion, s.video.RobotReport())
		return map[string]interface{}{"motion": motion, "activeControl": state.Control.ActiveControl, "activeExpiresAtMs": state.Control.ActiveExpiresAtMS}, nil
	case "cmd_vel.stop":
		epoch, err := parseEpochArgument(arguments)
		if err != nil {
			return nil, err
		}
		if _, err := s.mcp.EnsureActive(sessionID, epoch, observedAtMS); err != nil {
			return nil, err
		}
		motion, err := s.cmdVel.Stop(ctx, true)
		if err != nil {
			return nil, err
		}
		state := s.mcp.RobotState(sessionID, motion, s.video.RobotReport())
		return map[string]interface{}{"motion": motion, "activeControl": state.Control.ActiveControl, "activeExpiresAtMs": state.Control.ActiveExpiresAtMS}, nil
	case "robot.get_state":
		_, _ = s.cmdVel.RefreshStatus(ctx)
		return s.mcp.RobotState(sessionID, s.cmdVel.DriveState(), s.video.RobotReport()), nil
	default:
		return nil, fmt.Errorf("unknown MCP tool %s", name)
	}
}

func (s *RuntimeState) publishMCPResponse(ctx context.Context, publisher Publisher, sessionID string, payload map[string]interface{}) error {
	topic, err := BuildMCPSessionS2CTopic(s.config.ThingID, sessionID)
	if err != nil {
		return err
	}
	return publishJSON(ctx, publisher, topic, payload, false)
}

func (s *RuntimeState) publishBoardShadow(ctx context.Context, publisher Publisher, report BoardReport) error {
	topic, _ := BuildBoardShadowUpdateTopic(s.config.ThingID)
	return publishJSON(ctx, publisher, topic, BuildBoardShadowUpdate(report), false)
}

type BoardVideoBridgeServerHandle struct {
	path   string
	server *grpc.Server
	done   chan struct{}
}

func (h *BoardVideoBridgeServerHandle) Shutdown() {
	if h == nil {
		return
	}
	h.server.GracefulStop()
	<-h.done
	if err := os.Remove(h.path); err != nil && !errors.Is(err, os.ErrNotExist) {
		// Ignore cleanup failures to preserve shutdown best effort semantics.
	}
}

type BoardVideoBridgeService struct {
	boardvideov1.UnimplementedBoardVideoBridgeServer
	config             RuntimeConfig
	videoEvents        chan<- VideoWorkerEvent
	mcpEvents          chan<- interface{}
	credentialsFetcher func(context.Context, RuntimeConfig) (IotTemporaryCredentials, error)
}

func NewBoardVideoBridgeService(config RuntimeConfig, videoEvents chan<- VideoWorkerEvent, mcpEvents chan<- interface{}) *BoardVideoBridgeService {
	return &BoardVideoBridgeService{config: config, videoEvents: videoEvents, mcpEvents: mcpEvents, credentialsFetcher: FetchIotTemporaryCredentials}
}

func StartBoardVideoBridgeServer(config RuntimeConfig, videoEvents chan<- VideoWorkerEvent, mcpEvents chan<- interface{}) (*BoardVideoBridgeServerHandle, error) {
	listener, err := bindUnixListener(config.BoardVideoBridgeSocketPath)
	if err != nil {
		return nil, err
	}
	server := grpc.NewServer()
	boardvideov1.RegisterBoardVideoBridgeServer(server, NewBoardVideoBridgeService(config, videoEvents, mcpEvents))
	done := make(chan struct{})
	go func() {
		_ = server.Serve(listener)
		close(done)
	}()
	return &BoardVideoBridgeServerHandle{path: config.BoardVideoBridgeSocketPath, server: server, done: done}, nil
}

func (s *BoardVideoBridgeService) GetWorkerConfig(ctx context.Context, hello *boardvideov1.WorkerHello) (*boardvideov1.WorkerConfig, error) {
	if strings.TrimSpace(hello.GetProtocolVersion()) != boardVideoBridgeProtocolVersion {
		return nil, status.Error(codes.InvalidArgument, "unsupported board video bridge protocol_version")
	}
	credentials, err := s.credentialsFetcher(ctx, s.config)
	if err != nil {
		return nil, status.Errorf(codes.Unavailable, "resolve KVS worker credentials: %v", err)
	}
	response, err := BuildWorkerConfigResponse(s.config, credentials)
	if err != nil {
		return nil, status.Errorf(codes.Internal, "%v", err)
	}
	return response, nil
}

func (s *BoardVideoBridgeService) RefreshCredentials(ctx context.Context, _ *boardvideov1.RefreshCredentialsRequest) (*boardvideov1.KvsCredentials, error) {
	credentials, err := s.credentialsFetcher(ctx, s.config)
	if err != nil {
		return nil, status.Errorf(codes.Unavailable, "refresh KVS worker credentials: %v", err)
	}
	response, err := BridgeCredentialsFromIot(credentials)
	if err != nil {
		return nil, status.Errorf(codes.Internal, "%v", err)
	}
	return response, nil
}

func (s *BoardVideoBridgeService) ReportVideoState(_ context.Context, report *boardvideov1.VideoState) (*boardvideov1.Ack, error) {
	switch report.GetState() {
	case boardvideov1.VideoState_STARTING:
		s.sendVideoEvent(VideoWorkerEvent{Kind: VideoWorkerStarting})
		s.sendVideoEvent(VideoWorkerEvent{Kind: VideoWorkerViewerConnected, Connected: report.GetViewerCount() > 0})
	case boardvideov1.VideoState_READY:
		s.sendVideoEvent(VideoWorkerEvent{Kind: VideoWorkerReady})
		s.sendVideoEvent(VideoWorkerEvent{Kind: VideoWorkerViewerConnected, Connected: report.GetViewerCount() > 0})
	case boardvideov1.VideoState_ERROR:
		detail := report.GetError()
		if strings.TrimSpace(detail) == "" {
			detail = defaultBoardVideoWorkerErrorDetail
		}
		s.sendVideoEvent(VideoWorkerEvent{Kind: VideoWorkerError, Detail: detail})
		s.sendVideoEvent(VideoWorkerEvent{Kind: VideoWorkerViewerConnected, Connected: report.GetViewerCount() > 0})
	default:
		return nil, status.Error(codes.InvalidArgument, "video state must be STARTING, READY, or ERROR")
	}
	return &boardvideov1.Ack{}, nil
}

func (s *BoardVideoBridgeService) OpenMcpSession(_ context.Context, request *boardvideov1.OpenMcpSessionRequest) (*boardvideov1.Ack, error) {
	sessionID, err := normalizeBridgeSessionID(request.GetMcpSessionId())
	if err != nil {
		return nil, err
	}
	transport := strings.TrimSpace(request.GetTransport())
	if transport == "" {
		transport = defaultBoardVideoWorkerTransport
	}
	if err := s.sendMCPEvent(RuntimeMcpOpenEvent{SessionID: sessionID, Transport: transport, PeerID: strings.TrimSpace(request.GetPeerId())}); err != nil {
		return nil, err
	}
	return &boardvideov1.Ack{}, nil
}

func (s *BoardVideoBridgeService) HandleMcp(ctx context.Context, request *boardvideov1.McpRequest) (*boardvideov1.McpResponse, error) {
	sessionID, err := normalizeBridgeSessionID(request.GetMcpSessionId())
	if err != nil {
		return nil, err
	}
	payload := string(request.GetPayload())
	if !json.Valid([]byte(payload)) {
		return nil, status.Error(codes.InvalidArgument, "MCP payload must be UTF-8 JSON-RPC")
	}
	responseCh := make(chan *string, 1)
	if err := s.sendMCPEvent(RuntimeMcpRequestEvent{SessionID: sessionID, Payload: payload, Response: responseCh}); err != nil {
		return nil, err
	}
	select {
	case response := <-responseCh:
		if response == nil {
			return &boardvideov1.McpResponse{HasPayload: false}, nil
		}
		return &boardvideov1.McpResponse{HasPayload: true, Payload: []byte(*response)}, nil
	case <-time.After(time.Duration(DefaultMCPResponseTimeoutMillis) * time.Millisecond):
		return nil, status.Error(codes.DeadlineExceeded, "MCP response timed out")
	case <-ctx.Done():
		return nil, status.FromContextError(ctx.Err()).Err()
	}
}

func (s *BoardVideoBridgeService) CloseMcpSession(_ context.Context, request *boardvideov1.CloseMcpSessionRequest) (*boardvideov1.Ack, error) {
	sessionID, err := normalizeBridgeSessionID(request.GetMcpSessionId())
	if err != nil {
		return nil, err
	}
	reason := strings.TrimSpace(request.GetReason())
	if reason == "" {
		reason = defaultMCPBridgeSessionClosedReason
	}
	if err := s.sendMCPEvent(RuntimeMcpCloseEvent{SessionID: sessionID, Reason: reason}); err != nil {
		return nil, err
	}
	return &boardvideov1.Ack{}, nil
}

func (s *BoardVideoBridgeService) sendVideoEvent(event VideoWorkerEvent) error {
	select {
	case s.videoEvents <- event:
		return nil
	default:
		return status.Error(codes.Unavailable, "daemon video runtime stopped")
	}
}

func (s *BoardVideoBridgeService) sendMCPEvent(event interface{}) error {
	select {
	case s.mcpEvents <- event:
		return nil
	default:
		return status.Error(codes.Unavailable, "daemon MCP runtime stopped")
	}
}

func BuildWorkerConfigResponse(config RuntimeConfig, credentials IotTemporaryCredentials) (*boardvideov1.WorkerConfig, error) {
	bridgeCredentials, err := BridgeCredentialsFromIot(credentials)
	if err != nil {
		return nil, err
	}
	return &boardvideov1.WorkerConfig{
		Region:               config.VideoRegion,
		ChannelName:          config.VideoChannelName,
		ClientId:             BoardVideoWorkerClientID(config),
		McpDataChannelLabel:  MCPWebRTCDataChannelLabel,
		McpResponseTimeoutMs: DefaultMCPResponseTimeoutMillis,
		PreferIpv6:           config.KVSPreferIPv6,
		DisableIpv4Turn:      config.KVSDisableIPv4TURN,
		Credentials:          bridgeCredentials,
	}, nil
}

func BridgeCredentialsFromIot(credentials IotTemporaryCredentials) (*boardvideov1.KvsCredentials, error) {
	expires, err := ParseIotTemporaryCredentialsExpiration(credentials.Expiration)
	if err != nil {
		return nil, err
	}
	return &boardvideov1.KvsCredentials{
		AccessKeyId:     credentials.AccessKeyID,
		SecretAccessKey: credentials.SecretAccessKey,
		SessionToken:    credentials.SessionToken,
		ExpiresAt:       timestamppb.New(expires),
	}, nil
}

func BoardVideoWorkerClientID(config RuntimeConfig) string {
	return config.ThingID + "-unit-kvs-master"
}

type IotCredentialsRequest struct {
	URL       string
	ThingName string
}

type iotCredentialsEnvelope struct {
	Credentials IotTemporaryCredentials `json:"credentials"`
}

type IotTemporaryCredentials struct {
	AccessKeyID     string `json:"accessKeyId"`
	SecretAccessKey string `json:"secretAccessKey"`
	SessionToken    string `json:"sessionToken"`
	Expiration      string `json:"expiration"`
}

func BuildIotCredentialsRequest(config RuntimeConfig) (IotCredentialsRequest, error) {
	if err := validateEndpointHost(config.IoTCredentialEndpoint, "iot-credential-endpoint"); err != nil {
		return IotCredentialsRequest{}, err
	}
	if err := validateRoleAliasPublic(config.IoTRoleAlias); err != nil {
		return IotCredentialsRequest{}, err
	}
	return IotCredentialsRequest{URL: fmt.Sprintf("https://%s/role-aliases/%s/credentials", config.IoTCredentialEndpoint, config.IoTRoleAlias), ThingName: config.ThingID}, nil
}

func ParseIotCredentialsResponse(payload []byte) (IotTemporaryCredentials, error) {
	var envelope iotCredentialsEnvelope
	if err := json.Unmarshal(payload, &envelope); err != nil {
		return IotTemporaryCredentials{}, fmt.Errorf("parse AWS IoT credential provider response: %w", err)
	}
	if err := envelope.Credentials.validate(); err != nil {
		return IotTemporaryCredentials{}, err
	}
	return envelope.Credentials, nil
}

func (c IotTemporaryCredentials) validate() error {
	if strings.TrimSpace(c.AccessKeyID) == "" {
		return errors.New("accessKeyId must not be empty")
	}
	if strings.TrimSpace(c.SecretAccessKey) == "" {
		return errors.New("secretAccessKey must not be empty")
	}
	if strings.TrimSpace(c.SessionToken) == "" {
		return errors.New("sessionToken must not be empty")
	}
	if strings.TrimSpace(c.Expiration) == "" {
		return errors.New("expiration must not be empty")
	}
	return nil
}

func ParseIotTemporaryCredentialsExpiration(value string) (time.Time, error) {
	parsed, err := time.Parse(time.RFC3339, value)
	if err != nil {
		return time.Time{}, fmt.Errorf("parse IoT temporary credential expiration %q: %w", value, err)
	}
	return parsed, nil
}

func FetchIotTemporaryCredentials(ctx context.Context, config RuntimeConfig) (IotTemporaryCredentials, error) {
	request, err := BuildIotCredentialsRequest(config)
	if err != nil {
		return IotTemporaryCredentials{}, err
	}
	cert, err := tls.LoadX509KeyPair(config.IoTCertFile, config.IoTPrivateKeyFile)
	if err != nil {
		return IotTemporaryCredentials{}, fmt.Errorf("load IoT client identity: %w", err)
	}
	rootPEM, err := os.ReadFile(config.IoTRootCAFile)
	if err != nil {
		return IotTemporaryCredentials{}, fmt.Errorf("read IoT root CA %s: %w", config.IoTRootCAFile, err)
	}
	roots := x509.NewCertPool()
	if !roots.AppendCertsFromPEM(rootPEM) {
		return IotTemporaryCredentials{}, errors.New("load IoT root CA")
	}
	client := http.Client{Transport: &http.Transport{TLSClientConfig: &tls.Config{Certificates: []tls.Certificate{cert}, RootCAs: roots, MinVersion: tls.VersionTLS12}}}
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, request.URL, nil)
	if err != nil {
		return IotTemporaryCredentials{}, err
	}
	req.Header.Set("x-amzn-iot-thingname", request.ThingName)
	response, err := client.Do(req)
	if err != nil {
		return IotTemporaryCredentials{}, fmt.Errorf("request AWS IoT temporary credentials: %w", err)
	}
	defer response.Body.Close()
	body, err := io.ReadAll(response.Body)
	if err != nil {
		return IotTemporaryCredentials{}, fmt.Errorf("read AWS IoT temporary credential response: %w", err)
	}
	if response.StatusCode < 200 || response.StatusCode >= 300 {
		return IotTemporaryCredentials{}, fmt.Errorf("AWS IoT temporary credential request failed: %s", response.Status)
	}
	return ParseIotCredentialsResponse(body)
}

type iotCertificateCredentialsProvider struct {
	config RuntimeConfig
}

func (p iotCertificateCredentialsProvider) Retrieve(ctx context.Context) (aws.Credentials, error) {
	credentials, err := FetchIotTemporaryCredentials(ctx, p.config)
	if err != nil {
		return aws.Credentials{}, err
	}
	expires, err := ParseIotTemporaryCredentialsExpiration(credentials.Expiration)
	if err != nil {
		return aws.Credentials{}, err
	}
	return aws.Credentials{
		AccessKeyID:     credentials.AccessKeyID,
		SecretAccessKey: credentials.SecretAccessKey,
		SessionToken:    credentials.SessionToken,
		CanExpire:       true,
		Expires:         expires,
		Source:          "aws-iot-credential-provider",
	}, nil
}

func awsSDKConfigFromIotCredentials(ctx context.Context, runtimeConfig RuntimeConfig) (aws.Config, error) {
	return config.LoadDefaultConfig(ctx,
		config.WithRegion(runtimeConfig.AWSRegion),
		config.WithCredentialsProvider(aws.NewCredentialsCache(iotCertificateCredentialsProvider{config: runtimeConfig})),
	)
}

type SparkplugRedcon struct {
	Level       uint8
	Unavailable bool
}

func (r SparkplugRedcon) String() string {
	if r.Unavailable {
		return "sparkplug.redcon=unavailable"
	}
	return fmt.Sprintf("sparkplug.redcon=%d", r.Level)
}

func ParseSparkplugRedcon(payload []byte) (SparkplugRedcon, error) {
	var shadow map[string]interface{}
	if err := json.Unmarshal(payload, &shadow); err != nil {
		return SparkplugRedcon{}, fmt.Errorf("parse sparkplug shadow: %w", err)
	}
	if getStringAt(shadow, "state", "reported", "topic", "messageType") == "DDEATH" {
		return SparkplugRedcon{Unavailable: true}, nil
	}
	level, ok := getFloatAt(shadow, "state", "reported", "payload", "metrics", "redcon")
	if !ok {
		return SparkplugRedcon{Unavailable: true}, nil
	}
	if level < 1 || level > 4 || level != float64(uint8(level)) {
		return SparkplugRedcon{}, fmt.Errorf("sparkplug redcon value %v is outside 1..=4", level)
	}
	return SparkplugRedcon{Level: uint8(level)}, nil
}

func BuildIotDataEndpointURL(endpoint string) (string, error) {
	if err := validateEndpointHost(endpoint, "iot-endpoint"); err != nil {
		return "", err
	}
	return "https://" + endpoint, nil
}

func RunRuntime(ctx context.Context, config RuntimeConfig) error {
	redcon, err := ReadCurrentSparkplugRedcon(ctx, config)
	if err != nil {
		return err
	}
	_ = redcon
	publisher, incoming, err := ConnectMQTT(ctx, config)
	if err != nil {
		return err
	}
	defer publisher.Stop()
	return RunConnectedRuntime(ctx, config, publisher, incoming)
}

func ReadCurrentSparkplugRedcon(ctx context.Context, config RuntimeConfig) (SparkplugRedcon, error) {
	sdkConfig, err := awsSDKConfigFromIotCredentials(ctx, config)
	if err != nil {
		return SparkplugRedcon{}, err
	}
	endpoint, err := BuildIotDataEndpointURL(config.IoTEndpoint)
	if err != nil {
		return SparkplugRedcon{}, err
	}
	client := iotdataplane.NewFromConfig(sdkConfig, func(options *iotdataplane.Options) {
		options.BaseEndpoint = aws.String(endpoint)
	})
	response, err := client.GetThingShadow(ctx, &iotdataplane.GetThingShadowInput{
		ThingName:  aws.String(config.ThingID),
		ShadowName: aws.String("sparkplug"),
	})
	if err != nil {
		return SparkplugRedcon{}, fmt.Errorf("get sparkplug thing shadow thing=%s shadow=sparkplug endpoint=%s region=%s roleAlias=%s: %w", config.ThingID, config.IoTEndpoint, config.AWSRegion, config.IoTRoleAlias, err)
	}
	if response.Payload == nil {
		return SparkplugRedcon{}, errors.New("sparkplug shadow response did not include payload")
	}
	return ParseSparkplugRedcon(response.Payload)
}

type CloudWatchLogBaseFields struct {
	ThingID      string
	ClientID     string
	IoTRoleAlias string
	AWSRegion    string
}

func CloudWatchLogBaseFieldsFromConfig(config RuntimeConfig) CloudWatchLogBaseFields {
	return CloudWatchLogBaseFields{ThingID: config.ThingID, ClientID: config.ClientID, IoTRoleAlias: config.IoTRoleAlias, AWSRegion: config.AWSRegion}
}

type CloudWatchLogRecord struct {
	TimestampMS int64
	Message     string
}

type CloudWatchPutLogEventsResult struct {
	NextSequenceToken *string
}

type CloudWatchLogClientErrorKind string

const (
	CloudWatchAlreadyExists        CloudWatchLogClientErrorKind = "already-exists"
	CloudWatchNotFound             CloudWatchLogClientErrorKind = "not-found"
	CloudWatchInvalidSequenceToken CloudWatchLogClientErrorKind = "invalid-sequence-token"
	CloudWatchDataAlreadyAccepted  CloudWatchLogClientErrorKind = "data-already-accepted"
	CloudWatchOther                CloudWatchLogClientErrorKind = "other"
)

type CloudWatchLogClientError struct {
	Kind     CloudWatchLogClientErrorKind
	Message  string
	Expected *string
}

func (e CloudWatchLogClientError) Error() string {
	return e.Message
}

func NewCloudWatchLogClientError(kind CloudWatchLogClientErrorKind, message string) CloudWatchLogClientError {
	return CloudWatchLogClientError{Kind: kind, Message: message}
}

type CloudWatchLogsClient interface {
	CreateLogGroup(context.Context, string) error
	PutRetentionPolicy(context.Context, string, int32) error
	CreateLogStream(context.Context, string, string) error
	PutLogEvents(context.Context, string, string, []CloudWatchLogRecord, *string) (CloudWatchPutLogEventsResult, error)
}

type RealCloudWatchLogsClient struct {
	client *cloudwatchlogs.Client
}

func NewRealCloudWatchLogsClient(ctx context.Context, runtimeConfig RuntimeConfig) (*RealCloudWatchLogsClient, error) {
	sdkConfig, err := awsSDKConfigFromIotCredentials(ctx, runtimeConfig)
	if err != nil {
		return nil, err
	}
	return &RealCloudWatchLogsClient{client: cloudwatchlogs.NewFromConfig(sdkConfig)}, nil
}

func (c *RealCloudWatchLogsClient) CreateLogGroup(ctx context.Context, logGroup string) error {
	_, err := c.client.CreateLogGroup(ctx, &cloudwatchlogs.CreateLogGroupInput{LogGroupName: aws.String(logGroup)})
	return mapCloudWatchSDKError(err)
}

func (c *RealCloudWatchLogsClient) PutRetentionPolicy(ctx context.Context, logGroup string, retentionDays int32) error {
	_, err := c.client.PutRetentionPolicy(ctx, &cloudwatchlogs.PutRetentionPolicyInput{LogGroupName: aws.String(logGroup), RetentionInDays: aws.Int32(retentionDays)})
	return mapCloudWatchSDKError(err)
}

func (c *RealCloudWatchLogsClient) CreateLogStream(ctx context.Context, logGroup, logStream string) error {
	_, err := c.client.CreateLogStream(ctx, &cloudwatchlogs.CreateLogStreamInput{LogGroupName: aws.String(logGroup), LogStreamName: aws.String(logStream)})
	return mapCloudWatchSDKError(err)
}

func (c *RealCloudWatchLogsClient) PutLogEvents(ctx context.Context, logGroup, logStream string, events []CloudWatchLogRecord, sequenceToken *string) (CloudWatchPutLogEventsResult, error) {
	logEvents := make([]cwtypes.InputLogEvent, 0, len(events))
	for _, event := range events {
		timestamp := event.TimestampMS
		message := event.Message
		logEvents = append(logEvents, cwtypes.InputLogEvent{Timestamp: &timestamp, Message: &message})
	}
	output, err := c.client.PutLogEvents(ctx, &cloudwatchlogs.PutLogEventsInput{
		LogGroupName:  aws.String(logGroup),
		LogStreamName: aws.String(logStream),
		LogEvents:     logEvents,
		SequenceToken: sequenceToken,
	})
	if err != nil {
		return CloudWatchPutLogEventsResult{}, mapCloudWatchSDKError(err)
	}
	return CloudWatchPutLogEventsResult{NextSequenceToken: output.NextSequenceToken}, nil
}

func mapCloudWatchSDKError(err error) error {
	if err == nil {
		return nil
	}
	var alreadyExists *cwtypes.ResourceAlreadyExistsException
	if errors.As(err, &alreadyExists) {
		return CloudWatchLogClientError{Kind: CloudWatchAlreadyExists, Message: alreadyExists.ErrorMessage()}
	}
	var notFound *cwtypes.ResourceNotFoundException
	if errors.As(err, &notFound) {
		return CloudWatchLogClientError{Kind: CloudWatchNotFound, Message: notFound.ErrorMessage()}
	}
	var invalid *cwtypes.InvalidSequenceTokenException
	if errors.As(err, &invalid) {
		return CloudWatchLogClientError{Kind: CloudWatchInvalidSequenceToken, Message: invalid.ErrorMessage(), Expected: invalid.ExpectedSequenceToken}
	}
	var accepted *cwtypes.DataAlreadyAcceptedException
	if errors.As(err, &accepted) {
		return CloudWatchLogClientError{Kind: CloudWatchDataAlreadyAccepted, Message: accepted.ErrorMessage()}
	}
	var apiErr smithy.APIError
	if errors.As(err, &apiErr) {
		return CloudWatchLogClientError{Kind: CloudWatchOther, Message: apiErr.Error()}
	}
	return err
}

type CloudWatchLogWriter struct {
	config CloudWatchLogConfig
	client CloudWatchLogsClient
}

func NewCloudWatchLogWriter(config CloudWatchLogConfig, client CloudWatchLogsClient) *CloudWatchLogWriter {
	return &CloudWatchLogWriter{config: config, client: client}
}

func (w *CloudWatchLogWriter) EnsureReady(ctx context.Context) error {
	if w.client == nil {
		return errors.New(defaultCloudWatchLogsProviderUnavailable)
	}
	if err := w.client.CreateLogGroup(ctx, w.config.LogGroup); err != nil {
		var cwErr CloudWatchLogClientError
		if !errors.As(err, &cwErr) || cwErr.Kind != CloudWatchAlreadyExists {
			return fmt.Errorf("create CloudWatch log group: %w", err)
		}
	}
	if err := w.client.PutRetentionPolicy(ctx, w.config.LogGroup, w.config.RetentionDays); err != nil {
		return fmt.Errorf("set CloudWatch log group retention: %w", err)
	}
	if err := w.client.CreateLogStream(ctx, w.config.LogGroup, w.config.LogStream); err != nil {
		var cwErr CloudWatchLogClientError
		if !errors.As(err, &cwErr) || cwErr.Kind != CloudWatchAlreadyExists {
			return fmt.Errorf("create CloudWatch log stream: %w", err)
		}
	}
	return nil
}

func (w *CloudWatchLogWriter) PutLogEventsWithRetry(ctx context.Context, events []CloudWatchLogRecord, sequenceToken *string) (CloudWatchPutLogEventsResult, error) {
	result, err := w.client.PutLogEvents(ctx, w.config.LogGroup, w.config.LogStream, events, sequenceToken)
	if err == nil {
		return result, nil
	}
	var cwErr CloudWatchLogClientError
	if !errors.As(err, &cwErr) {
		return CloudWatchPutLogEventsResult{}, fmt.Errorf("put CloudWatch Logs batch: %w", err)
	}
	switch cwErr.Kind {
	case CloudWatchNotFound:
		if err := w.EnsureReady(ctx); err != nil {
			return CloudWatchPutLogEventsResult{}, err
		}
		return w.client.PutLogEvents(ctx, w.config.LogGroup, w.config.LogStream, events, sequenceToken)
	case CloudWatchInvalidSequenceToken:
		return w.client.PutLogEvents(ctx, w.config.LogGroup, w.config.LogStream, events, cwErr.Expected)
	case CloudWatchDataAlreadyAccepted:
		return CloudWatchPutLogEventsResult{}, nil
	default:
		return CloudWatchPutLogEventsResult{}, fmt.Errorf("put CloudWatch Logs batch: %w", err)
	}
}

func BuildCloudWatchLogMessage(base CloudWatchLogBaseFields, level, target, message string, eventFields map[string]interface{}, timestampMS uint64) (string, error) {
	fields := map[string]interface{}{
		"timestamp":      timestampMS,
		"level":          level,
		"target":         target,
		"message":        message,
		"thing_id":       base.ThingID,
		"client_id":      base.ClientID,
		"iot_role_alias": base.IoTRoleAlias,
		"aws_region":     base.AWSRegion,
	}
	for key, value := range eventFields {
		fields[key] = value
	}
	encoded, err := json.Marshal(fields)
	return string(encoded), err
}

func DebugFieldToJSONValue(value string) interface{} {
	var decoded interface{}
	if json.Unmarshal([]byte(value), &decoded) == nil {
		return decoded
	}
	return value
}

func PushCloudWatchLogBatchRecord(batch *[]CloudWatchLogRecord, record CloudWatchLogRecord) {
	if len(record.Message)+cloudWatchLogEventOverheadBytes > cloudWatchLogBatchMaxBytes {
		return
	}
	*batch = append(*batch, record)
}

func CloudWatchLogBatchShouldFlush(batch []CloudWatchLogRecord) bool {
	if len(batch) >= cloudWatchLogBatchMaxEvents {
		return true
	}
	return cloudWatchLogBatchSize(batch) >= cloudWatchLogBatchMaxBytes
}

func ParseVideoWorkerMarker(line string) (VideoWorkerEvent, bool) {
	trimmed := strings.TrimSpace(line)
	if trimmed == "" {
		return VideoWorkerEvent{}, false
	}
	marker, rest, found := strings.Cut(trimmed, " ")
	if !found {
		marker, rest = trimmed, ""
	}
	rest = strings.TrimSpace(rest)
	switch marker {
	case "TXING_KVS_READY":
		return VideoWorkerEvent{Kind: VideoWorkerReady, WorkerVersion: parseMarkerField(rest, "version")}, true
	case "TXING_VIEWER_CONNECTED":
		return VideoWorkerEvent{Kind: VideoWorkerViewerConnected, Connected: true}, true
	case "TXING_VIEWER_DISCONNECTED":
		return VideoWorkerEvent{Kind: VideoWorkerViewerConnected, Connected: false}, true
	case "TXING_MCP_DATACHANNEL_OPEN":
		return VideoWorkerEvent{Kind: VideoWorkerMCPDataChannelOpen, SessionID: parseMarkerField(rest, "sessionId")}, true
	case "TXING_MCP_DATACHANNEL_CLOSED":
		reason := parseMarkerField(rest, "reason")
		if reason == "" {
			reason = defaultMCPWebRTCDataChannelClosedReason
		}
		return VideoWorkerEvent{Kind: VideoWorkerMCPDataChannelClosed, SessionID: parseMarkerField(rest, "sessionId"), Reason: reason}, true
	case "TXING_MCP_DATACHANNEL_ERROR":
		detail := parseMarkerField(rest, "detail")
		if detail == "" {
			detail = defaultMCPWebRTCDataChannelErrorDetail
		}
		return VideoWorkerEvent{Kind: VideoWorkerMCPDataChannelError, SessionID: parseMarkerField(rest, "sessionId"), Detail: detail}, true
	case "TXING_KVS_ERROR":
		detail := parseMarkerField(rest, "detail")
		if detail == "" {
			detail = defaultNativeKVSWorkerErrorDetail
		}
		return VideoWorkerEvent{Kind: VideoWorkerError, Detail: detail}, true
	default:
		return VideoWorkerEvent{}, false
	}
}

func VideoCredentialRestartAt(expiresAt, now time.Time) time.Time {
	if expiresAt.Sub(now) > videoCredentialRestartMargin+videoCredentialRestartMinDelay {
		return expiresAt.Add(-videoCredentialRestartMargin)
	}
	return now.Add(videoCredentialRestartMinDelay)
}

func DiscoverDefaultRouteAddresses() DefaultRouteAddresses {
	return DefaultRouteAddresses{
		IPv4: probeDefaultRouteIP("udp4", "8.8.8.8:80"),
		IPv6: probeDefaultRouteIP("udp6", "[2001:4860:4860::8888]:80"),
	}
}

func publishJSON(ctx context.Context, publisher Publisher, topic string, payload interface{}, retain bool) error {
	encoded, err := json.Marshal(payload)
	if err != nil {
		return err
	}
	return publisher.Publish(ctx, PublishedMessage{Topic: topic, Payload: encoded, Retain: retain})
}

func mqttPacketConnect(clientID string) []byte {
	var variable bytes.Buffer
	writeMQTTString(&variable, "MQTT")
	variable.WriteByte(4)
	variable.WriteByte(2)
	_ = binary.Write(&variable, binary.BigEndian, uint16(mqttKeepAliveSeconds))
	writeMQTTString(&variable, clientID)
	return appendMQTTFixedHeader(0x10, variable.Bytes())
}

func mqttPacketSubscribe(packetID uint16, topicFilter string) []byte {
	var variable bytes.Buffer
	_ = binary.Write(&variable, binary.BigEndian, packetID)
	writeMQTTString(&variable, topicFilter)
	variable.WriteByte(mqttPublishQoS)
	return appendMQTTFixedHeader(0x82, variable.Bytes())
}

func mqttPacketPublish(packetID uint16, topic string, payload []byte, retain bool) []byte {
	var variable bytes.Buffer
	writeMQTTString(&variable, topic)
	_ = binary.Write(&variable, binary.BigEndian, packetID)
	variable.Write(payload)
	header := byte(0x30 | 0x02)
	if retain {
		header |= 0x01
	}
	return appendMQTTFixedHeader(header, variable.Bytes())
}

func mqttPacketPubAck(packetID uint16) []byte {
	return []byte{0x40, 0x02, byte(packetID >> 8), byte(packetID)}
}

func appendMQTTFixedHeader(first byte, payload []byte) []byte {
	packet := []byte{first}
	remaining := len(payload)
	for {
		encoded := byte(remaining % 128)
		remaining /= 128
		if remaining > 0 {
			encoded |= 128
		}
		packet = append(packet, encoded)
		if remaining == 0 {
			break
		}
	}
	return append(packet, payload...)
}

func readMQTTPacket(reader io.Reader) (byte, byte, []byte, error) {
	var first [1]byte
	if _, err := io.ReadFull(reader, first[:]); err != nil {
		return 0, 0, nil, err
	}
	multiplier := 1
	remaining := 0
	for i := 0; i < 4; i++ {
		var encoded [1]byte
		if _, err := io.ReadFull(reader, encoded[:]); err != nil {
			return 0, 0, nil, err
		}
		remaining += int(encoded[0]&127) * multiplier
		if encoded[0]&128 == 0 {
			payload := make([]byte, remaining)
			_, err := io.ReadFull(reader, payload)
			return first[0] >> 4, first[0] & 0x0f, payload, err
		}
		multiplier *= 128
	}
	return 0, 0, nil, errors.New("MQTT remaining length exceeded 4 bytes")
}

func parseMQTTPublish(flags byte, payload []byte) (string, uint16, []byte, byte, bool) {
	if len(payload) < 2 {
		return "", 0, nil, 0, false
	}
	topicLen := int(binary.BigEndian.Uint16(payload[:2]))
	if len(payload) < 2+topicLen {
		return "", 0, nil, 0, false
	}
	topic := string(payload[2 : 2+topicLen])
	offset := 2 + topicLen
	var packetID uint16
	qos := (flags & 0x06) >> 1
	if qos > 0 {
		if len(payload) < offset+2 {
			return "", 0, nil, 0, false
		}
		packetID = binary.BigEndian.Uint16(payload[offset : offset+2])
		offset += 2
	}
	return topic, packetID, payload[offset:], qos, true
}

func writeMQTTString(buffer *bytes.Buffer, value string) {
	_ = binary.Write(buffer, binary.BigEndian, uint16(len(value)))
	buffer.WriteString(value)
}

func jsonRPCSuccess(id interface{}, result interface{}) map[string]interface{} {
	if id == nil {
		id = nil
	}
	return map[string]interface{}{"jsonrpc": "2.0", "id": id, "result": result}
}

func jsonRPCErrorResponse(id interface{}, err map[string]interface{}) map[string]interface{} {
	return map[string]interface{}{"jsonrpc": "2.0", "id": id, "error": err}
}

func jsonRPCError(code int64, message string) map[string]interface{} {
	return map[string]interface{}{"code": code, "message": message}
}

func mcpRequestUpdatesStatus(method string, params interface{}) bool {
	if method != "tools/call" {
		return false
	}
	values, ok := params.(map[string]interface{})
	if !ok {
		return false
	}
	name, _ := values["name"].(string)
	return name == "control.activate" || name == "control.renew_active" || name == "control.release_active"
}

func parseEpochArgument(arguments map[string]interface{}) (uint64, error) {
	value, ok := arguments["epoch"]
	if !ok {
		return 0, errors.New("active control epoch is required")
	}
	switch typed := value.(type) {
	case float64:
		if typed < 0 || typed != float64(uint64(typed)) {
			return 0, errors.New("active control epoch is required")
		}
		return uint64(typed), nil
	case uint64:
		return typed, nil
	case int:
		if typed < 0 {
			return 0, errors.New("active control epoch is required")
		}
		return uint64(typed), nil
	default:
		return 0, errors.New("active control epoch is required")
	}
}

func toolErrorToJSONRPCError(_ string, err error) map[string]interface{} {
	message := err.Error()
	code := int64(-32602)
	if strings.Contains(message, "no active control") {
		code = -32011
	} else if strings.Contains(message, "active control busy") {
		code = -32012
	} else if strings.Contains(message, "stale active control epoch") {
		code = -32013
	}
	return jsonRPCError(code, message)
}

func bindUnixListener(socketPath string) (net.Listener, error) {
	if parent := filepath.Dir(socketPath); parent != "." && parent != "" {
		if err := os.MkdirAll(parent, 0o755); err != nil {
			return nil, err
		}
	}
	if err := os.Remove(socketPath); err != nil && !errors.Is(err, os.ErrNotExist) {
		return nil, err
	}
	return net.Listen("unix", socketPath)
}

func normalizeBridgeSessionID(sessionID string) (string, error) {
	trimmed := strings.TrimSpace(sessionID)
	if trimmed == "" {
		return "", status.Error(codes.InvalidArgument, "mcp_session_id is required")
	}
	return trimmed, nil
}

func twistToProto(twist Twist) *hardwarev1.Twist {
	return &hardwarev1.Twist{
		Linear:  &hardwarev1.Vector3{X: twist.Linear.X, Y: twist.Linear.Y, Z: twist.Linear.Z},
		Angular: &hardwarev1.Vector3{X: twist.Angular.X, Y: twist.Angular.Y, Z: twist.Angular.Z},
	}
}

func motionFromProto(motion *hardwarev1.MotionState) DriveState {
	if motion == nil {
		return DriveState{}
	}
	return DriveState{LeftSpeed: motion.GetLeftSpeed(), RightSpeed: motion.GetRightSpeed(), Sequence: motion.GetSequence()}
}

func hardwareStatusFromProto(status *hardwarev1.HardwareStatus) HardwareStatusSnapshot {
	if status == nil {
		return HardwareStatusSnapshot{}
	}
	return HardwareStatusSnapshot{ActuatorReady: status.GetActuatorReady(), Motion: motionFromProto(status.GetMotion())}
}

func parseMarkerField(fields, key string) string {
	prefix := key + "="
	if strings.HasPrefix(fields, prefix) {
		value := strings.TrimPrefix(fields, prefix)
		if key == "detail" || key == "reason" {
			return value
		}
		parts := strings.Fields(value)
		if len(parts) == 0 {
			return ""
		}
		return parts[0]
	}
	for _, field := range strings.Fields(fields) {
		if strings.HasPrefix(field, prefix) {
			return strings.TrimPrefix(field, prefix)
		}
	}
	return ""
}

func durationMillis(duration time.Duration) uint64 {
	if duration <= 0 {
		return 0
	}
	return uint64(duration / time.Millisecond)
}

func nowMillis() uint64 {
	return uint64(time.Now().UnixMilli())
}

func capabilityEnabled(capabilities []string, capability string) bool {
	for _, value := range capabilities {
		if value == capability {
			return true
		}
	}
	return false
}

func cloudWatchLogBatchSize(batch []CloudWatchLogRecord) int {
	size := 0
	for _, event := range batch {
		size += len(event.Message) + cloudWatchLogEventOverheadBytes
	}
	return size
}

func getStringAt(root map[string]interface{}, path ...string) string {
	var current interface{} = root
	for _, part := range path {
		values, ok := current.(map[string]interface{})
		if !ok {
			return ""
		}
		current = values[part]
	}
	value, _ := current.(string)
	return value
}

func getFloatAt(root map[string]interface{}, path ...string) (float64, bool) {
	var current interface{} = root
	for _, part := range path {
		values, ok := current.(map[string]interface{})
		if !ok {
			return 0, false
		}
		current = values[part]
	}
	value, ok := current.(float64)
	return value, ok
}

func probeDefaultRouteIP(network, remote string) net.IP {
	conn, err := net.Dial(network, remote)
	if err != nil {
		return nil
	}
	defer conn.Close()
	if udp, ok := conn.LocalAddr().(*net.UDPAddr); ok {
		return udp.IP
	}
	return nil
}

func validateCapabilityNamePublic(value string) error {
	return validateCapabilityName(value)
}

func validateRoleAliasPublic(value string) error {
	return validateRoleAlias(value)
}
