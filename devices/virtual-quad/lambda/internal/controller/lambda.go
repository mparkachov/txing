package controller

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/aws/aws-lambda-go/lambdacontext"
	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/service/iotdataplane"
	"txing.dev/virtual-quad-lambda/internal/lifecycle"
	"txing.dev/virtual-quad-lambda/internal/session"
)

// LambdaHandler owns each accepted session in its Start invocation. Shadow
// updates and Lambda failure destinations enter as separate invocations.
type LambdaHandler struct {
	registry       Registry
	shadow         session.Shadow
	client         ReportClient
	cfg            aws.Config
	endpoint       string
	root           string
	reconnectLimit time.Duration
	healthInterval time.Duration
	startWorkload  func(string, string) (simulator, error)
	subscribe      func(context.Context, aws.Config, string, string, string, string) (<-chan session.Notification, func(), error)
}

type simulator interface {
	Done() <-chan struct{}
	Err() error
	Stop() error
	Health() session.Health
}

func NewLambdaHandler(cfg aws.Config, endpoint string, registry Registry, client ReportClient) LambdaHandler {
	return LambdaHandler{registry: registry, shadow: session.NewShadow(client), client: client,
		cfg: cfg, endpoint: endpoint, root: filepath.Join(os.Getenv("LAMBDA_TASK_ROOT"), "quad"), reconnectLimit: 10 * time.Second, healthInterval: 5 * time.Second,
		startWorkload: func(root, device string) (simulator, error) { return session.StartWorkload(root, device) },
		subscribe: func(ctx context.Context, cfg aws.Config, endpoint, device, rig, owner string) (<-chan session.Notification, func(), error) {
			n, err := session.Subscribe(ctx, cfg, endpoint, device, rig, owner)
			return n.Events, n.Close, err
		}}
}

type lambdaEvent struct {
	Topic      string `json:"mqttTopic"`
	Payload    string `json:"payloadBase64"`
	Action     string `json:"action"`
	DeviceID   string `json:"deviceId"`
	DetailType string `json:"detail-type"`
	Detail     struct {
		RequestContext struct {
			RequestID string `json:"requestId"`
		} `json:"requestContext"`
		RequestPayload struct {
			Topic   string `json:"mqttTopic"`
			Payload string `json:"payloadBase64"`
		} `json:"requestPayload"`
	} `json:"detail"`
}

func (h LambdaHandler) Handle(ctx context.Context, raw json.RawMessage) (any, error) {
	var e lambdaEvent
	if err := json.Unmarshal(raw, &e); err != nil {
		return nil, lifecycle.ErrInvalidRequest
	}
	switch {
	case e.Action == "report" && segment.MatchString(e.DeviceID) && strings.HasPrefix(e.DeviceID, "virtual-quad-"):
		return nil, h.report(ctx, e.DeviceID)
	case e.DetailType == "Lambda Function Invocation Result - Failure":
		return nil, h.failure(ctx, e)
	case e.Topic != "" && e.Action == "":
		return nil, h.command(ctx, e)
	default:
		return nil, lifecycle.ErrInvalidRequest
	}
}

func (h LambdaHandler) command(ctx context.Context, e lambdaEvent) error {
	cmd, err := decodeCommand(e.Topic, e.Payload)
	if err != nil {
		return err
	}
	assignment, awake, err := h.registry.Assignment(ctx, cmd.Assignment.DeviceID)
	if err != nil && (cmd.REDCON == 1 || assignment != cmd.Assignment) {
		return err
	}
	if assignment != cmd.Assignment {
		return lifecycle.ErrStaleTarget
	}
	if cmd.REDCON == 4 {
		_, err = h.shadow.Change(ctx, assignment.DeviceID, func(s *session.State) error {
			return s.Stop(cmd.SessionID, strings.ToLower(cmd.Request.ID), cmd.Request.Sequence, time.Now().UnixMilli())
		})
		if errors.Is(err, session.ErrDuplicate) || errors.Is(err, session.ErrStale) {
			return nil
		}
		if errors.Is(err, session.ErrBusy) {
			return h.reject(ctx, cmd, err)
		}
		return err
	}
	if !awake {
		return h.reject(ctx, cmd, lifecycle.ErrRigAsleep)
	}
	lc, ok := lambdacontext.FromContext(ctx)
	deadline, hasDeadline := ctx.Deadline()
	if !ok || lc.AwsRequestID == "" || !hasDeadline {
		return errors.New("Lambda invocation identity or deadline missing")
	}
	// Anchor the first new projection after any existing Sparkplug timestamp.
	previous, err := (AWSReporter{client: h.client}).readShadow(ctx, assignment.DeviceID, "sparkplug")
	if err != nil {
		return err
	}
	owner := lc.AwsRequestID
	_, err = h.shadow.Change(ctx, assignment.DeviceID, func(s *session.State) error {
		if err := s.Start(strings.ToLower(cmd.Request.ID), owner, assignment.TownID, assignment.RigID,
			cmd.Request.Sequence, cmd.TerminalRevision, time.Now().UnixMilli(), deadline.UnixMilli()); err != nil {
			return err
		}
		s.ProjectionTimestamp = max(s.ProjectionTimestamp, previous.State.Reported.Payload.Timestamp)
		return nil
	})
	if errors.Is(err, session.ErrDuplicate) || errors.Is(err, session.ErrStale) {
		return nil
	}
	if errors.Is(err, session.ErrBusy) {
		return h.reject(ctx, cmd, err)
	}
	if err != nil {
		return err
	}
	return h.run(ctx, assignment, owner)
}

