package daemon

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"reflect"
	"strings"
	"sync"
	"time"

	mavlinkbridgev1 "github.com/mparkachov/txing/devices/common/board/daemon/internal/proto/mavlinkbridgev1"
	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
	"google.golang.org/protobuf/types/known/timestamppb"
)

const (
	mavlinkBridgeProtocolVersion = "1"
	mavlinkBridgeResponseTimeout = 7 * time.Second
)

// MAVLinkFlightTransport is the daemon-side client of the independently
// supervised local MAVLink service. The bridge owns session policy; this
// transport only carries already-authorized frames and safe-state requests.
type MAVLinkFlightTransport interface {
	SendFrame([]byte) error
	RequestSafeState(reason string, requestDisarm bool)
	EnterSafeState(context.Context, string, bool) error
	Close()
}

type runtimeMAVLinkBridgeOpenEvent struct {
	response chan runtimeMAVLinkBridgeOpenResult
}

type runtimeMAVLinkBridgeOpenResult struct {
	peer *MAVLinkPeer
	err  error
}

type runtimeMAVLinkBridgeControlEvent struct {
	sessionID string
	json      string
	response  chan string
}

type runtimeMAVLinkBridgeFrameEvent struct {
	sessionID string
	epoch     uint64
	frame     []byte
	response  chan error
}

type runtimeMAVLinkBridgeCloseEvent struct {
	sessionID string
	reason    string
	response  chan error
}

type runtimeMAVLinkKVSReadyEvent struct {
	ready bool
	error string
}

type runtimeMAVLinkFlightStatusEvent struct {
	status MAVLinkRuntimeStatus
}

type runtimeMAVLinkTelemetryEvent struct {
	frame []byte
}

// HandleMAVLinkBridgeEvent runs on the daemon runtime loop. Keeping all
// ownership mutations here means KVS workers cannot bypass daemon authority
// even though their gRPC calls are concurrent.
func (s *RuntimeState) HandleMAVLinkBridgeEvent(ctx context.Context, publisher Publisher, event interface{}, observedAtMS uint64) error {
	if !s.mavlinkEnabled() {
		return nil
	}
	publishStatus := false
	safeReason := ""
	safeDisarm := false
	switch typed := event.(type) {
	case runtimeMAVLinkBridgeOpenEvent:
		typed.response <- runtimeMAVLinkBridgeOpenResult{peer: s.mavlink.OpenPeer()}
		publishStatus = true
	case runtimeMAVLinkBridgeControlEvent:
		result := s.mavlink.HandleControlMessage(typed.sessionID, typed.json, observedAtMS)
		if result.SafeRequired {
			safeReason = "MAVLink active control released"
		}
		typed.response <- result.Response
		publishStatus = result.StatusChanged
	case runtimeMAVLinkBridgeFrameEvent:
		policy, err := s.mavlinkUplinkPolicy()
		if err == nil {
			err = s.mavlink.AuthorizeControlFrame(typed.sessionID, typed.epoch, typed.frame, policy, observedAtMS)
		}
		if err == nil && s.mavlinkFlight == nil {
			err = errors.New("MAVLink local transport is unavailable")
		}
		if err == nil {
			err = s.mavlinkFlight.SendFrame(typed.frame)
		}
		if err == nil {
			s.mavlink.RecordAcceptedControlFrame(observedAtMS)
		}
		typed.response <- err
	case runtimeMAVLinkBridgeCloseEvent:
		if s.mavlink.ClosePeer(typed.sessionID) {
			safeReason = "MAVLink active peer closed"
		}
		typed.response <- nil
		publishStatus = true
	case runtimeMAVLinkKVSReadyEvent:
		errorMessage := ""
		if !typed.ready {
			errorMessage = strings.TrimSpace(typed.error)
		}
		if s.mavlinkKVSReady != typed.ready || s.mavlinkKVSError != errorMessage {
			s.mavlinkKVSReady = typed.ready
			s.mavlinkKVSError = errorMessage
			publishStatus = true
		}
	case runtimeMAVLinkFlightStatusEvent:
		if !reflect.DeepEqual(s.mavlinkStatus, typed.status) {
			s.mavlinkStatus = typed.status
			publishStatus = true
		}
	case runtimeMAVLinkTelemetryEvent:
		s.mavlink.BroadcastTelemetry(typed.frame)
	default:
		return fmt.Errorf("unsupported MAVLink bridge event %T", event)
	}
	if safeReason != "" {
		s.requestMAVLinkSafeState(safeReason, safeDisarm)
	}
	if publishStatus {
		if err := s.publishMAVLinkStatus(ctx, publisher); err != nil {
			return err
		}
		return s.publishCapabilities(ctx, publisher, s.onlineCapabilities(), observedAtMS)
	}
	return nil
}

