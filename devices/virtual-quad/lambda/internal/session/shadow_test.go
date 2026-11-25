package session

import (
	"context"
	"encoding/json"
	"errors"
	"sync"
	"testing"

	"github.com/aws/aws-sdk-go-v2/service/iotdataplane"
	"github.com/aws/aws-sdk-go-v2/service/iotdataplane/types"
)

type memoryShadow struct {
	mu      sync.Mutex
	version int64
	state   State
}

func (m *memoryShadow) GetThingShadow(_ context.Context, _ *iotdataplane.GetThingShadowInput, _ ...func(*iotdataplane.Options)) (*iotdataplane.GetThingShadowOutput, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	doc := document{Version: m.version}
	doc.State.Reported = m.state
	payload, err := json.Marshal(doc)
	return &iotdataplane.GetThingShadowOutput{Payload: payload}, err
}

func (m *memoryShadow) UpdateThingShadow(_ context.Context, input *iotdataplane.UpdateThingShadowInput, _ ...func(*iotdataplane.Options)) (*iotdataplane.UpdateThingShadowOutput, error) {
	var doc document
	if err := json.Unmarshal(input.Payload, &doc); err != nil {
		return nil, err
	}
	m.mu.Lock()
	defer m.mu.Unlock()
	if doc.Version != m.version {
		return nil, &types.ConflictException{}
	}
	m.version++
	m.state = doc.State.Reported
	return &iotdataplane.UpdateThingShadowOutput{}, nil
}

func TestConcurrentStartsReserveOnlyOneSession(t *testing.T) {
	client := &memoryShadow{version: 1, state: State{Phase: "stopped"}}
	shadow := NewShadow(client)
	start := make(chan struct{})
	results := make(chan error, 2)
	for _, id := range []string{"one", "two"} {
		go func(id string) {
			<-start
			_, err := shadow.Change(context.Background(), "virtual-quad-test", func(state *State) error {
				return state.Start(id, "owner-"+id, "town", "cloud-rig", 1, 0, startTime, startTime+900_000)
			})
			results <- err
		}(id)
	}
	close(start)
	first, second := <-results, <-results
	if !((first == nil && errors.Is(second, ErrBusy)) || (second == nil && errors.Is(first, ErrBusy))) {
		t.Fatalf("expected one accepted start and one busy result, got %v and %v", first, second)
	}
	state, version, err := shadow.Read(context.Background(), "virtual-quad-test")
	if err != nil || version != 2 || state.Run == nil || state.SessionID == nil {
		t.Fatalf("unexpected stored session: version=%d state=%+v error=%v", version, state, err)
	}
}
