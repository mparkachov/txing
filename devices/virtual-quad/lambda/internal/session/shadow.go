package session

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/service/iotdataplane"
	"github.com/aws/aws-sdk-go-v2/service/iotdataplane/types"
)

type ShadowClient interface {
	GetThingShadow(context.Context, *iotdataplane.GetThingShadowInput, ...func(*iotdataplane.Options)) (*iotdataplane.GetThingShadowOutput, error)
	UpdateThingShadow(context.Context, *iotdataplane.UpdateThingShadowInput, ...func(*iotdataplane.Options)) (*iotdataplane.UpdateThingShadowOutput, error)
}

type Shadow struct {
	client ShadowClient
}

func NewShadow(client ShadowClient) Shadow { return Shadow{client: client} }

type document struct {
	Version int64 `json:"version"`
	State   struct {
		Reported State `json:"reported"`
	} `json:"state"`
}

func (s Shadow) Read(ctx context.Context, deviceID string) (State, int64, error) {
	out, err := s.client.GetThingShadow(ctx, &iotdataplane.GetThingShadowInput{
		ThingName: aws.String(deviceID), ShadowName: aws.String("simulation"),
	})
	if err != nil {
		return State{}, 0, fmt.Errorf("read simulation shadow: %w", err)
	}
	var doc document
	if err := json.Unmarshal(out.Payload, &doc); err != nil {
		return State{}, 0, fmt.Errorf("decode simulation shadow: %w", err)
	}
	if doc.Version <= 0 || doc.State.Reported.Phase == "" {
		return State{}, 0, errors.New("simulation shadow is missing its version or phase")
	}
	return doc.State.Reported, doc.Version, nil
}

// Change retries only version conflicts. The mutation is evaluated again on
// the latest state, so a competing Start or Stop remains authoritative.
func (s Shadow) Change(ctx context.Context, deviceID string, change func(*State) error) (State, error) {
	for attempt := 0; attempt < 5; attempt++ {
		state, version, err := s.Read(ctx, deviceID)
		if err != nil {
			return State{}, err
		}
		if err := change(&state); err != nil {
			return state, err
		}
		state.ProjectionTimestamp = max(state.ProjectionTimestamp+1, time.Now().UnixMilli())
		payload, err := json.Marshal(map[string]any{
			"version": version,
			"state":   map[string]any{"reported": state},
		})
		if err != nil {
			return State{}, fmt.Errorf("encode simulation shadow: %w", err)
		}
		_, err = s.client.UpdateThingShadow(ctx, &iotdataplane.UpdateThingShadowInput{
			ThingName: aws.String(deviceID), ShadowName: aws.String("simulation"), Payload: payload,
		})
		if err == nil {
			return state, nil
		}
		var conflict *types.ConflictException
		if !errors.As(err, &conflict) {
			return State{}, fmt.Errorf("update simulation shadow: %w", err)
		}
	}
	return State{}, errors.New("simulation shadow update contention")
}
