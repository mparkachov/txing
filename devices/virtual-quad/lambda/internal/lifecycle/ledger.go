package lifecycle

import (
	"context"
	"crypto/rand"
	"strings"
)

const mutationAttempts = 8

type CommandRequest struct {
	ID       string
	Sequence uint32
}

// Store must return strongly consistent data. A missing row has version zero.
// CompareAndSwap creates or replaces the row only if the expected version matches.
type Store interface {
	Load(ctx context.Context, deviceID string) (Record, error)
	CompareAndSwap(ctx context.Context, version uint64, replacement Record) (bool, error)
}

type Ledger struct{ store Store }

func NewLedger(store Store) Ledger { return Ledger{store: store} }

func (l Ledger) mutate(ctx context.Context, deviceID string, change func(*Record) (bool, error)) (Record, error) {
	if deviceID == "" {
		return Record{}, ErrInvalidRequest
	}
	for attempt := 0; attempt < mutationAttempts; attempt++ {
		current, err := l.store.Load(ctx, deviceID)
		if err != nil {
			return Record{}, err
		}
		// Load returns a snapshot owned by the caller, including nested state.
		current.DeviceID = deviceID
		version := current.Version
		changed, err := change(&current)
		if err != nil || !changed {
			return current, err
		}
		current.Version++
		committed, err := l.store.CompareAndSwap(ctx, version, current)
		if err != nil {
			return Record{}, err
		}
		if committed {
			return current, nil
		}
	}
	return Record{}, ErrContention
}

func (l Ledger) Reserve(ctx context.Context, target Assignment, request CommandRequest, revision uint64, rigAwake bool, nowMS int64) (Record, Receipt, error) {
	requestID := strings.ToLower(request.ID)
	if !target.valid() || !ValidRequestID(requestID) || nowMS <= 0 {
		return Record{}, Receipt{}, ErrInvalidRequest
	}
	var result Receipt
	record, err := l.mutate(ctx, target.DeviceID, func(record *Record) (bool, error) {
		if last := record.Last; last != nil && last.Start.RequestID == requestID &&
			last.StartRevision == revision && last.Assignment == target {
			result = last.Start
			return false, nil
		}
		if revision != record.TerminalRevision {
			return false, ErrStaleTarget
		}
		if s := record.Session; s != nil {
			if s.Start.RequestID == requestID && s.Assignment == target {
				result = s.Start
				return false, nil
			}
			return false, ErrBusy
		}
		if !rigAwake {
			return false, ErrRigAsleep
		}
		result = Receipt{RequestID: requestID, Sequence: request.Sequence, REDCON: 1, Status: Accepted}
		record.Session = &Session{
			ID: rand.Text(), WorkerToken: rand.Text(), Assignment: target,
			Phase: Starting, Start: result, AcceptedAtMS: nowMS,
			StartupDeadlineMS:  nowMS + StartupTimeout.Milliseconds(),
			ShutdownDeadlineMS: nowMS + SessionLimit.Milliseconds(),
		}
		record.markAvailability(nowMS)
		return true, nil
	})
	if err != nil {
		return record, Receipt{}, err
	}
	return record, result, nil
}

func (l Ledger) BeginDispatch(ctx context.Context, deviceID, sessionID string, config LaunchConfig, nowMS int64) (Record, bool, error) {
	var dispatch bool
	record, err := l.mutate(ctx, deviceID, func(record *Record) (bool, error) {
		dispatch = false
		s := record.Session
		if s == nil || s.ID != sessionID {
			return false, ErrStaleTarget
		}
		if s.Phase != Starting || s.deadlineReason(nowMS) != "" || s.VMID != "" || nowMS < s.DispatchUntilMS {
			return false, nil
		}
		if s.Launch == nil {
			launch, err := s.launchRequest(config, nowMS)
			if err != nil {
				return false, err
			}
			s.Launch = &launch
		}
		s.LaunchAttempts++
		s.DispatchUntilMS = min(nowMS+DispatchTimeout.Milliseconds(), s.StartupDeadlineMS)
		dispatch = true
		return true, nil
	})
	return record, dispatch && err == nil, err
}

