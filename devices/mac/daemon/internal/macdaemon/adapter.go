// Package macdaemon implements the mac device watch layer: a rig IPC
// connectivity adapter that lets the local rig manage the development
// Mac as a txing device. It is modeled on the rig Thread adapter
// (rig/internal/thread/runtime.go), with one difference: the mac
// device accepts every REDCON target 1-4 without normalization, and a
// command succeeds when the daemon has applied the target locally.
// Higher derived levels (2, 1) require board/mcp/video evidence that
// the action layer publishes separately; the rig manager converges the
// reported REDCON to the highest level supported by evidence.
package macdaemon

import (
	"fmt"
	"sync"
	"time"

	"github.com/mparkachov/txing/devices/mac/daemon/internal/rigadapter"
)

const (
	AdapterID  = "dev.txing.mac.Daemon"
	DeviceType = "mac"

	SparkplugCapability = "sparkplug"
	PowerCapability     = "power"
)

// Machine holds the daemon-side REDCON target. The watch layer derives
// simulated power evidence from it: power is on below REDCON 4.
type Machine struct {
	mu     sync.Mutex
	redcon uint8
}

func NewMachine(initial uint8) (*Machine, error) {
	if err := rigadapter.ValidateRedcon(initial, "initial redcon"); err != nil {
		return nil, err
	}
	return &Machine{redcon: initial}, nil
}

func (m *Machine) Redcon() uint8 {
	m.mu.Lock()
	defer m.mu.Unlock()
	return m.redcon
}

func (m *Machine) Apply(target uint8) (uint8, error) {
	if err := rigadapter.ValidateRedcon(target, "target.redcon"); err != nil {
		return 0, err
	}
	m.mu.Lock()
	defer m.mu.Unlock()
	m.redcon = target
	return m.redcon, nil
}

// CapabilityStateFor builds the watch-layer IPC state. It must never
// declare board, mcp, or video: those are board-owned capabilities and
// declaring them here would let this state override action-layer
// evidence inside the rig manager's merge.
func CapabilityStateFor(thingName string, redcon uint8, nowMS, seq uint64) rigadapter.CapabilityState {
	return rigadapter.CapabilityState{
		SchemaVersion: rigadapter.SchemaVersion,
		AdapterID:     AdapterID,
		ThingName:     thingName,
		Capabilities: map[string]bool{
			SparkplugCapability: true,
			PowerCapability:     redcon < 4,
		},
		Metrics: map[string]rigadapter.MetricValue{
			rigadapter.TransportRedconMetric: rigadapter.MetricInt32(int32(redcon)),
		},
		ObservedAtMS: nowMS,
		Seq:          seq,
	}
}

type Publisher interface {
	Publish(topic string, payload []byte) error
	PublishRetained(topic string, payload []byte) error
}

type Adapter struct {
	ThingName string
	Machine   *Machine
	Publisher Publisher
	NowMS     func() uint64

	mu      sync.Mutex
	present bool
	seq     uint64
}

func NewAdapter(thingName string, machine *Machine, publisher Publisher) *Adapter {
	return &Adapter{ThingName: thingName, Machine: machine, Publisher: publisher}
}

// ReconcileInventory records whether the rig currently manages this
// thing as a mac device. It returns the presence flag and whether it
// changed; on becoming present the adapter publishes its state so the
// device is born without waiting for the next state tick.
func (a *Adapter) ReconcileInventory(inventory rigadapter.Inventory) (bool, bool, error) {
	present := false
	for _, device := range inventory.Devices {
		if device.ThingName == a.ThingName && device.ThingType == DeviceType {
			present = true
			break
		}
	}
	a.mu.Lock()
	changed := a.present != present
	a.present = present
	a.mu.Unlock()
	if present && changed {
		return present, changed, a.PublishState()
	}
	return present, changed, nil
}

func (a *Adapter) Present() bool {
	a.mu.Lock()
	defer a.mu.Unlock()
	return a.present
}

// PublishState publishes the retained watch-layer capability state.
// It is a no-op while the thing is not in the rig inventory.
func (a *Adapter) PublishState() error {
	if !a.Present() {
		return nil
	}
	state := CapabilityStateFor(a.ThingName, a.Machine.Redcon(), a.nowMS(), a.nextSeq())
	payload, err := state.Marshal()
	if err != nil {
		return err
	}
	topic, err := rigadapter.BuildCapabilityStateTopic(a.ThingName, AdapterID)
	if err != nil {
		return err
	}
	return a.Publisher.PublishRetained(topic, payload)
}

func (a *Adapter) PublishHeartbeat() error {
	var activeThingName *string
	if a.Present() {
		thingName := a.ThingName
		activeThingName = &thingName
	}
	heartbeat := rigadapter.NewCapabilityHeartbeat(AdapterID, rigadapter.HeartbeatRunning, activeThingName, a.nowMS(), a.nextSeq())
	payload, err := heartbeat.Marshal()
	if err != nil {
		return err
	}
	topic, err := rigadapter.BuildCapabilityHeartbeatTopic(AdapterID)
	if err != nil {
		return err
	}
	return a.Publisher.PublishRetained(topic, payload)
}

// HandleCommand applies a REDCON command. All targets 1-4 are
// accepted; success means the target is applied locally and the new
// watch-layer state is published. Reported REDCON above 3 additionally
// depends on action-layer evidence, which is not this method's job.
func (a *Adapter) HandleCommand(command rigadapter.CapabilityCommand) error {
	if command.ThingName != a.ThingName || !a.Present() {
		return nil
	}
	if rigadapter.CommandDeadlineExpired(command, a.nowMS()) {
		message := "command deadline expired"
		return a.publishCommandResult(command, rigadapter.CommandFailed, &message)
	}
	if err := a.publishCommandResult(command, rigadapter.CommandAccepted, nil); err != nil {
		return err
	}
	if _, err := a.Machine.Apply(command.Target.Redcon); err != nil {
		message := err.Error()
		return a.publishCommandResult(command, rigadapter.CommandRejected, &message)
	}
	if err := a.PublishState(); err != nil {
		message := fmt.Sprintf("publish state failed: %v", err)
		_ = a.publishCommandResult(command, rigadapter.CommandFailed, &message)
		return err
	}
	return a.publishCommandResult(command, rigadapter.CommandSucceeded, nil)
}

func (a *Adapter) publishCommandResult(command rigadapter.CapabilityCommand, status string, message *string) error {
	result := rigadapter.NewCapabilityCommandResult(AdapterID, command.CommandID, command.ThingName, status, a.nowMS(), a.nextSeq())
	result.Message = message
	redcon := command.Target.Redcon
	result.Target.Redcon = &redcon
	payload, err := result.Marshal()
	if err != nil {
		return err
	}
	topic, err := rigadapter.BuildCapabilityCommandResultTopic(command.ThingName, AdapterID)
	if err != nil {
		return err
	}
	return a.Publisher.Publish(topic, payload)
}

func (a *Adapter) nowMS() uint64 {
	if a.NowMS != nil {
		return a.NowMS()
	}
	return NowMS()
}

func (a *Adapter) nextSeq() uint64 {
	a.mu.Lock()
	defer a.mu.Unlock()
	value := a.seq
	a.seq++
	return value
}

func NowMS() uint64 {
	return uint64(time.Now().UnixMilli())
}
