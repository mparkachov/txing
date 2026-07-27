package thread

import (
	"context"
	"sync"
	"testing"
	"time"

	"github.com/mparkachov/txing/rig/internal/protocol"
)

func TestSchedulerPrioritizesCommandOverInFlightMaintenancePoll(t *testing.T) {
	client := &blockingMaintenanceClient{
		getStarted:  make(chan struct{}),
		getCanceled: make(chan struct{}),
		secondGet:   make(chan struct{}),
		putStarted:  make(chan struct{}),
	}
	runtime := schedulerRuntime(t, client)
	scheduler := NewScheduler(runtime, 4)
	scheduler.Start(context.Background())
	defer scheduler.Close()

	scheduler.RequestMaintenance()
	waitForSignal(t, client.getStarted, "maintenance GET start")

	command := schedulerCommand(t, "command-priority", 3)
	if err := scheduler.SubmitCommand(command); err != nil {
		t.Fatal(err)
	}
	waitForSignal(t, client.getCanceled, "maintenance GET cancellation")
	waitForSignal(t, client.putStarted, "command PUT start")

	// The cancelled maintenance cycle finishes before a new one may start. A
	// subsequent tick must still restore periodic state maintenance.
	deadline := time.After(2 * time.Second)
	for {
		scheduler.RequestMaintenance()
		select {
		case <-client.secondGet:
			return
		case <-deadline:
			t.Fatal("maintenance did not recover after prioritized command")
		case <-time.After(5 * time.Millisecond):
		}
	}
}

func TestSchedulerCoalescesOverlappingMaintenanceRequests(t *testing.T) {
	discoverer := &countingDiscoverer{endpoints: []Endpoint{testEndpoint("power-si-001")}}
	client := &blockingMaintenanceClient{
		getStarted:  make(chan struct{}),
		getCanceled: make(chan struct{}),
		secondGet:   make(chan struct{}),
		putStarted:  make(chan struct{}),
	}
	runtime := NewRuntime(discoverer, client, &recordingPublisher{})
	runtime.ReconcileInventory(testInventory())
	scheduler := NewScheduler(runtime, 4)
	scheduler.Start(context.Background())
	defer scheduler.Close()

	scheduler.RequestMaintenance()
	waitForSignal(t, client.getStarted, "first maintenance GET")
	for range 8 {
		scheduler.RequestMaintenance()
	}
	if calls := discoverer.callsMade(); calls != 1 {
		t.Fatalf("discover calls = %d, want one coalesced maintenance cycle", calls)
	}
}

func TestSchedulerSerializesCommandsForEachDevice(t *testing.T) {
	client := &orderedCommandClient{firstStarted: make(chan struct{}), allowFirst: make(chan struct{}), secondStarted: make(chan struct{})}
	runtime := schedulerRuntime(t, client)
	scheduler := NewScheduler(runtime, 4)
	scheduler.Start(context.Background())
	defer scheduler.Close()

	if err := scheduler.SubmitCommand(schedulerCommand(t, "command-four", 4)); err != nil {
		t.Fatal(err)
	}
	if err := scheduler.SubmitCommand(schedulerCommand(t, "command-three", 3)); err != nil {
		t.Fatal(err)
	}
	waitForSignal(t, client.firstStarted, "first command")

	select {
	case <-client.secondStarted:
		t.Fatal("second command started before the first command completed")
	default:
	}
	close(client.allowFirst)
	waitForSignal(t, client.secondStarted, "second command")

	if targets := client.commandTargets(); len(targets) != 2 || targets[0] != 4 || targets[1] != 3 {
		t.Fatalf("command targets = %#v, want [4 3]", targets)
	}
}