// ObserveLaunch accepts the API result even if Stop arrived while RunMicrovm
// was in flight. The stopping reservation must retain the VM ID for cleanup.
func (l Ledger) ObserveLaunch(ctx context.Context, deviceID, sessionID, vmID string) (Record, error) {
	return l.mutate(ctx, deviceID, func(record *Record) (bool, error) {
		s := record.Session
		if s == nil || s.ID != sessionID || s.Launch == nil {
			return false, ErrStaleTarget
		}
		if vmID == "" || (s.VMID != "" && s.VMID != vmID) {
			return false, ErrGrantDenied
		}
		if s.VMID == vmID {
			return false, nil
		}
		s.VMID = vmID
		return true, nil
	})
}

func (l Ledger) Claim(ctx context.Context, deviceID string, worker Worker, nowMS int64) (Record, error) {
	record, err := l.mutate(ctx, deviceID, func(record *Record) (bool, error) {
		s := record.Session
		if s == nil || s.Launch == nil ||
			!s.matchesWorker(worker) || (s.VMID != "" && s.VMID != worker.VMID) {
			return false, ErrGrantDenied
		}
		if s.Phase == Stopping || s.deadlineReason(nowMS) != "" {
			// Record the authenticated VM identity for cleanup even when its
			// Run response was lost and the worker can no longer start.
			if s.VMID == "" {
				s.VMID = worker.VMID
				return true, nil
			}
			return false, nil
		}
		if s.Claimed {
			return false, nil
		}
		s.VMID = worker.VMID
		s.Claimed = true
		return true, nil
	})
	if err == nil && !record.Session.workerGranted(worker, nowMS) {
		return record, ErrGrantDenied
	}
	return record, err
}

func (l Ledger) WorkerGrant(ctx context.Context, deviceID string, worker Worker, nowMS int64) (Record, error) {
	record, err := l.store.Load(ctx, deviceID)
	if err != nil {
		return Record{}, err
	}
	s := record.Session
	if s == nil || !s.workerGranted(worker, nowMS) {
		return record, ErrGrantDenied
	}
	return record, nil
}

func (s Session) workerGranted(worker Worker, nowMS int64) bool {
	return s.Phase != Stopping && s.deadlineReason(nowMS) == "" && s.Claimed &&
		s.VMID == worker.VMID && s.matchesWorker(worker)
}

func (l Ledger) ReportHealth(ctx context.Context, deviceID string, worker Worker, sample Health, nowMS int64) (Record, error) {
	if sample.Sequence == 0 || sample.ObservedAtMS <= nowMS-HealthTimeout.Milliseconds() ||
		sample.ObservedAtMS > nowMS+GrantInterval.Milliseconds() {
		return Record{}, ErrStaleHealth
	}
	// A small clock skew must not extend the readiness window.
	sample.ObservedAtMS = min(sample.ObservedAtMS, nowMS)
	return l.mutate(ctx, deviceID, func(record *Record) (bool, error) {
		s := record.Session
		if s == nil || !s.workerGranted(worker, nowMS) {
			return false, ErrGrantDenied
		}
		if sample.Sequence == s.Health.Sequence {
			return false, nil
		}
		if sample.Sequence < s.Health.Sequence || sample.ObservedAtMS < s.Health.ObservedAtMS {
			return false, ErrStaleHealth
		}
		before := record.Availability(nowMS)
		s.Health = sample
		ready := sample.Heartbeat && sample.Navigation && sample.Mavlink && sample.Video
		if s.Phase == Starting && ready {
			s.Phase = Operational
			s.FlightDeadlineMS = min(nowMS+FlightLimit.Milliseconds(), s.ShutdownDeadlineMS-CleanupTimeout.Milliseconds())
			s.Start.Status = Succeeded
		}
		if ready {
			s.ReadinessLostAtMS = 0
		} else if s.Phase == Operational && s.ReadinessLostAtMS == 0 {
			s.ReadinessLostAtMS = sample.ObservedAtMS
		}
		after := record.Availability(nowMS)
		if before.REDCON != after.REDCON || before.Mavlink != after.Mavlink || before.Video != after.Video {
			record.markAvailability(nowMS)
		}
		return true, nil
	})
}