func (s *RuntimeState) mavlinkUplinkPolicy() (MAVLinkUplinkPolicy, error) {
	if s.mavlinkStatus.Target == nil {
		return MAVLinkUplinkPolicy{}, errors.New("MAVLink flight-controller target is unavailable")
	}
	return DefaultMAVLinkUplinkPolicy(*s.mavlinkStatus.Target), nil
}

type MAVLinkBridgeServerHandle struct {
	path   string
	server *grpc.Server
	done   chan struct{}
}

func (h *MAVLinkBridgeServerHandle) Shutdown() {
	if h == nil {
		return
	}
	// ExchangeFrames is intentionally long-lived while a KVS/WebRTC peer is
	// connected. GracefulStop would wait forever for that stream during daemon
	// shutdown, after PublishOffline has already requested the safe state.
	h.server.Stop()
	<-h.done
	_ = os.Remove(h.path)
}

type MAVLinkBridgeService struct {
	mavlinkbridgev1.UnimplementedBoardMavlinkBridgeServer
	config             RuntimeConfig
	events             chan<- interface{}
	credentialsFetcher func(context.Context, RuntimeConfig) (IotTemporaryCredentials, error)
	peers              sync.Map // map[string]*MAVLinkPeer
}

func NewMAVLinkBridgeService(config RuntimeConfig, events chan<- interface{}) *MAVLinkBridgeService {
	return &MAVLinkBridgeService{config: config, events: events, credentialsFetcher: FetchIotTemporaryCredentials}
}

func StartMAVLinkBridgeServer(config RuntimeConfig, events chan<- interface{}) (*MAVLinkBridgeServerHandle, error) {
	listener, err := bindUnixListener(config.MAVLinkBridgeSocketPath)
	if err != nil {
		return nil, err
	}
	server := grpc.NewServer()
	mavlinkbridgev1.RegisterBoardMavlinkBridgeServer(server, NewMAVLinkBridgeService(config, events))
	done := make(chan struct{})
	go func() {
		_ = server.Serve(listener)
		close(done)
	}()
	return &MAVLinkBridgeServerHandle{path: config.MAVLinkBridgeSocketPath, server: server, done: done}, nil
}

func (s *MAVLinkBridgeService) GetControlChannelConfig(ctx context.Context, hello *mavlinkbridgev1.WorkerHello) (*mavlinkbridgev1.ControlChannelConfig, error) {
	if strings.TrimSpace(hello.GetProtocolVersion()) != mavlinkBridgeProtocolVersion {
		return nil, status.Error(codes.InvalidArgument, "unsupported MAVLink bridge protocol_version")
	}
	credentials, err := s.credentialsFetcher(ctx, s.config)
	if err != nil {
		return nil, status.Errorf(codes.Unavailable, "resolve MAVLink KVS credentials: %v", err)
	}
	converted, err := mavlinkBridgeCredentialsFromIot(credentials)
	if err != nil {
		return nil, status.Errorf(codes.Internal, "%v", err)
	}
	return &mavlinkbridgev1.ControlChannelConfig{
		Region:              s.config.AWSRegion,
		ChannelName:         s.config.MAVLinkChannelName,
		ClientId:            s.config.ClientID + "-mavlink",
		DataChannelLabel:    MAVLinkWebRTCDataChannelLabel,
		DataChannelOrdered:  true,
		DataChannelReliable: true,
		Credentials:         converted,
	}, nil
}