func TestSchedulerCloseCancelsMaintenanceAndWaitsForWorkers(t *testing.T) {
	client := &blockingMaintenanceClient{
		getStarted:  make(chan struct{}),
		getCanceled: make(chan struct{}),
		secondGet:   make(chan struct{}),
		putStarted:  make(chan struct{}),
	}
	runtime := schedulerRuntime(t, client)
	scheduler := NewScheduler(runtime, 2)
	scheduler.Start(context.Background())
	scheduler.RequestMaintenance()
	waitForSignal(t, client.getStarted, "maintenance GET start")

	closed := make(chan struct{})
	go func() {
		scheduler.Close()
		close(closed)
	}()
	waitForSignal(t, client.getCanceled, "maintenance GET cancellation on shutdown")
	waitForSignal(t, closed, "scheduler shutdown")
}

func schedulerRuntime(t *testing.T, client DeviceClient) *Runtime {
	t.Helper()
	publisher := &recordingPublisher{}
	runtime := NewRuntime(&fakeDiscoverer{endpoints: []Endpoint{testEndpoint("power-si-001")}}, client, publisher)
	runtime.NowMS = func() uint64 { return 9000 }
	runtime.ReconcileInventory(testInventory())
	runtime.recordEndpoints([]Endpoint{testEndpoint("power-si-001")})
	return runtime
}

func schedulerCommand(t *testing.T, id string, target uint8) protocol.CapabilityCommand {
	t.Helper()
	command, err := protocol.NewCapabilityCommand(id, "power-si-001", target, "test", 9000, 1, nil)
	if err != nil {
		t.Fatal(err)
	}
	return command
}

func waitForSignal(t *testing.T, signal <-chan struct{}, description string) {
	t.Helper()
	select {
	case <-signal:
	case <-time.After(2 * time.Second):
		t.Fatalf("timed out waiting for %s", description)
	}
}

type blockingMaintenanceClient struct {
	mu sync.Mutex

	getCalls    int
	getStarted  chan struct{}
	getCanceled chan struct{}
	secondGet   chan struct{}
	putStarted  chan struct{}
}

func (c *blockingMaintenanceClient) GetState(ctx context.Context, _ Endpoint) (DeviceState, error) {
	c.mu.Lock()
	c.getCalls++
	call := c.getCalls
	c.mu.Unlock()
	if call == 1 {
		close(c.getStarted)
		<-ctx.Done()
		close(c.getCanceled)
		return DeviceState{}, ctx.Err()
	}
	close(c.secondGet)
	return DeviceState{ThingName: "power-si-001", ProtocolVersion: "1", Redcon: 3}, nil
}

func (c *blockingMaintenanceClient) PutRedcon(_ context.Context, _ Endpoint, target uint8) (DeviceState, error) {
	close(c.putStarted)
	return DeviceState{ThingName: "power-si-001", ProtocolVersion: "1", Redcon: target}, nil
}

type orderedCommandClient struct {
	mu sync.Mutex

	targets       []uint8
	firstStarted  chan struct{}
	allowFirst    chan struct{}
	secondStarted chan struct{}
}

func (c *orderedCommandClient) GetState(context.Context, Endpoint) (DeviceState, error) {
	return DeviceState{ThingName: "power-si-001", ProtocolVersion: "1", Redcon: 4}, nil
}

func (c *orderedCommandClient) PutRedcon(_ context.Context, _ Endpoint, target uint8) (DeviceState, error) {
	c.mu.Lock()
	c.targets = append(c.targets, target)
	position := len(c.targets)
	c.mu.Unlock()
	if position == 1 {
		close(c.firstStarted)
		<-c.allowFirst
	} else {
		close(c.secondStarted)
	}
	return DeviceState{ThingName: "power-si-001", ProtocolVersion: "1", Redcon: target}, nil
}

func (c *orderedCommandClient) commandTargets() []uint8 {
	c.mu.Lock()
	defer c.mu.Unlock()
	return append([]uint8(nil), c.targets...)
}

type countingDiscoverer struct {
	mu sync.Mutex

	endpoints []Endpoint
	calls     int
}

func (d *countingDiscoverer) Discover(context.Context) ([]Endpoint, error) {
	d.mu.Lock()
	defer d.mu.Unlock()
	d.calls++
	return d.endpoints, nil
}

func (d *countingDiscoverer) callsMade() int {
	d.mu.Lock()
	defer d.mu.Unlock()
	return d.calls
}
