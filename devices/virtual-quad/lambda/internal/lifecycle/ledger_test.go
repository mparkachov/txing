package lifecycle

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"sync"
	"testing"
)

const testNow int64 = 1794408173798

var target = Assignment{DeviceID: "virtual-quad-test", TownID: "town-test", RigID: "cloud-test"}

func requestID(i int) string { return fmt.Sprintf("00000000-0000-4000-8000-%012x", i) }

func testConfig() LaunchConfig {
	return LaunchConfig{
		ImageARN: "image", ExecutionRoleARN: "worker-role",
		IngressConnector: "NO_INGRESS", EgressConnector: "INTERNET_EGRESS",
		LogGroup: "simulator-logs", ControllerURL: "controller",
	}
}

type memoryStore struct {
	sync.Mutex
	version uint64
	data    []byte
}

func (s *memoryStore) Load(_ context.Context, _ string) (Record, error) {
	s.Lock()
	defer s.Unlock()
	var record Record
	if s.data == nil {
		return record, nil
	}
	err := json.Unmarshal(s.data, &record)
	return record, err
}

func (s *memoryStore) CompareAndSwap(_ context.Context, version uint64, replacement Record) (bool, error) {
	s.Lock()
	defer s.Unlock()
	if version != s.version {
		return false, nil
	}
	data, err := json.Marshal(replacement)
	if err != nil {
		return false, err
	}
	s.version, s.data = replacement.Version, data
	return true, nil
}

func reserve(t *testing.T, ledger Ledger, revision uint64, nowMS int64) Record {
	t.Helper()
	record, receipt, err := ledger.Reserve(t.Context(), target, CommandRequest{ID: requestID(int(revision) + 1)}, revision, true, nowMS)
	if err != nil || receipt.Status != Accepted || record.Session == nil {
		t.Fatalf("reserve: receipt=%#v error=%v", receipt, err)
	}
	return record
}

func prepare(t *testing.T, ledger Ledger, sessionID string, at int64) Record {
	t.Helper()
	record, dispatch, err := ledger.BeginDispatch(t.Context(), target.DeviceID, sessionID, testConfig(), at)
	if err != nil || !dispatch || record.Session.Launch == nil {
		t.Fatalf("prepare: dispatch=%t error=%v", dispatch, err)
	}
	return record
}

func claim(t *testing.T, ledger Ledger, record Record, at int64) Worker {
	t.Helper()
	worker := Worker{SessionID: record.Session.ID, VMID: "microvm-test", Token: record.Session.WorkerToken}
	if _, err := ledger.Claim(t.Context(), target.DeviceID, worker, at); err != nil {
		t.Fatal(err)
	}
	return worker
}

func TestConcurrentStartsReserveOneSession(t *testing.T) {
	ledger := NewLedger(&memoryStore{})
	const callers = 32
	begin := make(chan struct{})
	type result struct {
		id     string
		record Record
		err    error
	}
	results := make(chan result, callers)
	for i := 0; i < callers; i++ {
		go func(id string) {
			<-begin
			record, _, err := ledger.Reserve(t.Context(), target, CommandRequest{ID: id}, 0, true, testNow)
			results <- result{id, record, err}
		}(requestID(i))
	}
	close(begin)
	var winner result
	accepted := 0
	for i := 0; i < callers; i++ {
		res := <-results
		if res.err == nil {
			accepted++
			winner = res
		} else if !errors.Is(res.err, ErrBusy) {
			t.Fatalf("unexpected error: %v", res.err)
		}
	}
	if accepted != 1 {
		t.Fatalf("accepted %d starts", accepted)
	}
	replay, receipt, err := ledger.Reserve(t.Context(), target, CommandRequest{ID: winner.id}, 0, true, testNow+1000)
	if err != nil || replay.Session.ID != winner.record.Session.ID || replay.Version != 1 || receipt.Status != Accepted {
		t.Fatalf("duplicate start changed the reservation: receipt=%#v err=%v", receipt, err)
	}
}

