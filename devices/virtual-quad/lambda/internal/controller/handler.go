package controller

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"errors"
	"log"
	"net/http"
	"strings"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws/arn"
	"txing.dev/virtual-quad-lambda/internal/lifecycle"
)

type Reporter interface {
	Publish(context.Context, lifecycle.Assignment, *lifecycle.Receipt) error
}

type Handler struct {
	ledger     lifecycle.Ledger
	reconciler lifecycle.Reconciler
	registry   Registry
	records    lifecycle.RecordInventory
	reports    Reporter
	workerRole string
	workerSTS  string
	now        func() time.Time
}

func NewHandler(ledger lifecycle.Ledger, reconciler lifecycle.Reconciler, registry Registry, records lifecycle.RecordInventory, reports Reporter, workerRole string) (Handler, error) {
	role, err := arn.Parse(workerRole)
	if err != nil || role.Service != "iam" || role.AccountID == "" || !strings.HasPrefix(role.Resource, "role/") {
		return Handler{}, errors.New("invalid virtual quad worker role ARN")
	}
	roleName := role.Resource[strings.LastIndex(role.Resource, "/")+1:]
	if roleName == "" {
		return Handler{}, errors.New("virtual quad worker role ARN is missing its role name")
	}
	return Handler{
		ledger: ledger, reconciler: reconciler, registry: registry, records: records, reports: reports,
		workerRole: workerRole, workerSTS: "arn:" + role.Partition + ":sts::" + role.AccountID + ":assumed-role/" + roleName + "/",
		now: time.Now,
	}, nil
}

type functionURLContext struct {
	HTTP struct {
		Method string `json:"method"`
		Path   string `json:"path"`
	} `json:"http"`
	Authorizer struct {
		IAM struct {
			UserARN string `json:"userArn"`
		} `json:"iam"`
	} `json:"authorizer"`
}

type event struct {
	Topic           string              `json:"mqttTopic"`
	PayloadBase64   string              `json:"payloadBase64"`
	Action          string              `json:"action"`
	RequestContext  *functionURLContext `json:"requestContext"`
	Body            string              `json:"body"`
	IsBase64Encoded bool                `json:"isBase64Encoded"`
}

type workerRequest struct {
	Action   string           `json:"action"`
	DeviceID string           `json:"deviceId"`
	Worker   lifecycle.Worker `json:"worker"`
	Health   lifecycle.Health `json:"health"`
}

type workerResponse struct {
	Granted            bool  `json:"granted"`
	FlightAllowed      bool  `json:"flightAllowed"`
	FlightDeadlineMS   int64 `json:"flightDeadlineMs,omitempty"`
	ShutdownDeadlineMS int64 `json:"shutdownDeadlineMs,omitempty"`
}

type functionURLResponse struct {
	StatusCode int               `json:"statusCode"`
	Headers    map[string]string `json:"headers"`
	Body       string            `json:"body"`
}

func workerReply(status int, grant workerResponse) functionURLResponse {
	body, _ := json.Marshal(grant)
	return functionURLResponse{StatusCode: status, Headers: map[string]string{"content-type": "application/json"}, Body: string(body)}
}

func (h Handler) Handle(ctx context.Context, raw json.RawMessage) (any, error) {
	var input event
	if err := json.Unmarshal(raw, &input); err != nil {
		return nil, lifecycle.ErrInvalidRequest
	}
	switch {
	case input.RequestContext != nil:
		// Lambda wraps HTTP calls. Worker bodies are never dispatched as
		// trusted IoT or Scheduler events.
		return h.handleWorker(ctx, input), nil
	case input.Topic != "" && input.Action == "":
		return h.handleCommand(ctx, input)
	case input.Topic == "" && input.Action == "repair":
		return nil, h.repair(ctx)
	default:
		return nil, lifecycle.ErrInvalidRequest
	}
}

func (h Handler) handleCommand(ctx context.Context, input event) (lifecycle.Receipt, error) {
	var receipt lifecycle.Receipt
	cmd, err := decodeCommand(input.Topic, input.PayloadBase64)
	if err != nil {
		return receipt, err
	}
	assignment, awake, err := h.registry.Assignment(ctx, cmd.Assignment.DeviceID)
	// Stop only needs a verified assignment. A failed rig-status read must
	// not prevent a valid Stop from revoking the reservation.
	if err != nil && (cmd.REDCON == 1 || assignment != cmd.Assignment) {
		return receipt, err
	}
	if assignment != cmd.Assignment {
		return receipt, lifecycle.ErrStaleTarget
	}
	nowMS := h.now().UnixMilli()
	var record lifecycle.Record
	if cmd.REDCON == 1 {
		record, receipt, err = h.ledger.Reserve(ctx, assignment, cmd.Request, cmd.TerminalRevision, awake, nowMS)
	} else {
		record, receipt, err = h.ledger.RequestStop(ctx, assignment, cmd.Request, cmd.SessionID, nowMS)
	}
	if err != nil {
		if !errors.Is(err, lifecycle.ErrStaleTarget) && !errors.Is(err, lifecycle.ErrBusy) && !errors.Is(err, lifecycle.ErrRigAsleep) {
			return receipt, err
		}
		receipt = lifecycle.Receipt{
			RequestID: strings.ToLower(cmd.Request.ID), Sequence: cmd.Request.Sequence, REDCON: cmd.REDCON,
			Status: lifecycle.Failed, Reason: err.Error(),
		}
		return receipt, h.reports.Publish(ctx, assignment, &receipt)
	}
	// Retry delivery can return a receipt for the preceding generation.
	// Only drive the session that actually owns this command.
	if s := record.Session; s != nil && s.Assignment == assignment && ((cmd.REDCON == 1 &&
		s.Start.RequestID == receipt.RequestID && record.TerminalRevision == cmd.TerminalRevision) ||
		(cmd.REDCON == 4 && s.ID == cmd.SessionID)) {
		// Keep a slow IoT projection from consuming the Stop or startup budget.
		publishCtx, cancel := context.WithTimeout(ctx, 2*time.Second)
		publishErr := h.reports.Publish(publishCtx, assignment, &receipt)
		cancel()
		var reconcileErr error
		if cmd.REDCON == 4 {
			_, reconcileErr = h.reconciler.ReconcileStop(ctx, record)
		} else {
			_, reconcileErr = h.reconciler.ReconcileStart(ctx, assignment, s.ID, awake)
		}
		return receipt, errors.Join(publishErr, reconcileErr, h.reports.Publish(ctx, assignment, nil))
	}
	return receipt, h.reports.Publish(ctx, assignment, &receipt)
}