func (s *MAVLinkBridgeService) RefreshControlChannelCredentials(ctx context.Context, _ *mavlinkbridgev1.RefreshCredentialsRequest) (*mavlinkbridgev1.KvsCredentials, error) {
	credentials, err := s.credentialsFetcher(ctx, s.config)
	if err != nil {
		return nil, status.Errorf(codes.Unavailable, "refresh MAVLink KVS credentials: %v", err)
	}
	converted, err := mavlinkBridgeCredentialsFromIot(credentials)
	if err != nil {
		return nil, status.Errorf(codes.Internal, "%v", err)
	}
	return converted, nil
}

func (s *MAVLinkBridgeService) ReportControlChannelState(ctx context.Context, report *mavlinkbridgev1.ControlChannelState) (*mavlinkbridgev1.Ack, error) {
	if err := s.sendEvent(ctx, runtimeMAVLinkKVSReadyEvent{ready: report.GetReady(), error: report.GetError()}); err != nil {
		return nil, err
	}
	return &mavlinkbridgev1.Ack{}, nil
}

func (s *MAVLinkBridgeService) OpenPeer(ctx context.Context, request *mavlinkbridgev1.OpenPeerRequest) (*mavlinkbridgev1.OpenPeerResponse, error) {
	if strings.TrimSpace(request.GetPeerId()) == "" {
		return nil, status.Error(codes.InvalidArgument, "peer_id is required")
	}
	response := make(chan runtimeMAVLinkBridgeOpenResult, 1)
	if err := s.sendEvent(ctx, runtimeMAVLinkBridgeOpenEvent{response: response}); err != nil {
		return nil, err
	}
	select {
	case result := <-response:
		if result.err != nil {
			return nil, status.Errorf(codes.Internal, "%v", result.err)
		}
		s.peers.Store(result.peer.SessionID, result.peer)
		return &mavlinkbridgev1.OpenPeerResponse{SessionId: result.peer.SessionID}, nil
	case <-ctx.Done():
		return nil, status.FromContextError(ctx.Err()).Err()
	case <-time.After(mavlinkBridgeResponseTimeout):
		return nil, status.Error(codes.DeadlineExceeded, "MAVLink bridge open peer timed out")
	}
}

func (s *MAVLinkBridgeService) HandleControlMessage(ctx context.Context, request *mavlinkbridgev1.ControlMessageRequest) (*mavlinkbridgev1.ControlMessageResponse, error) {
	if !s.hasPeer(request.GetSessionId()) {
		return nil, status.Error(codes.NotFound, "unknown MAVLink peer session")
	}
	if !json.Valid([]byte(request.GetJson())) {
		return nil, status.Error(codes.InvalidArgument, "MAVLink control payload must be JSON")
	}
	response := make(chan string, 1)
	if err := s.sendEvent(ctx, runtimeMAVLinkBridgeControlEvent{sessionID: request.GetSessionId(), json: request.GetJson(), response: response}); err != nil {
		return nil, err
	}
	select {
	case value := <-response:
		return &mavlinkbridgev1.ControlMessageResponse{Json: value}, nil
	case <-ctx.Done():
		return nil, status.FromContextError(ctx.Err()).Err()
	case <-time.After(mavlinkBridgeResponseTimeout):
		return nil, status.Error(codes.DeadlineExceeded, "MAVLink control response timed out")
	}
}

