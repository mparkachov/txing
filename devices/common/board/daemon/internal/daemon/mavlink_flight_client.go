package daemon

import (
	"context"
	"errors"
	"fmt"
	"sync"
	"sync/atomic"
	"time"

	mavlinkv1 "github.com/mparkachov/txing/devices/common/board/daemon/internal/proto/mavlinkv1"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"
)

const (
	mavlinkFlightDialTimeout  = 2 * time.Second
	mavlinkFlightCallTimeout  = 700 * time.Millisecond
	mavlinkFlightRetryDelay   = time.Second
	mavlinkFlightStatusPeriod = time.Second
)

// MAVLinkFlightClient keeps one reconnecting local gRPC exchange with the
// supervised flight-controller transport. It never owns peer identity or
// lease state; those decisions remain in RuntimeState.
type MAVLinkFlightClient struct {
	socketPath string
	events     chan<- interface{}
	outbound   chan []byte
	safe       chan mavlinkSafeStateRequest
	connected  atomic.Bool
	cancel     context.CancelFunc
	done       chan struct{}
	closeOnce  sync.Once
}

type mavlinkSafeStateRequest struct {
	reason        string
	requestDisarm bool
	done          chan error
}

func StartMAVLinkFlightClient(parent context.Context, socketPath string, events chan<- interface{}) *MAVLinkFlightClient {
	ctx, cancel := context.WithCancel(parent)
	client := &MAVLinkFlightClient{
		socketPath: socketPath,
		events:     events,
		outbound:   make(chan []byte, 64),
		safe:       make(chan mavlinkSafeStateRequest, 8),
		cancel:     cancel,
		done:       make(chan struct{}),
	}
	go client.run(ctx)
	return client
}

func (c *MAVLinkFlightClient) SendFrame(frame []byte) error {
	if !c.connected.Load() {
		return errors.New("MAVLink local transport is unavailable")
	}
	copy := append([]byte(nil), frame...)
	select {
	case c.outbound <- copy:
		return nil
	default:
		return errors.New("MAVLink local transport outbound queue is full")
	}
}

func (c *MAVLinkFlightClient) RequestSafeState(reason string, requestDisarm bool) {
	request := mavlinkSafeStateRequest{reason: reason, requestDisarm: requestDisarm}
	select {
	case c.safe <- request:
	default:
		// A prior safe-state request is already queued. Coalescing preserves the
		// bounded non-blocking watchdog path without weakening its outcome.
	}
}

func (c *MAVLinkFlightClient) EnterSafeState(ctx context.Context, reason string, requestDisarm bool) error {
	request := mavlinkSafeStateRequest{reason: reason, requestDisarm: requestDisarm, done: make(chan error, 1)}
	select {
	case c.safe <- request:
	case <-ctx.Done():
		return ctx.Err()
	}
	select {
	case err := <-request.done:
		return err
	case <-ctx.Done():
		return ctx.Err()
	}
}

func (c *MAVLinkFlightClient) Close() {
	c.closeOnce.Do(func() {
		c.cancel()
		<-c.done
	})
}

func (c *MAVLinkFlightClient) run(ctx context.Context) {
	defer close(c.done)
	for {
		if ctx.Err() != nil {
			return
		}
		if err := c.connectAndServe(ctx); err != nil && ctx.Err() == nil {
			c.emit(runtimeMAVLinkFlightStatusEvent{status: MAVLinkUnavailableStatus(err.Error())})
		}
		c.connected.Store(false)
		if !waitMAVLinkFlightRetry(ctx, mavlinkFlightRetryDelay) {
			return
		}
	}
}

func (c *MAVLinkFlightClient) connectAndServe(ctx context.Context) error {
	dialCtx, cancel := context.WithTimeout(ctx, mavlinkFlightDialTimeout)
	defer cancel()
	conn, err := grpc.DialContext(dialCtx, "unix://"+c.socketPath, grpc.WithTransportCredentials(insecure.NewCredentials()), grpc.WithBlock())
	if err != nil {
		return fmt.Errorf("connect to MAVLink service: %w", err)
	}
	defer conn.Close()
	client := mavlinkv1.NewBoardMavlinkClient(conn)
	if err := c.publishStatus(ctx, client); err != nil {
		return err
	}
	streamCtx, stopStream := context.WithCancel(ctx)
	defer stopStream()
	stream, err := client.Exchange(streamCtx)
	if err != nil {
		return fmt.Errorf("open MAVLink exchange: %w", err)
	}
	c.connected.Store(true)
	defer c.connected.Store(false)
	return c.serveExchange(streamCtx, client, stream)
}