func (h Handler) handleWorker(ctx context.Context, input event) functionURLResponse {
	meta := input.RequestContext
	caller := meta.Authorizer.IAM.UserARN
	if caller != h.workerRole && (!strings.HasPrefix(caller, h.workerSTS) || len(caller) == len(h.workerSTS)) {
		return workerReply(http.StatusForbidden, workerResponse{})
	}
	if meta.HTTP.Method != http.MethodPost || meta.HTTP.Path != "/" || len(input.Body) > 4096 {
		return workerReply(http.StatusBadRequest, workerResponse{})
	}
	body := []byte(input.Body)
	if input.IsBase64Encoded {
		decoded, err := base64.StdEncoding.DecodeString(input.Body)
		if err != nil {
			return workerReply(http.StatusBadRequest, workerResponse{})
		}
		body = decoded
	}
	var request workerRequest
	if err := json.Unmarshal(body, &request); err != nil || !segment.MatchString(request.DeviceID) ||
		!strings.HasPrefix(request.DeviceID, "virtual-quad-") || !segment.MatchString(request.Worker.VMID) ||
		!segment.MatchString(request.Worker.SessionID) || !segment.MatchString(request.Worker.Token) {
		return workerReply(http.StatusBadRequest, workerResponse{})
	}
	nowMS := h.now().UnixMilli()
	var record lifecycle.Record
	var err error
	switch request.Action {
	case "claim":
		record, err = h.ledger.Claim(ctx, request.DeviceID, request.Worker, nowMS)
	case "grant", "health":
		record, err = h.ledger.WorkerGrant(ctx, request.DeviceID, request.Worker, nowMS)
	default:
		return workerReply(http.StatusBadRequest, workerResponse{})
	}
	if err != nil {
		return workerError(err)
	}
	assignment, awake, err := h.registry.Assignment(ctx, request.DeviceID)
	if err != nil && !errors.Is(err, ErrNotAssigned) {
		return workerError(err)
	}
	if assignment != record.Session.Assignment || !awake {
		_, revokeErr := h.ledger.RevokeIfDue(ctx, request.DeviceID, request.Worker.SessionID, assignment, awake, h.now().UnixMilli())
		if revokeErr != nil && !errors.Is(revokeErr, lifecycle.ErrStaleTarget) {
			return workerError(revokeErr)
		}
		return workerReply(http.StatusForbidden, workerResponse{})
	}
	nowMS = h.now().UnixMilli()
	if request.Action == "health" {
		if _, err := h.ledger.ReportHealth(ctx, request.DeviceID, request.Worker, request.Health, nowMS); err != nil {
			return workerError(err)
		}
		if err := h.reports.Publish(ctx, assignment, nil); err != nil {
			return workerError(err)
		}
	}
	nowMS = h.now().UnixMilli()
	record, err = h.ledger.WorkerGrant(ctx, request.DeviceID, request.Worker, nowMS)
	if err != nil {
		return workerError(err)
	}
	return workerReply(http.StatusOK, workerResponse{
		Granted: true, FlightAllowed: record.Availability(nowMS).REDCON == 1,
		FlightDeadlineMS: record.Session.FlightDeadlineMS, ShutdownDeadlineMS: record.Session.ShutdownDeadlineMS,
	})
}

func workerError(err error) functionURLResponse {
	if errors.Is(err, lifecycle.ErrGrantDenied) || errors.Is(err, lifecycle.ErrStaleTarget) {
		return workerReply(http.StatusForbidden, workerResponse{})
	}
	if errors.Is(err, lifecycle.ErrStaleHealth) {
		return workerReply(http.StatusConflict, workerResponse{})
	}
	log.Printf("virtual quad worker operation failed: %v", err)
	return workerReply(http.StatusServiceUnavailable, workerResponse{})
}

func (h Handler) repair(ctx context.Context) error {
	records, err := h.records.Records(ctx)
	if err != nil {
		return err
	}
	var failures []error
	for _, record := range records {
		assignment, awake, err := h.registry.Assignment(ctx, record.DeviceID)
		if err != nil && !errors.Is(err, ErrNotAssigned) {
			failures = append(failures, err)
			if record.Session == nil || record.Session.Phase != lifecycle.Stopping {
				continue
			}
		}
		if s := record.Session; s != nil {
			if _, err := h.reconciler.Reconcile(ctx, record.DeviceID, s.ID, assignment, awake); err != nil && !errors.Is(err, lifecycle.ErrStaleTarget) {
				failures = append(failures, err)
			}
		}
		if assignment.DeviceID != "" {
			failures = append(failures, h.reports.Publish(ctx, assignment, nil))
		}
	}
	return errors.Join(append(failures, h.reconciler.RepairInventory(ctx, h.records))...)
}
