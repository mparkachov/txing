package thread

import (
	"context"
	"fmt"
	"sync"

	"github.com/mparkachov/txing/rig/internal/protocol"
)

type EndpointDiscoverer interface {
	Discover(ctx context.Context) ([]Endpoint, error)
}

type DeviceClient interface {
	GetState(ctx context.Context, endpoint Endpoint) (DeviceState, error)
	PutRedcon(ctx context.Context, endpoint Endpoint, target uint8) (DeviceState, error)
}

type Publisher interface {
	Publish(topic string, payload []byte) error
	PublishRetained(topic string, payload []byte) error
}

type Runtime struct {
	Discoverer EndpointDiscoverer
	Client     DeviceClient
	Publisher  Publisher
	NowMS      func() uint64

	mu        sync.Mutex
	specs     map[string]DeviceSpec
	endpoints map[string]Endpoint
	seq       uint64
}

func NewRuntime(discoverer EndpointDiscoverer, client DeviceClient, publisher Publisher) *Runtime {
	return &Runtime{
		Discoverer: discoverer,
		Client:     client,
		Publisher:  publisher,
		specs:      map[string]DeviceSpec{},
		endpoints:  map[string]Endpoint{},
	}
}

func (r *Runtime) ReconcileInventory(inventory protocol.Inventory) int {
	next := map[string]DeviceSpec{}
	for _, device := range inventory.Devices {
		spec := DeviceSpecFromInventory(device)
		if spec != nil {
			next[spec.ThingName] = *spec
		}
	}
	r.mu.Lock()
	r.specs = next
	for thingName := range r.endpoints {
		if _, ok := next[thingName]; !ok {
			delete(r.endpoints, thingName)
		}
	}
	r.mu.Unlock()
	return len(next)
}

func (r *Runtime) DiscoverAndPoll(ctx context.Context) error {
	if r.Discoverer == nil || r.Client == nil || r.Publisher == nil {
		return fmt.Errorf("thread runtime is not fully configured")
	}
	endpoints, err := r.Discoverer.Discover(ctx)
	if err != nil {
		r.publishAllOffline(ctx)
		return err
	}
	r.recordEndpoints(endpoints)
	specs := r.specSnapshot()
	for thingName := range specs {
		endpoint, ok := r.endpointFor(thingName)
		if !ok {
			if err := r.publishOffline(ctx, thingName); err != nil {
				return err
			}
			continue
		}
		if err := r.pollEndpoint(ctx, endpoint); err != nil {
			_ = r.publishOffline(ctx, thingName)
		}
	}
	return nil
}

func (r *Runtime) HandleCommand(ctx context.Context, command protocol.CapabilityCommand) error {
	if r.Publisher == nil || r.Client == nil {
		return fmt.Errorf("thread runtime is not fully configured")
	}
	target, err := protocol.NormalizeThreadTargetRedcon(command.Target.Redcon)
	if err != nil {
		message := err.Error()
		return r.publishCommandResult(command, protocol.CommandRejected, &message, &command.Target.Redcon)
	}
	if _, ok := r.specFor(command.ThingName); !ok {
		return nil
	}
	if protocol.CommandDeadlineExpired(command, r.nowMS()) {
		message := "command deadline expired"
		return r.publishCommandResult(command, protocol.CommandFailed, &message, &command.Target.Redcon)
	}
	endpoint, ok := r.endpointFor(command.ThingName)
	if !ok {
		message := "Thread endpoint is unavailable"
		_ = r.publishOffline(ctx, command.ThingName)
		return r.publishCommandResult(command, protocol.CommandFailed, &message, &command.Target.Redcon)
	}
	if err := r.publishCommandResult(command, protocol.CommandAccepted, nil, &command.Target.Redcon); err != nil {
		return err
	}
	state, err := r.Client.PutRedcon(ctx, endpoint, target)
	if err != nil {
		message := fmt.Sprintf("Thread REDCON command failed: %v", err)
		_ = r.publishOffline(ctx, command.ThingName)
		return r.publishCommandResult(command, protocol.CommandFailed, &message, &command.Target.Redcon)
	}
	state = r.decorateState(state, endpoint)
	if err := r.publishState(ctx, state); err != nil {
		return err
	}
	if state.Redcon != target {
		message := fmt.Sprintf("confirmed Thread state REDCON %d, want %d", state.Redcon, target)
		return r.publishCommandResult(command, protocol.CommandFailed, &message, &command.Target.Redcon)
	}
	return r.publishCommandResult(command, protocol.CommandSucceeded, nil, &command.Target.Redcon)
}