func (s *MAVLinkBridgeService) ExchangeFrames(stream grpc.BidiStreamingServer[mavlinkbridgev1.PeerFrame, mavlinkbridgev1.PeerFrame]) error {
	first, err := stream.Recv()
	if err != nil {
		return err
	}
	sessionID := first.GetSessionId()
	peer, ok := s.lookupPeer(sessionID)
	if !ok {
		return status.Error(codes.NotFound, "unknown MAVLink peer session")
	}
	if len(first.GetFrame()) != 0 {
		if err := s.forwardUplink(stream.Context(), sessionID, first.GetEpoch(), first.GetFrame()); err != nil {
			return err
		}
	}
	receiveDone := make(chan error, 1)
	go func() {
		for {
			message, receiveErr := stream.Recv()
			if receiveErr != nil {
				receiveDone <- receiveErr
				return
			}
			if message.GetSessionId() != sessionID || len(message.GetFrame()) == 0 || message.GetEpoch() == 0 {
				receiveDone <- status.Error(codes.InvalidArgument, "MAVLink stream frames require the opened session and one frame")
				return
			}
			if forwardErr := s.forwardUplink(stream.Context(), sessionID, message.GetEpoch(), message.GetFrame()); forwardErr != nil {
				receiveDone <- forwardErr
				return
			}
		}
	}()
	defer func() {
		closeCtx, cancel := context.WithTimeout(context.Background(), time.Second)
		defer cancel()
		_ = s.closePeer(closeCtx, sessionID, "MAVLink data channel closed")
	}()
	for {
		select {
		case frame := <-peer.Outbound:
			if err := stream.Send(&mavlinkbridgev1.PeerFrame{SessionId: sessionID, Frame: frame}); err != nil {
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

func (s *MAVLinkBridgeService) ClosePeer(ctx context.Context, request *mavlinkbridgev1.ClosePeerRequest) (*mavlinkbridgev1.Ack, error) {
	if !s.hasPeer(request.GetSessionId()) {
		return &mavlinkbridgev1.Ack{}, nil
	}
	reason := strings.TrimSpace(request.GetReason())
	if reason == "" {
		reason = "MAVLink peer closed"
	}
	if err := s.closePeer(ctx, request.GetSessionId(), reason); err != nil {
		return nil, err
	}
	return &mavlinkbridgev1.Ack{}, nil
}

func (s *MAVLinkBridgeService) forwardUplink(ctx context.Context, sessionID string, epoch uint64, frame []byte) error {
	response := make(chan error, 1)
	if err := s.sendEvent(ctx, runtimeMAVLinkBridgeFrameEvent{sessionID: sessionID, epoch: epoch, frame: append([]byte(nil), frame...), response: response}); err != nil {
		return err
	}
	select {
	case err := <-response:
		if err != nil {
			return status.Error(codes.PermissionDenied, err.Error())
		}
		return nil
	case <-ctx.Done():
		return status.FromContextError(ctx.Err()).Err()
	case <-time.After(mavlinkBridgeResponseTimeout):
		return status.Error(codes.DeadlineExceeded, "MAVLink frame authorization timed out")
	}
}

func (s *MAVLinkBridgeService) closePeer(ctx context.Context, sessionID, reason string) error {
	s.peers.Delete(sessionID)
	response := make(chan error, 1)
	if err := s.sendEvent(ctx, runtimeMAVLinkBridgeCloseEvent{sessionID: sessionID, reason: reason, response: response}); err != nil {
		return err
	}
	select {
	case err := <-response:
		return err
	case <-ctx.Done():
		return status.FromContextError(ctx.Err()).Err()
	case <-time.After(mavlinkBridgeResponseTimeout):
		return status.Error(codes.DeadlineExceeded, "MAVLink peer close timed out")
	}
}

func (s *MAVLinkBridgeService) sendEvent(ctx context.Context, event interface{}) error {
	select {
	case s.events <- event:
		return nil
	case <-ctx.Done():
		return status.FromContextError(ctx.Err()).Err()
	}
}

func (s *MAVLinkBridgeService) hasPeer(sessionID string) bool {
	_, ok := s.lookupPeer(sessionID)
	return ok
}

func (s *MAVLinkBridgeService) lookupPeer(sessionID string) (*MAVLinkPeer, bool) {
	value, ok := s.peers.Load(sessionID)
	if !ok {
		return nil, false
	}
	peer, ok := value.(*MAVLinkPeer)
	return peer, ok
}

func mavlinkBridgeCredentialsFromIot(credentials IotTemporaryCredentials) (*mavlinkbridgev1.KvsCredentials, error) {
	expiresAt, err := ParseIotTemporaryCredentialsExpiration(credentials.Expiration)
	if err != nil {
		return nil, err
	}
	return &mavlinkbridgev1.KvsCredentials{
		AccessKeyId:     credentials.AccessKeyID,
		SecretAccessKey: credentials.SecretAccessKey,
		SessionToken:    credentials.SessionToken,
		ExpiresAt:       timestamppb.New(expiresAt),
	}, nil
}