func TestLaunchRetryKeepsExactInputsAndWorkerClaim(t *testing.T) {
	ledger := NewLedger(&memoryStore{})
	start := reserve(t, ledger, 0, testNow)
	first := prepare(t, ledger, start.Session.ID, testNow+2500)
	if first.Session.Launch.ClientToken != start.Session.ID || first.Session.Launch.MaximumDurationInSeconds != 837 {
		t.Fatal("launch token or absolute duration differs from the reservation")
	}
	if inflight, dispatch, err := ledger.BeginDispatch(t.Context(), target.DeviceID, start.Session.ID, testConfig(), testNow+3000); err != nil || dispatch || inflight.Version != first.Version {
		t.Fatalf("overlapping dispatch acquired a lease: %t %v", dispatch, err)
	}
	config := testConfig()
	config.LogGroup = "new-log-group"
	retry, dispatch, err := ledger.BeginDispatch(t.Context(), target.DeviceID, start.Session.ID, config, testNow+20000)
	if err != nil || !dispatch || *retry.Session.Launch != *first.Session.Launch || retry.Version != first.Version+1 || retry.Session.LaunchAttempts != 2 {
		t.Fatalf("launch retry changed persisted inputs: dispatch=%t error=%v", dispatch, err)
	}
	var payload WorkerPayload
	if err := json.Unmarshal([]byte(first.Session.Launch.RunHookPayload), &payload); err != nil ||
		payload.Assignment != target || payload.SessionID != start.Session.ID || payload.WorkerToken != start.Session.WorkerToken {
		t.Fatalf("wrong worker payload: %v", err)
	}
	bad := Worker{SessionID: start.Session.ID, VMID: "microvm-unknown", Token: "wrong"}
	if _, err := ledger.Claim(t.Context(), target.DeviceID, bad, testNow+25000); !errors.Is(err, ErrGrantDenied) {
		t.Fatalf("invalid worker token was accepted: %v", err)
	}
	worker := claim(t, ledger, start, testNow+25000)
	bad.Token = start.Session.WorkerToken
	if _, err := ledger.Claim(t.Context(), target.DeviceID, bad, testNow+26000); !errors.Is(err, ErrGrantDenied) {
		t.Fatalf("second worker was accepted: %v", err)
	}
	observed, err := ledger.ObserveLaunch(t.Context(), target.DeviceID, start.Session.ID, worker.VMID)
	if err != nil || observed.Session.VMID != worker.VMID || !observed.Session.Claimed {
		t.Fatalf("matching late API result was rejected: %v", err)
	}
}