func (r *Runtime) pollEndpoint(ctx context.Context, endpoint Endpoint) error {
	state, err := r.Client.GetState(ctx, endpoint)
	if err != nil {
		return err
	}
	return r.publishState(ctx, r.decorateState(state, endpoint))
}

func (r *Runtime) publishState(_ context.Context, state DeviceState) error {
	capability := CapabilityStateFromDeviceState(state)
	payload, err := capability.Marshal()
	if err != nil {
		return err
	}
	topic, err := protocol.BuildCapabilityStateTopic(state.ThingName, AdapterID)
	if err != nil {
		return err
	}
	if err := r.Publisher.PublishRetained(topic, payload); err != nil {
		return err
	}
	updates, err := ShadowUpdatesFromState(state)
	if err != nil {
		return err
	}
	for _, update := range updates {
		if err := r.Publisher.Publish(update.Topic, update.Payload); err != nil {
			return err
		}
	}
	return nil
}

func (r *Runtime) publishOffline(_ context.Context, thingName string) error {
	state := OfflineCapabilityState(thingName, r.nowMS(), r.nextSeq())
	payload, err := state.Marshal()
	if err != nil {
		return err
	}
	topic, err := protocol.BuildCapabilityStateTopic(thingName, AdapterID)
	if err != nil {
		return err
	}
	if err := r.Publisher.PublishRetained(topic, payload); err != nil {
		return err
	}
	update, err := OfflineShadowUpdate(thingName)
	if err != nil {
		return err
	}
	return r.Publisher.Publish(update.Topic, update.Payload)
}

func (r *Runtime) publishAllOffline(ctx context.Context) {
	for thingName := range r.specSnapshot() {
		_ = r.publishOffline(ctx, thingName)
	}
}

func (r *Runtime) publishCommandResult(command protocol.CapabilityCommand, status string, message *string, redcon *uint8) error {
	topic, payload, err := PublishCommandResult(command, status, message, redcon, r.nowMS(), r.nextSeq())
	if err != nil {
		return err
	}
	return r.Publisher.Publish(topic, payload)
}

func (r *Runtime) recordEndpoints(endpoints []Endpoint) {
	r.mu.Lock()
	defer r.mu.Unlock()
	next := map[string]Endpoint{}
	for _, endpoint := range endpoints {
		if _, ok := r.specs[endpoint.ThingName]; ok {
			next[endpoint.ThingName] = endpoint
		}
	}
	r.endpoints = next
}

func (r *Runtime) decorateState(state DeviceState, endpoint Endpoint) DeviceState {
	state.ServiceInstance = endpoint.ServiceInstance
	state.Host = endpoint.Host
	state.Address = endpoint.Address.String()
	state.Port = endpoint.Port
	state.ObservedAtMS = r.nowMS()
	state.Seq = r.nextSeq()
	return state
}

func (r *Runtime) specSnapshot() map[string]DeviceSpec {
	r.mu.Lock()
	defer r.mu.Unlock()
	out := make(map[string]DeviceSpec, len(r.specs))
	for key, value := range r.specs {
		out[key] = value
	}
	return out
}

func (r *Runtime) specFor(thingName string) (DeviceSpec, bool) {
	r.mu.Lock()
	defer r.mu.Unlock()
	spec, ok := r.specs[thingName]
	return spec, ok
}

func (r *Runtime) endpointFor(thingName string) (Endpoint, bool) {
	r.mu.Lock()
	defer r.mu.Unlock()
	endpoint, ok := r.endpoints[thingName]
	return endpoint, ok
}

func (r *Runtime) nowMS() uint64 {
	if r.NowMS != nil {
		return r.NowMS()
	}
	return NowMS()
}

func (r *Runtime) nextSeq() uint64 {
	r.mu.Lock()
	defer r.mu.Unlock()
	value := r.seq
	r.seq++
	return value
}