func (l Ledger) RequestStop(ctx context.Context, target Assignment, request CommandRequest, sessionID string, nowMS int64) (Record, Receipt, error) {
	requestID := strings.ToLower(request.ID)
	if !target.valid() || !ValidRequestID(requestID) || sessionID == "" || nowMS <= 0 {
		return Record{}, Receipt{}, ErrInvalidRequest
	}
	var result Receipt
	record, err := l.mutate(ctx, target.DeviceID, func(record *Record) (bool, error) {
		if last := record.Last; last != nil && last.SessionID == sessionID &&
			last.Stop.RequestID == requestID && last.Assignment == target {
			result = last.Stop
			return false, nil
		}
		s := record.Session
		if s == nil || s.ID != sessionID || s.Assignment != target {
			return false, ErrStaleTarget
		}
		if s.Stop != nil {
			if s.Stop.Receipt.RequestID == requestID {
				result = s.Stop.Receipt
				return false, nil
			}
			if s.Stop.Receipt.RequestID != "" {
				return false, ErrBusy
			}
			result = Receipt{RequestID: requestID, Sequence: request.Sequence, REDCON: 4, Status: Accepted}
			s.Stop.Receipt = result
			return true, nil
		}
		result = Receipt{RequestID: requestID, Sequence: request.Sequence, REDCON: 4, Status: Accepted}
		record.beginStop(result, ReasonStopped, nowMS)
		return true, nil
	})
	if err != nil {
		return record, Receipt{}, err
	}
	return record, result, nil
}

func (l Ledger) RevokeIfDue(ctx context.Context, deviceID, sessionID string, assignment Assignment, rigAwake bool, nowMS int64) (Record, error) {
	return l.mutate(ctx, deviceID, func(record *Record) (bool, error) {
		s := record.Session
		if s == nil || s.ID != sessionID {
			return false, ErrStaleTarget
		}
		if s.Phase == Stopping {
			return false, nil
		}
		reason := s.deadlineReason(nowMS)
		if s.Assignment != assignment {
			reason = ReasonAssignment
		} else if !rigAwake {
			reason = ReasonRigSleep
		}
		if reason == "" {
			return false, nil
		}
		record.beginStop(Receipt{}, reason, nowMS)
		return true, nil
	})
}

type Termination struct {
	VMID                  string
	RejectedInitialLaunch bool
	InventoryCleared      bool
}

// Complete requires the caller's authoritative observation of a terminal VM,
// definitive launch rejection, or an empty scoped inventory after the deadline.
func (l Ledger) Complete(ctx context.Context, deviceID, sessionID string, evidence Termination, nowMS int64) (Record, error) {
	return l.mutate(ctx, deviceID, func(record *Record) (bool, error) {
		if record.Last != nil && record.Last.SessionID == sessionID {
			return false, nil
		}
		s := record.Session
		if s == nil || s.ID != sessionID {
			return false, ErrStaleTarget
		}
		if !s.confirmedTerminated(evidence, nowMS) {
			return false, ErrUnconfirmed
		}
		completion := Completion{
			SessionID: s.ID, StartRevision: record.TerminalRevision, Assignment: s.Assignment,
			Start: s.Start, Reason: ReasonUnexpectedVM, Outcome: OutcomeFailed,
		}
		if s.Stop != nil {
			completion.Reason = s.Stop.Reason
			switch completion.Reason {
			case ReasonStopped, ReasonRigSleep:
				completion.Outcome = OutcomeStopped
			case ReasonDeadline:
				completion.Outcome = OutcomeExpired
			}
			completion.Stop = s.Stop.Receipt
			if completion.Stop.RequestID != "" {
				completion.Stop.Status = Succeeded
			}
		}
		if evidence.RejectedInitialLaunch && s.Stop == nil {
			completion.Reason = "MicroVM launch rejected"
		}
		if completion.Start.Status == Accepted {
			completion.Start.Status = Failed
			completion.Start.Reason = completion.Reason
		}
		record.Session = nil
		record.Last = &completion
		record.TerminalRevision++
		record.markAvailability(nowMS)
		return true, nil
	})
}

func (s Session) confirmedTerminated(evidence Termination, nowMS int64) bool {
	if s.VMID != "" {
		return s.VMID == evidence.VMID
	}
	if evidence.VMID != "" {
		return false
	}
	if s.Launch == nil {
		return s.Phase == Stopping
	}
	// An idempotent retry could have been accepted as late as the startup
	// deadline. Allow its full pinned lifetime before clearing an unknown VM.
	latestEnd := s.StartupDeadlineMS + int64(s.Launch.MaximumDurationInSeconds)*1000 + CleanupTimeout.Milliseconds()
	return (evidence.RejectedInitialLaunch && s.LaunchAttempts == 1) ||
		(evidence.InventoryCleared && s.Phase == Stopping && nowMS >= latestEnd)
}