func (c *MAVLinkFlightClient) serveExchange(ctx context.Context, client mavlinkv1.BoardMavlinkClient, stream grpc.BidiStreamingClient[mavlinkv1.MavlinkFrame, mavlinkv1.MavlinkFrame]) error {
	received := make(chan mavlinkFlightReceiveResult, 1)
	go func() {
		for {
			frame, err := stream.Recv()
			if err != nil {
				received <- mavlinkFlightReceiveResult{err: err}
				return
			}
			received <- mavlinkFlightReceiveResult{frame: frame.GetFrame()}
		}
	}()
	statusTicker := time.NewTicker(mavlinkFlightStatusPeriod)
	defer statusTicker.Stop()
	for {
		select {
		case frame := <-c.outbound:
			if err := stream.Send(&mavlinkv1.MavlinkFrame{Frame: frame}); err != nil {
				return fmt.Errorf("send MAVLink frame: %w", err)
			}
		case request := <-c.safe:
			err := c.enterSafeState(ctx, client, request)
			if request.done != nil {
				request.done <- err
			}
			if err != nil {
				c.emit(runtimeMAVLinkFlightStatusEvent{status: MAVLinkUnavailableStatus(err.Error())})
			}
		case result := <-received:
			if result.err != nil {
				return fmt.Errorf("receive MAVLink frame: %w", result.err)
			}
			if len(result.frame) == 0 {
				continue
			}
			c.emit(runtimeMAVLinkTelemetryEvent{frame: append([]byte(nil), result.frame...)})
		case <-statusTicker.C:
			if err := c.publishStatus(ctx, client); err != nil {
				return err
			}
		case <-ctx.Done():
			return ctx.Err()
		}
	}
}

type mavlinkFlightReceiveResult struct {
	frame []byte
	err   error
}

func (c *MAVLinkFlightClient) publishStatus(parent context.Context, client mavlinkv1.BoardMavlinkClient) error {
	ctx, cancel := context.WithTimeout(parent, mavlinkFlightCallTimeout)
	defer cancel()
	statusPayload, err := client.GetStatus(ctx, &mavlinkv1.GetStatusRequest{})
	if err != nil {
		return fmt.Errorf("get MAVLink status: %w", err)
	}
	c.emit(runtimeMAVLinkFlightStatusEvent{status: mavlinkRuntimeStatusFromProto(statusPayload)})
	return nil
}

func (c *MAVLinkFlightClient) enterSafeState(parent context.Context, client mavlinkv1.BoardMavlinkClient, request mavlinkSafeStateRequest) error {
	ctx, cancel := context.WithTimeout(parent, mavlinkFlightCallTimeout)
	defer cancel()
	_, err := client.EnterSafeState(ctx, &mavlinkv1.EnterSafeStateRequest{Reason: request.reason, RequestDisarm: request.requestDisarm})
	if err != nil {
		return fmt.Errorf("enter MAVLink safe state: %w", err)
	}
	return c.publishStatus(parent, client)
}

func (c *MAVLinkFlightClient) emit(event interface{}) {
	select {
	case c.events <- event:
	default:
		// Status is sampled again every second and telemetry may be dropped for a
		// slow daemon loop, preserving bounded transport behavior.
	}
}

func waitMAVLinkFlightRetry(ctx context.Context, delay time.Duration) bool {
	timer := time.NewTimer(delay)
	defer timer.Stop()
	select {
	case <-timer.C:
		return true
	case <-ctx.Done():
		return false
	}
}

func mavlinkRuntimeStatusFromProto(value *mavlinkv1.MavlinkStatus) MAVLinkRuntimeStatus {
	status := MAVLinkRuntimeStatus{
		LinkState:      mavlinkLinkStateString(value.GetLinkState()),
		HeartbeatFresh: value.GetHeartbeatFresh(),
		Armed:          value.GetArmed(),
		Errors:         make([]MAVLinkError, 0, len(value.GetErrors())),
	}
	if target := value.GetTarget(); target != nil {
		status.Target = &MAVLinkTarget{SystemID: target.GetSystemId(), ComponentID: target.GetComponentId()}
	}
	if value.GetMode() != "" {
		mode := value.GetMode()
		status.Mode = &mode
	}
	for _, item := range value.GetErrors() {
		status.Errors = append(status.Errors, MAVLinkError{Code: item.GetCode(), Message: item.GetMessage()})
	}
	return status
}

func mavlinkLinkStateString(value mavlinkv1.LinkState) string {
	switch value {
	case mavlinkv1.LinkState_LINK_STATE_STARTING:
		return "starting"
	case mavlinkv1.LinkState_LINK_STATE_READY:
		return "ready"
	case mavlinkv1.LinkState_LINK_STATE_DEGRADED:
		return "degraded"
	case mavlinkv1.LinkState_LINK_STATE_UNAVAILABLE:
		return "unavailable"
	default:
		return "unavailable"
	}
}