func TestStopDuringDispatchFencesWorkerAndRestart(t *testing.T) {
	ledger := NewLedger(&memoryStore{})
	start := reserve(t, ledger, 0, testNow)
	prepare(t, ledger, start.Session.ID, testNow)
	stopAt := testNow + 1500
	stop, receipt, err := ledger.RequestStop(t.Context(), target, CommandRequest{ID: requestID(42)}, start.Session.ID, stopAt)
	if err != nil || receipt.Status != Accepted || stop.Session.Phase != Stopping || stop.Availability(stopAt).REDCON != 3 {
		t.Fatalf("stop: receipt=%#v err=%v", receipt, err)
	}
	if _, dispatch, err := ledger.BeginDispatch(t.Context(), target.DeviceID, start.Session.ID, testConfig(), stopAt); err != nil || dispatch {
		t.Fatalf("stopping reservation still dispatches: %t %v", dispatch, err)
	}
	worker := Worker{SessionID: start.Session.ID, VMID: "microvm-late", Token: start.Session.WorkerToken}
	if _, err := ledger.Claim(t.Context(), target.DeviceID, worker, stopAt); !errors.Is(err, ErrGrantDenied) {
		t.Fatalf("late worker claim was accepted: %v", err)
	}
	if _, err := ledger.Complete(t.Context(), target.DeviceID, start.Session.ID, Termination{InventoryCleared: true}, stopAt); !errors.Is(err, ErrUnconfirmed) {
		t.Fatalf("an empty early inventory released a pending dispatch: %v", err)
	}
	if _, err := ledger.ObserveLaunch(t.Context(), target.DeviceID, start.Session.ID, worker.VMID); err != nil {
		t.Fatal(err)
	}
	if _, err := ledger.Complete(t.Context(), target.DeviceID, start.Session.ID, Termination{VMID: "microvm-other"}, stopAt); !errors.Is(err, ErrUnconfirmed) {
		t.Fatalf("mismatched termination released the reservation: %v", err)
	}
	ended, err := ledger.Complete(t.Context(), target.DeviceID, start.Session.ID, Termination{VMID: worker.VMID}, stopAt+1000)
	if err != nil || ended.Session != nil || ended.TerminalRevision != 1 || ended.Last.Start.Status != Failed || ended.Last.Stop.Status != Succeeded {
		t.Fatalf("unexpected completed record: %#v error=%v", ended, err)
	}
	if _, _, err := ledger.Reserve(t.Context(), target, CommandRequest{ID: requestID(99)}, 0, true, stopAt+1000); !errors.Is(err, ErrStaleTarget) {
		t.Fatalf("stale start accepted: %v", err)
	}
	next := reserve(t, ledger, 1, stopAt+2000)
	if next.Session.ID == start.Session.ID || next.Session.WorkerToken == start.Session.WorkerToken {
		t.Fatal("restart reused a session identity or worker token")
	}
	if _, _, err := ledger.RequestStop(t.Context(), target, CommandRequest{ID: requestID(43)}, start.Session.ID, stopAt+3000); !errors.Is(err, ErrStaleTarget) {
		t.Fatalf("old stop affected the new generation: %v", err)
	}
	replay, receipt, err := ledger.RequestStop(t.Context(), target, CommandRequest{ID: requestID(42)}, start.Session.ID, stopAt+3000)
	if err != nil || receipt.Status != Succeeded || replay.Session.ID != next.Session.ID || replay.Version != next.Version {
		t.Fatalf("old stop replay lost its receipt: %#v %v", receipt, err)
	}

	prepare(t, ledger, next.Session.ID, stopAt+3000)
	currentWorker := claim(t, ledger, next, stopAt+4000)
	at := stopAt + 5000
	late := Health{Sequence: 1, ObservedAtMS: at, Heartbeat: true, Navigation: true, Mavlink: true, Video: true}
	if _, err := ledger.ReportHealth(t.Context(), target.DeviceID, worker, late, at); !errors.Is(err, ErrGrantDenied) {
		t.Fatalf("retired worker reported readiness after restart: %v", err)
	}
	current, err := ledger.WorkerGrant(t.Context(), target.DeviceID, currentWorker, at)
	if err != nil || current.Session.Phase != Starting || current.Availability(at).REDCON != 3 {
		t.Fatalf("retired health changed replacement availability: %v", err)
	}
}

func TestReadinessUsesFreshEvidenceAndBoundedDeadlines(t *testing.T) {
	ledger := NewLedger(&memoryStore{})
	start := reserve(t, ledger, 0, testNow)
	prepare(t, ledger, start.Session.ID, testNow)
	worker := claim(t, ledger, start, testNow+1000)
	at := testNow + 45000
	partial := Health{Sequence: 1, ObservedAtMS: at, Heartbeat: true, Mavlink: true}
	step, err := ledger.ReportHealth(t.Context(), target.DeviceID, worker, partial, at)
	if err != nil || step.Session.Phase != Starting || step.Availability(at).REDCON != 2 || step.Availability(at).Video {
		t.Fatalf("bad partial readiness: %v", err)
	}
	projected, err := ledger.PrepareProjection(t.Context(), target.DeviceID, nil, at, 0)
	if err != nil || projected.Projection.Agent {
		t.Fatalf("partial readiness enabled the observer: %v", err)
	}
	at += 5000
	full := Health{Sequence: 2, ObservedAtMS: at, Heartbeat: true, Navigation: true, Mavlink: true, Video: true}
	step, err = ledger.ReportHealth(t.Context(), target.DeviceID, worker, full, at)
	if err != nil || step.Session.Phase != Operational || step.Availability(at).REDCON != 1 || step.Session.Start.Status != Succeeded {
		t.Fatalf("bad full readiness: %v", err)
	}
	projected, err = ledger.PrepareProjection(t.Context(), target.DeviceID, nil, at, 0)
	if err != nil || !projected.Projection.Agent {
		t.Fatalf("full readiness did not enable the observer: %v", err)
	}
	if step.Session.FlightDeadlineMS != at+FlightLimit.Milliseconds() || step.Session.ShutdownDeadlineMS != testNow+SessionLimit.Milliseconds() {
		t.Fatal("flight or absolute deadline changed unexpectedly")
	}
	if _, err := ledger.ReportHealth(t.Context(), target.DeviceID, worker, partial, at); !errors.Is(err, ErrStaleHealth) {
		t.Fatalf("out-of-order health report was accepted: %v", err)
	}
	expiry := at + HealthTimeout.Milliseconds()
	if step.Availability(expiry-1).REDCON != 1 || step.Availability(expiry).REDCON != 3 {
		t.Fatal("readiness did not expire at exactly fifteen seconds")
	}
	if _, err := ledger.WorkerGrant(t.Context(), target.DeviceID, worker, expiry); !errors.Is(err, ErrGrantDenied) {
		t.Fatalf("expired worker still has a grant: %v", err)
	}
	stopped, err := ledger.RevokeIfDue(t.Context(), target.DeviceID, start.Session.ID, target, true, expiry)
	if err != nil || stopped.Session.Phase != Stopping || stopped.Session.Stop.Reason != ReasonHealth || stopped.AvailabilityWatermarkMS != expiry {
		t.Fatalf("repair did not revoke expired readiness: %v", err)
	}
	projected, err = ledger.PrepareProjection(t.Context(), target.DeviceID, nil, expiry, 0)
	if err != nil || projected.Projection.Agent {
		t.Fatalf("expired readiness enabled the observer: %v", err)
	}
}

