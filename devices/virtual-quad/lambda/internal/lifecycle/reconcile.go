package lifecycle

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/aws/aws-sdk-go-v2/service/lambdamicrovms/types"
)

var errLaunchUnconfirmed = errors.New("MicroVM launch result is unconfirmed")

type Reconciler struct {
	ledger   Ledger
	platform MicroVMs
	launch   LaunchConfig
	now      func() time.Time
}

func NewReconciler(ledger Ledger, platform MicroVMs, launch LaunchConfig) Reconciler {
	return Reconciler{ledger: ledger, platform: platform, launch: launch, now: time.Now}
}

// ReconcileStart gives an ambiguous launch an early replay while the
// startup budget still leaves time for the simulator to become ready.
func (r Reconciler) ReconcileStart(ctx context.Context, assignment Assignment, sessionID string, rigAwake bool) (Record, error) {
	const maxAttempts = 3
	for attempt := 1; ; attempt++ {
		record, err := r.Reconcile(ctx, assignment.DeviceID, sessionID, assignment, rigAwake)
		if errors.Is(err, ErrStaleTarget) {
			return record, nil
		}
		s := record.Session
		if !errors.Is(err, errLaunchUnconfirmed) || s == nil || attempt == maxAttempts ||
			s.DispatchUntilMS >= s.StartupDeadlineMS {
			return record, err
		}
		wait := time.Duration(s.DispatchUntilMS-r.now().UnixMilli()) * time.Millisecond
		timer := time.NewTimer(wait)
		select {
		case <-ctx.Done():
			timer.Stop()
			return record, errors.Join(err, ctx.Err())
		case <-timer.C:
		}
	}
}

// ReconcileStop observes the terminal state within the current Stop budget.
// The independent repair pass can resume any reservation still unresolved.
func (r Reconciler) ReconcileStop(ctx context.Context, record Record) (Record, error) {
	s := record.Session
	if s == nil || s.Phase != Stopping || s.Stop == nil {
		return record, ErrInvalidRequest
	}
	remaining := time.Duration(s.Stop.DeadlineMS-r.now().UnixMilli()) * time.Millisecond
	if remaining <= 0 {
		return r.Reconcile(ctx, record.DeviceID, s.ID, s.Assignment, true)
	}
	stopCtx, cancel := context.WithTimeout(ctx, remaining)
	defer cancel()
	poll := time.NewTicker(time.Second)
	defer poll.Stop()
	for {
		current, err := r.Reconcile(stopCtx, record.DeviceID, s.ID, s.Assignment, true)
		if errors.Is(err, ErrStaleTarget) || (err == nil && current.Session == nil) {
			return current, nil
		}
		if stopCtx.Err() != nil {
			return current, errors.Join(ErrUnconfirmed, err)
		}
		if err != nil && !errors.Is(err, errRetryVMState) {
			return current, err
		}
		select {
		case <-stopCtx.Done():
			return current, errors.Join(ErrUnconfirmed, err)
		case <-poll.C:
		}
	}
}

// Reconcile advances one current reservation using the caller's verified rig
// assignment and awake state. A later repair invocation can repeat it safely.
func (r Reconciler) Reconcile(ctx context.Context, deviceID, sessionID string, assignment Assignment, rigAwake bool) (Record, error) {
	record, err := r.ledger.RevokeIfDue(ctx, deviceID, sessionID, assignment, rigAwake, r.now().UnixMilli())
	if err != nil {
		return record, err
	}
	session := record.Session
	if session.VMID != "" {
		return r.observeVM(ctx, record)
	}
	if session.Phase == Stopping {
		if session.Launch == nil {
			return r.ledger.Complete(ctx, deviceID, sessionID, Termination{}, r.now().UnixMilli())
		}
		return record, nil // Await the in-flight response, worker identity, or inventory repair.
	}
	prepared, dispatch, err := r.ledger.BeginDispatch(ctx, deviceID, sessionID, r.launch, r.now().UnixMilli())
	if err != nil || !dispatch {
		return prepared, err
	}
	return r.dispatch(ctx, prepared)
}

func (r Reconciler) dispatch(ctx context.Context, record Record) (Record, error) {
	session := record.Session
	remaining := time.Duration(session.DispatchUntilMS-r.now().UnixMilli()) * time.Millisecond
	if remaining <= 0 {
		return record, nil
	}
	launchCtx, cancel := context.WithTimeout(ctx, remaining)
	vmID, err := r.platform.Run(launchCtx, *session.Launch)
	cancel()
	if err != nil {
		if errors.Is(err, ErrLaunchRejected) && session.LaunchAttempts == 1 {
			return r.ledger.Complete(ctx, record.DeviceID, session.ID, Termination{RejectedInitialLaunch: true}, r.now().UnixMilli())
		}
		if !errors.Is(err, ErrLaunchRejected) {
			return record, errors.Join(errLaunchUnconfirmed, err)
		}
		return record, err
	}
	observed, err := r.ledger.ObserveLaunch(ctx, record.DeviceID, session.ID, vmID)
	if err != nil {
		return observed, err
	}
	if observed.Session.Phase == Stopping {
		return r.observeVM(ctx, observed)
	}
	return observed, nil
}

