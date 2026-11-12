package lifecycle

import (
	"context"
	"errors"
	"reflect"
	"testing"
	"time"

	"github.com/aws/aws-sdk-go-v2/service/lambdamicrovms/types"
)

type fakeMicroVMs struct {
	run        func() (string, error)
	launches   []Launch
	vms        map[string]MicroVM
	listed     []MicroVM
	images     []string
	terminated []string
}

func (f *fakeMicroVMs) Run(_ context.Context, launch Launch) (string, error) {
	f.launches = append(f.launches, launch)
	return f.run()
}

func (f *fakeMicroVMs) Get(_ context.Context, id string) (MicroVM, error) {
	vm, found := f.vms[id]
	if !found {
		return MicroVM{}, errors.New("VM missing")
	}
	return vm, nil
}

func (f *fakeMicroVMs) Terminate(_ context.Context, id string) error {
	f.terminated = append(f.terminated, id)
	vm := f.vms[id]
	vm.State = types.MicrovmStateTerminating
	f.vms[id] = vm
	return nil
}

func (f *fakeMicroVMs) Inventory(_ context.Context, image string) ([]MicroVM, error) {
	f.images = append(f.images, image)
	return f.listed, nil
}

func TestReconcileAmbiguousLaunchKeepsReservationAndPinnedRequest(t *testing.T) {
	ledger := NewLedger(&memoryStore{})
	started := reserve(t, ledger, 0, testNow)
	platform := &fakeMicroVMs{run: func() (string, error) { return "", context.DeadlineExceeded }}
	reconciler := NewReconciler(ledger, platform, testConfig())
	now := time.UnixMilli(testNow)
	reconciler.now = func() time.Time { return now }
	reconcile := func() (Record, error) {
		return reconciler.Reconcile(t.Context(), target.DeviceID, started.Session.ID, target, true)
	}
	if record, err := reconcile(); !errors.Is(err, context.DeadlineExceeded) || record.Session.LaunchAttempts != 1 {
		t.Fatalf("ambiguous initial launch lost the reservation: %v", err)
	}
	if _, err := reconcile(); err != nil || len(platform.launches) != 1 {
		t.Fatalf("a duplicate dispatched before the previous window closed: %v", err)
	}
	now = now.Add(DispatchTimeout)
	platform.run = func() (string, error) { return "", ErrLaunchRejected }
	reconciler.launch.ImageVersion = "3.0"
	if record, err := reconcile(); !errors.Is(err, ErrLaunchRejected) || record.Session == nil || record.Session.LaunchAttempts != 2 {
		t.Fatalf("a rejection after an ambiguous dispatch released the reservation: %v", err)
	}
	now = now.Add(DispatchTimeout)
	platform.run = func() (string, error) { return "microvm-assigned", nil }
	if record, err := reconcile(); err != nil || record.Session.VMID != "microvm-assigned" {
		t.Fatalf("recovery did not persist the returned VM: %v", err)
	}
	if len(platform.launches) != 3 || platform.launches[0] != platform.launches[1] || platform.launches[0] != platform.launches[2] {
		t.Fatal("recovery changed the idempotent launch request")
	}
}

func TestReconcileInitialRejectionReleasesReservation(t *testing.T) {
	ledger := NewLedger(&memoryStore{})
	started := reserve(t, ledger, 0, testNow)
	platform := &fakeMicroVMs{run: func() (string, error) { return "", ErrLaunchRejected }}
	reconciler := NewReconciler(ledger, platform, testConfig())
	reconciler.now = func() time.Time { return time.UnixMilli(testNow) }
	record, err := reconciler.Reconcile(t.Context(), target.DeviceID, started.Session.ID, target, true)
	if err != nil || record.Session != nil || record.Last.Outcome != OutcomeFailed || record.TerminalRevision != 1 {
		t.Fatalf("definitive first rejection did not close the reservation: %v", err)
	}
}

func TestStartReplaysAmbiguousLaunchBeforeScheduledRepair(t *testing.T) {
	for _, stopDuringLaunch := range []bool{false, true} {
		name := "retry"
		if stopDuringLaunch {
			name = "stop"
		}
		t.Run(name, func(t *testing.T) {
			ledger := NewLedger(&memoryStore{})
			started := reserve(t, ledger, 0, testNow)
			platform := &fakeMicroVMs{}
			reconciler := NewReconciler(ledger, platform, testConfig())
			now := time.UnixMilli(testNow)
			reconciler.now = func() time.Time { return now }
			platform.run = func() (string, error) {
				if len(platform.launches) > 1 {
					return "microvm-recovered", nil
				}
				if stopDuringLaunch {
					_, _, err := ledger.RequestStop(t.Context(), target,
						CommandRequest{ID: requestID(42)}, started.Session.ID, now.UnixMilli())
					if err != nil {
						t.Fatal(err)
					}
				}
				now = now.Add(DispatchTimeout)
				return "", context.DeadlineExceeded
			}
			record, err := reconciler.ReconcileStart(t.Context(), target, started.Session.ID, true)
			if err != nil || record.Session == nil {
				t.Fatalf("failed to reconcile Start after losing the launch response: %v", err)
			}
			if stopDuringLaunch {
				if len(platform.launches) != 1 || record.Session.Phase != Stopping {
					t.Fatal("retried a launch after Stop")
				}
			} else if len(platform.launches) != 2 || platform.launches[0] != platform.launches[1] ||
				record.Session.VMID != "microvm-recovered" {
				t.Fatal("Start did not recover using the original launch inputs")
			}
		})
	}
}