// Rejections do not change session ownership or its deadlines. Persisting the
// correlated receipt lets the normal shadow event report it through Witness.
func (h LambdaHandler) reject(ctx context.Context, cmd command, cause error) error {
	_, err := h.shadow.Change(ctx, cmd.Assignment.DeviceID, func(s *session.State) error {
		// Another invocation can finish and replace the session between the
		// failed transition and this write. Do not let an old rejection change
		// the replacement's correlated receipt.
		if cmd.REDCON == 1 {
			if s.TerminalRevision != cmd.TerminalRevision {
				return session.ErrStale
			}
			if s.Run != nil && s.Run.StartRequestID == strings.ToLower(cmd.Request.ID) {
				return session.ErrDuplicate
			}
		} else if s.SessionID == nil || *s.SessionID != cmd.SessionID {
			return session.ErrStale
		}
		s.Receipt = &session.Receipt{RequestID: strings.ToLower(cmd.Request.ID), Sequence: cmd.Request.Sequence,
			REDCON: cmd.REDCON, Status: "failed", Reason: cause.Error()}
		return nil
	})
	if errors.Is(err, session.ErrStale) || errors.Is(err, session.ErrDuplicate) {
		return nil
	}
	return err
}

func (h LambdaHandler) run(ctx context.Context, target lifecycle.Assignment, owner string) (result error) {
	outcome, reason := "failed", "session startup failed"
	defer func() {
		finishCtx, cancel := context.WithTimeout(context.WithoutCancel(ctx), 5*time.Second)
		defer cancel()
		_, err := h.shadow.Change(finishCtx, target.DeviceID, func(s *session.State) error {
			return s.Finish(owner, outcome, reason, time.Now().UnixMilli())
		})
		if err != nil && !errors.Is(err, session.ErrNotOwner) {
			result = errors.Join(result, fmt.Errorf("finalize session: %w", err))
		}
	}()
	notifications, closeNotifications, err := h.subscribe(ctx, h.cfg, h.endpoint, target.DeviceID, target.RigID, owner)
	if err != nil {
		return err
	}
	defer closeNotifications()
	startTimer := time.NewTimer(15 * time.Second)
	defer startTimer.Stop()
	for {
		select {
		case event := <-notifications:
			if event == session.Subscribed {
				goto subscribed
			}
			if event == session.Disconnected {
				return errors.New("MQTT subscription failed")
			}
		case <-startTimer.C:
			return errors.New("MQTT subscription timed out")
		case <-ctx.Done():
			return ctx.Err()
		}
	}
subscribed:
	assignment, awake, err := h.boundedAssignment(ctx, target.DeviceID)
	if err != nil {
		return err
	}
	if assignment != target || !awake {
		outcome, reason = "stopped", "rig asleep or assignment changed"
		return nil
	}
	state, err := h.boundedRead(ctx, target.DeviceID)
	if err != nil {
		return err
	}
	if state.Run == nil || state.Run.Owner != owner {
		return session.ErrNotOwner
	}
	if state.Phase == "stopping" {
		outcome, reason = "stopped", "operator stop"
		return nil
	}
	if state.StartupDeadline == nil {
		return errors.New("accepted session has no startup deadline")
	}
	// Use the absolute cutoff, not just the next health tick: a five-second
	// tick immediately before the flight deadline must not grant another tick.
	flightDeadline := int64(0)
	deadline := *state.StartupDeadline
	if state.Phase == "operational" && state.FlightDeadline != nil {
		flightDeadline = *state.FlightDeadline
		deadline = flightDeadline
	}
	deadlineTimer := time.NewTimer(time.Until(time.UnixMilli(deadline)))
	defer deadlineTimer.Stop()
	controlCtx, cancelDeadline := context.WithDeadline(ctx, time.UnixMilli(deadline))
	defer func() { cancelDeadline() }()
	deadlineReached := func() bool {
		if time.Now().UnixMilli() < deadline {
			return false
		}
		if flightDeadline == 0 {
			reason = "startup deadline exceeded"
		} else {
			outcome, reason = "stopped", "flight deadline reached"
		}
		return true
	}
	if deadlineReached() {
		return nil
	}
	workload, err := h.startWorkload(h.root, target.DeviceID)
	if err != nil {
		return err
	}
	defer func() {
		if err := workload.Stop(); err != nil {
			outcome, reason = "failed", "supervisor shutdown failed"
			result = errors.Join(result, err)
		}
	}()
	ticker := time.NewTicker(h.healthInterval)
	defer ticker.Stop()
	connected := true
	var reconnectTimer *time.Timer
	var reconnectC <-chan time.Time
	var reconnectDeadline time.Time
	lastExpiry := state.AvailabilityExpires
	defer func() {
		if reconnectTimer != nil {
			reconnectTimer.Stop()
		}
	}()
	for {
		select {
		case <-reconnectC:
			reason = "shadow notifications disconnected"
			return errors.New(reason)
		case <-deadlineTimer.C:
			deadlineReached()
			return nil
		case <-workload.Done():
			reason = "supervisor exited unexpectedly"
			return fmt.Errorf("%s: %v", reason, workload.Err())
		case event := <-notifications:
			if event == session.Disconnected {
				if connected {
					connected = false
					reconnectDeadline = time.Now().Add(h.reconnectLimit)
					if lastExpiry != nil {
						reconnectDeadline = minTime(reconnectDeadline, time.UnixMilli(*lastExpiry).Add(-time.Second))
					}
					reconnectTimer = time.NewTimer(time.Until(reconnectDeadline))
					reconnectC = reconnectTimer.C
				}
				continue
			}
			if !connected && event != session.Subscribed {
				continue
			}
			readCtx := controlCtx
			cancelRead := func() {}
			if !connected {
				readCtx, cancelRead = context.WithDeadline(controlCtx, reconnectDeadline)
			}
			if event == session.RigUpdated || event == session.Subscribed {
				assignment, awake, err := h.boundedAssignment(readCtx, target.DeviceID)
				if err != nil {
					cancelRead()
					if deadlineReached() {
						return nil
					}
					reason = "rig status unavailable"
					return err
				}
				if assignment != target || !awake {
					cancelRead()
					outcome, reason = "stopped", "rig asleep or assignment changed"
					return nil
				}
			}
			state, err := h.boundedRead(readCtx, target.DeviceID)
			cancelRead()
			if err != nil {
				if deadlineReached() {
					return nil
				}
				reason = "shadow read failed"
				return err
			}
			if state.Run == nil || state.Run.Owner != owner {
				return session.ErrNotOwner
			}
			if state.Phase == "stopping" {
				outcome, reason = "stopped", "operator stop"
				return nil
			}
			if !connected {
				if !time.Now().Before(reconnectDeadline) || (state.Phase == "operational" &&
					(state.AvailabilityExpires == nil || time.Now().UnixMilli() >= *state.AvailabilityExpires)) {
					reason = "shadow notifications disconnected"
					return errors.New(reason)
				}
				reconnectTimer.Stop()
				reconnectC = nil
				connected = true
			}
			lastExpiry = state.AvailabilityExpires
		case <-ticker.C:
			if !connected {
				continue
			}
			updateCtx, cancel := context.WithTimeout(controlCtx, 4*time.Second)
			current, err := h.shadow.Change(updateCtx, target.DeviceID, func(s *session.State) error {
				return s.UpdateHealth(owner, workload.Health(), time.Now().UnixMilli())
			})
			cancel()
			if errors.Is(err, session.ErrNotOwner) {
				state, readErr := h.boundedRead(controlCtx, target.DeviceID)
				if readErr == nil && state.Run != nil && state.Run.Owner == owner && state.Phase == "stopping" {
					outcome, reason = "stopped", "operator stop"
					return nil
				}
				return err
			}
			if errors.Is(err, session.ErrExpired) {
				if current.Phase == "starting" {
					reason = "startup deadline exceeded"
					return nil
				}
				if current.FlightDeadline != nil && time.Now().UnixMilli() >= *current.FlightDeadline {
					outcome, reason = "stopped", "flight deadline reached"
				} else {
					reason = "readiness expired"
				}
				return nil
			}
			if err != nil {
				if deadlineReached() {
					return nil
				}
				reason = "health update failed"
				return err
			}
			if current.FlightDeadline != nil && *current.FlightDeadline != flightDeadline {
				flightDeadline = *current.FlightDeadline
				deadline = flightDeadline
				deadlineTimer.Reset(time.Until(time.UnixMilli(deadline)))
				cancelDeadline()
				controlCtx, cancelDeadline = context.WithDeadline(ctx, time.UnixMilli(deadline))
			}
			lastExpiry = current.AvailabilityExpires
		case <-ctx.Done():
			reason = "invocation cancelled"
			return ctx.Err()
		}
	}
}

