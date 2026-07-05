// BoardVideoBridge gRPC server copied from
// devices/unit/daemon/internal/daemon/runtime.go. The contract is
// docs/contracts/board-video-bridge.md; the generated stubs come from
// the shared proto devices/unit/proto/txing/unit/board_video/v1.
package action

import (
	"context"
	"encoding/json"
	"errors"
	"net"
	"os"
	"path/filepath"
	"strings"
	"time"

	boardvideov1 "github.com/mparkachov/txing/devices/mac/daemon/internal/proto/boardvideov1"
	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
	"google.golang.org/protobuf/types/known/timestamppb"
)

const (
	DefaultMCPResponseTimeoutMillis     = uint32(7000)
	defaultBoardVideoWorkerTransport    = "webrtc-datachannel"
	defaultMCPBridgeSessionClosedReason = "MCP bridge session closed"
)

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
	config             Config
	videoEvents        chan<- VideoWorkerEvent
	mcpEvents          chan<- interface{}
	credentialsFetcher func(context.Context, Config) (IotTemporaryCredentials, error)
}

func NewBoardVideoBridgeService(config Config, videoEvents chan<- VideoWorkerEvent, mcpEvents chan<- interface{}) *BoardVideoBridgeService {
	return &BoardVideoBridgeService{
		config:             config,
		videoEvents:        videoEvents,
		mcpEvents:          mcpEvents,
		credentialsFetcher: FetchIotTemporaryCredentials,
	}
}

func StartBoardVideoBridgeServer(config Config, videoEvents chan<- VideoWorkerEvent, mcpEvents chan<- interface{}) (*BoardVideoBridgeServerHandle, error) {
	listener, err := bindUnixListener(config.BridgeSocketPath)
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
	return &BoardVideoBridgeServerHandle{path: config.BridgeSocketPath, server: server, done: done}, nil
}

func (s *BoardVideoBridgeService) GetWorkerConfig(ctx context.Context, hello *boardvideov1.WorkerHello) (*boardvideov1.WorkerConfig, error) {
	if strings.TrimSpace(hello.GetProtocolVersion()) != boardVideoBridgeProtocolVersion {
		return nil, status.Error(codes.InvalidArgument, "unsupported board video bridge protocol_version")
	}
	credentials, err := s.credentialsFetcher(ctx, s.config)
	if err != nil {
		return nil, status.Errorf(codes.Unavailable, "resolve KVS worker credentials: %v", err)
	}
	bridgeCredentials, err := BridgeCredentialsFromIot(credentials)
	if err != nil {
		return nil, status.Errorf(codes.Internal, "%v", err)
	}
	return &boardvideov1.WorkerConfig{
		Region:               s.config.AWSRegion,
		ChannelName:          s.config.VideoChannelName,
		ClientId:             BoardVideoWorkerClientID(s.config),
		McpDataChannelLabel:  MCPWebRTCDataChannelLabel,
		McpResponseTimeoutMs: DefaultMCPResponseTimeoutMillis,
		PreferIpv6:           s.config.KVSPreferIPv6,
		DisableIpv4Turn:      s.config.KVSDisableIPv4TURN,
		Credentials:          bridgeCredentials,
	}, nil
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

func BoardVideoWorkerClientID(config Config) string {
	return config.ThingID + "-kvs-master"
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