func TestMediaReconnectKeepsSessionWhileSITLIsHealthy(t *testing.T) {
	ledger := NewLedger(&memoryStore{})
	start := reserve(t, ledger, 0, testNow)
	prepare(t, ledger, start.Session.ID, testNow)
	worker := claim(t, ledger, start, testNow+1000)
	at := testNow + 45000
	var sequence uint64
	report := func(heartbeat, navigation, media bool) Record {
		t.Helper()
		sequence++
		sample := Health{
			Sequence: sequence, ObservedAtMS: at, Heartbeat: heartbeat,
			Navigation: navigation, Mavlink: media, Video: media,
		}
		record, err := ledger.ReportHealth(t.Context(), target.DeviceID, worker, sample, at)
		if err != nil {
			t.Fatalf("report health at %d: %v", at, err)
		}
		at += HealthInterval.Milliseconds()
		return record
	}
	operational := report(true, true, true)
	for range 4 {
		degraded := report(true, true, false)
		availability := degraded.Availability(at - HealthInterval.Milliseconds())
		if availability.REDCON != 3 || availability.Mavlink || availability.Video || degraded.Session.Phase != Operational {
			t.Fatalf("KVS loss did not withdraw readiness during recovery: %+v", availability)
		}
	}
	recovered := report(true, true, true)
	if recovered.Availability(at-HealthInterval.Milliseconds()).REDCON != 1 ||
		recovered.Session.ID != operational.Session.ID || recovered.Session.FlightDeadlineMS != operational.Session.FlightDeadlineMS {
		t.Fatal("KVS recovery did not restore readiness for the same session and deadline")
	}

	for range MediaRecoveryTimeout / HealthInterval {
		report(true, true, false)
	}
	if _, err := ledger.WorkerGrant(t.Context(), target.DeviceID, worker, at); !errors.Is(err, ErrGrantDenied) {
		t.Fatalf("persistent KVS outage retained the grant: %v", err)
	}
}

func TestStartupDeadlineAndRigSleep(t *testing.T) {
	ledger := NewLedger(&memoryStore{})
	if _, _, err := ledger.Reserve(t.Context(), target, CommandRequest{ID: requestID(1)}, 0, false, testNow); !errors.Is(err, ErrRigAsleep) {
		t.Fatalf("asleep rig accepted a start: %v", err)
	}
	start := reserve(t, ledger, 0, testNow)
	deadline := testNow + StartupTimeout.Milliseconds()
	if _, dispatch, err := ledger.BeginDispatch(t.Context(), target.DeviceID, start.Session.ID, testConfig(), deadline); err != nil || dispatch {
		t.Fatalf("launch dispatched past the startup cutoff: %t %v", dispatch, err)
	}
	stopped, err := ledger.RevokeIfDue(t.Context(), target.DeviceID, start.Session.ID, target, true, deadline)
	if err != nil || stopped.Session.Stop.Reason != ReasonStartup {
		t.Fatalf("startup timeout did not revoke the reservation: %v", err)
	}
	ended, err := ledger.Complete(t.Context(), target.DeviceID, start.Session.ID, Termination{}, deadline)
	if err != nil || ended.Session != nil || ended.Last.Outcome != OutcomeFailed {
		t.Fatalf("undispatched timed-out reservation did not end: %v", err)
	}
}