func minTime(a, b time.Time) time.Time {
	if b.Before(a) {
		return b
	}
	return a
}

func (h LambdaHandler) boundedRead(ctx context.Context, device string) (session.State, error) {
	ctx, cancel := context.WithTimeout(ctx, 4*time.Second)
	defer cancel()
	state, _, err := h.shadow.Read(ctx, device)
	return state, err
}

func (h LambdaHandler) boundedAssignment(ctx context.Context, device string) (lifecycle.Assignment, bool, error) {
	ctx, cancel := context.WithTimeout(ctx, 4*time.Second)
	defer cancel()
	return h.registry.Assignment(ctx, device)
}

func (h LambdaHandler) failure(ctx context.Context, e lambdaEvent) error {
	cmd, err := decodeCommand(e.Detail.RequestPayload.Topic, e.Detail.RequestPayload.Payload)
	if err != nil || cmd.REDCON != 1 || e.Detail.RequestContext.RequestID == "" {
		return nil
	}
	_, err = h.shadow.Change(ctx, cmd.Assignment.DeviceID, func(s *session.State) error {
		return s.Finish(e.Detail.RequestContext.RequestID, "failed", "Lambda invocation failed", time.Now().UnixMilli())
	})
	if errors.Is(err, session.ErrNotOwner) {
		return nil
	}
	return err
}