func TestReconcileTerminatesVMReturnedAfterStop(t *testing.T) {
	ledger := NewLedger(&memoryStore{})
	started := reserve(t, ledger, 0, testNow)
	vm := MicroVM{ID: "microvm-late", ImageARN: testConfig().ImageARN, ImageVersion: testConfig().ImageVersion, State: types.MicrovmStatePending}
	platform := &fakeMicroVMs{vms: map[string]MicroVM{vm.ID: vm}}
	platform.run = func() (string, error) {
		if _, _, err := ledger.RequestStop(t.Context(), target, CommandRequest{ID: requestID(40)}, started.Session.ID, testNow); err != nil {
			t.Fatal(err)
		}
		return vm.ID, nil
	}
	reconciler := NewReconciler(ledger, platform, testConfig())
	reconciler.now = func() time.Time { return time.UnixMilli(testNow) }
	for i := 0; i < 2; i++ {
		record, err := reconciler.Reconcile(t.Context(), target.DeviceID, started.Session.ID, target, true)
		if err != nil || record.Session.Phase != Stopping || record.TerminalRevision != 0 {
			t.Fatalf("termination request became terminal evidence: %v", err)
		}
	}
	if !reflect.DeepEqual(platform.terminated, []string{vm.ID}) {
		t.Fatalf("expected one terminate request, got %v", platform.terminated)
	}
	vm.State = types.MicrovmStateTerminated
	platform.vms[vm.ID] = vm
	record, err := reconciler.Reconcile(t.Context(), target.DeviceID, started.Session.ID, target, true)
	if err != nil || record.Session != nil || record.Last.Stop.Status != Succeeded {
		t.Fatalf("terminal observation did not close Stop: %v", err)
	}
}

type recordsFunc func(context.Context) ([]Record, error)

func (f recordsFunc) Records(ctx context.Context) ([]Record, error) { return f(ctx) }

func TestInventoryProtectsRecentAndNewlyClaimedVMs(t *testing.T) {
	now := time.UnixMilli(testNow)
	image := testConfig().ImageARN
	old := MicroVM{ID: "microvm-old", ImageARN: image, ImageVersion: "2.0", State: types.MicrovmStateRunning, StartedAt: now.Add(-2 * time.Minute)}
	claimed, recent := old, old
	claimed.ID = "microvm-claimed"
	recent.ID, recent.StartedAt = "microvm-new", now.Add(-30*time.Second)
	platform := &fakeMicroVMs{
		listed: []MicroVM{claimed, recent, old, old},
		vms:    map[string]MicroVM{old.ID: old, recent.ID: recent, claimed.ID: claimed},
	}
	reconciler := NewReconciler(NewLedger(&memoryStore{}), platform, testConfig())
	reconciler.now = func() time.Time { return now }
	reads := 0
	if err := reconciler.RepairInventory(t.Context(), recordsFunc(func(context.Context) ([]Record, error) {
		reads++
		if reads == 1 {
			return nil, nil
		}
		return []Record{{Session: &Session{VMID: claimed.ID}}}, nil
	})); err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(platform.images, []string{image}) || !reflect.DeepEqual(platform.terminated, []string{old.ID}) {
		t.Fatalf("wrong inventory scope or termination targets: images=%v terminated=%v", platform.images, platform.terminated)
	}
}

func TestInventoryRequiresAnAuthoritativeAssignmentRead(t *testing.T) {
	platform := &fakeMicroVMs{}
	reconciler := NewReconciler(NewLedger(&memoryStore{}), platform, testConfig())
	readFailed := errors.New("session read failed")
	reads := 0
	err := reconciler.RepairInventory(t.Context(), recordsFunc(func(context.Context) ([]Record, error) {
		reads++
		if reads == 1 {
			return nil, nil
		}
		return nil, readFailed
	}))
	if !errors.Is(err, readFailed) || len(platform.terminated) != 0 {
		t.Fatalf("incomplete assignment scan was treated as authoritative: %v", err)
	}
}