func (r Reconciler) observeVM(ctx context.Context, record Record) (Record, error) {
	session := record.Session
	if session.Launch == nil {
		return record, errors.New("MicroVM reservation is missing its launch request")
	}
	vm, err := r.platform.Get(ctx, session.VMID)
	if err != nil {
		return record, err
	}
	if vm.ID != session.VMID || vm.ImageARN != session.Launch.ImageARN ||
		(session.Launch.ImageVersion != "" && vm.ImageVersion != session.Launch.ImageVersion) {
		return record, errors.New("MicroVM identity or image differs from its reservation")
	}
	if vm.State == types.MicrovmStateTerminated {
		return r.ledger.Complete(ctx, record.DeviceID, session.ID, Termination{VMID: vm.ID}, r.now().UnixMilli())
	}
	if session.Phase != Stopping || vm.State == types.MicrovmStateTerminating {
		return record, nil
	}
	if !canTerminate(vm.State) {
		return record, fmt.Errorf("unexpected MicroVM state %q", vm.State)
	}
	return record, r.platform.Terminate(ctx, vm.ID)
}

func canTerminate(state types.MicrovmState) bool {
	switch state {
	case types.MicrovmStatePending, types.MicrovmStateRunning, types.MicrovmStateSuspended, types.MicrovmStateSuspending:
		return true
	default:
		return false
	}
}

type RecordInventory interface {
	Records(context.Context) ([]Record, error)
}

// RepairInventory looks only at the simulator images owned by this controller.
// Known VMs are reconciled independently through Get, even if List omits them.
func (r Reconciler) RepairInventory(ctx context.Context, source RecordInventory) error {
	records, err := source.Records(ctx)
	if err != nil {
		return err
	}
	images := map[string]bool{r.launch.ImageARN: true}
	for _, record := range records {
		if s := record.Session; s != nil && s.Launch != nil {
			images[s.Launch.ImageARN] = true
		}
	}
	inventories := make(map[string][]MicroVM, len(images))
	var failures []error
	for image := range images {
		vms, err := r.platform.Inventory(ctx, image)
		if err != nil {
			failures = append(failures, err)
			continue
		}
		inventories[image] = vms
	}
	// Read the record again after listing VMs, to see any late claim or Run
	// response that persisted the VM's identity during the inventory call.
	checkedAt := r.now()
	records, err = source.Records(ctx)
	if err != nil {
		return errors.Join(append(failures, err)...)
	}
	known := map[string]bool{}
	for _, record := range records {
		if s := record.Session; s != nil && s.VMID != "" {
			known[s.VMID] = true
		}
	}
	clear := make(map[string]bool, len(inventories))
	for image, vms := range inventories {
		clear[image] = true
		seen := map[string]bool{}
		for _, vm := range vms {
			if vm.ImageARN != image || vm.ID == "" {
				clear[image] = false
				failures = append(failures, errors.New("invalid MicroVM inventory identity"))
				continue
			}
			if vm.State == types.MicrovmStateTerminated || known[vm.ID] {
				continue
			}
			clear[image] = false
			if seen[vm.ID] {
				continue
			}
			seen[vm.ID] = true
			if err := r.stopUnassigned(ctx, vm, checkedAt); err != nil {
				failures = append(failures, err)
			}
		}
	}
	for _, record := range records {
		s := record.Session
		if s == nil || s.Phase != Stopping || s.VMID != "" || s.Launch == nil || !clear[s.Launch.ImageARN] {
			continue
		}
		_, err := r.ledger.Complete(ctx, record.DeviceID, s.ID, Termination{InventoryCleared: true}, r.now().UnixMilli())
		if err != nil && !errors.Is(err, ErrUnconfirmed) && !errors.Is(err, ErrStaleTarget) {
			failures = append(failures, err)
		}
	}
	return errors.Join(failures...)
}

func (r Reconciler) stopUnassigned(ctx context.Context, listed MicroVM, checkedAt time.Time) error {
	// A VM can still announce a valid claim within its startup window. VM
	// creation follows reservation, so this VM's age bounds that window.
	const grace = StartupTimeout + DispatchTimeout
	if !canTerminate(listed.State) || listed.StartedAt.IsZero() || checkedAt.Sub(listed.StartedAt) < grace {
		return nil
	}
	current, err := r.platform.Get(ctx, listed.ID)
	if err != nil {
		return err
	}
	if current.ID != listed.ID || current.ImageARN != listed.ImageARN || current.ImageVersion != listed.ImageVersion {
		return errors.New("unassigned MicroVM identity changed during repair")
	}
	if !canTerminate(current.State) || current.StartedAt.IsZero() || checkedAt.Sub(current.StartedAt) < grace {
		return nil
	}
	return r.platform.Terminate(ctx, current.ID)
}