func (h LambdaHandler) report(ctx context.Context, device string) error {
	target, _, err := h.registry.Assignment(ctx, device)
	if err != nil {
		return err
	}
	state, _, err := h.shadow.Read(ctx, device)
	if err != nil {
		return err
	}
	if state.Run != nil && (state.Run.TownID != target.TownID || state.Run.RigID != target.RigID) {
		return nil
	}
	current, err := (AWSReporter{client: h.client}).readShadow(ctx, device, "sparkplug")
	if err != nil {
		return err
	}
	topic := current.State.Reported.Topic
	if state.ProjectionTimestamp <= current.State.Reported.Payload.Timestamp || topic.Namespace != "spBv1.0" ||
		topic.GroupID != target.TownID || topic.EdgeNodeID != target.RigID || topic.DeviceID != target.DeviceID ||
		(topic.MessageType != "DBIRTH" && topic.MessageType != "DDATA") {
		return nil
	}
	a := state.Availability(time.Now().UnixMilli())
	p := lifecycle.Projection{TimestampMS: state.ProjectionTimestamp, REDCON: a.REDCON,
		Simulation: &a.Simulation, Mavlink: a.Mavlink, Video: a.Video, Agent: a.REDCON == 1}
	if state.SessionID != nil {
		p.SessionID = *state.SessionID
	} else if state.LastSessionID != nil {
		p.SessionID = *state.LastSessionID
	}
	if r := state.Receipt; r != nil {
		p.Receipt = lifecycle.Receipt{RequestID: r.RequestID, Sequence: r.Sequence,
			REDCON: r.REDCON, Status: lifecycle.Status(r.Status), Reason: r.Reason}
	}
	name := fmt.Sprintf("spBv1.0/%s/DDATA/%s/%s", target.TownID, target.RigID, target.DeviceID)
	_, err = h.client.Publish(ctx, &iotdataplane.PublishInput{Topic: aws.String(name), Qos: 1, Payload: encodeProjection(p)})
	if err != nil {
		log.Printf("virtual quad projection failed: %v", err)
	}
	return err
}
