package controller

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/service/iot"
	iottypes "github.com/aws/aws-sdk-go-v2/service/iot/types"
	"github.com/aws/aws-sdk-go-v2/service/iotdataplane"
	dataplanetypes "github.com/aws/aws-sdk-go-v2/service/iotdataplane/types"

	"txing.dev/virtual-quad-lambda/internal/lifecycle"
)

var ErrNotAssigned = errors.New("virtual quad has no valid cloud rig assignment")

type Registry interface {
	Assignment(context.Context, string) (lifecycle.Assignment, bool, error)
}

type ThingClient interface {
	DescribeThing(context.Context, *iot.DescribeThingInput, ...func(*iot.Options)) (*iot.DescribeThingOutput, error)
}

type ShadowReader interface {
	GetThingShadow(context.Context, *iotdataplane.GetThingShadowInput, ...func(*iotdataplane.Options)) (*iotdataplane.GetThingShadowOutput, error)
}

type AWSRegistry struct {
	things  ThingClient
	shadows ShadowReader
}

func NewAWSRegistry(things ThingClient, shadows ShadowReader) AWSRegistry {
	return AWSRegistry{things: things, shadows: shadows}
}

func (r AWSRegistry) Assignment(ctx context.Context, deviceID string) (lifecycle.Assignment, bool, error) {
	var result lifecycle.Assignment
	if !segment.MatchString(deviceID) {
		return result, false, ErrNotAssigned
	}
	device, err := r.describe(ctx, deviceID)
	if err != nil {
		return result, false, err
	}
	rigID, townID := device.Attributes["rigId"], device.Attributes["townId"]
	if aws.ToString(device.ThingTypeName) != "virtual-quad" || device.Attributes["kind"] != "deviceType" ||
		device.Attributes["rigType"] != "cloud" || !segment.MatchString(rigID) || !segment.MatchString(townID) {
		return result, false, ErrNotAssigned
	}
	rig, err := r.describe(ctx, rigID)
	if err != nil {
		return result, false, err
	}
	if aws.ToString(rig.ThingTypeName) != "cloud" || rig.Attributes["kind"] != "rigType" || rig.Attributes["townId"] != townID {
		return result, false, ErrNotAssigned
	}
	result = lifecycle.Assignment{DeviceID: deviceID, TownID: townID, RigID: rigID}
	awake, err := r.awake(ctx, result)
	return result, awake, err
}

func (r AWSRegistry) describe(ctx context.Context, thing string) (*iot.DescribeThingOutput, error) {
	result, err := r.things.DescribeThing(ctx, &iot.DescribeThingInput{ThingName: aws.String(thing)})
	var missing *iottypes.ResourceNotFoundException
	if errors.As(err, &missing) {
		return nil, ErrNotAssigned
	}
	if err != nil {
		return nil, fmt.Errorf("describe virtual quad assignment: %w", err)
	}
	return result, nil
}

func (r AWSRegistry) awake(ctx context.Context, assignment lifecycle.Assignment) (bool, error) {
	result, err := r.shadows.GetThingShadow(ctx, &iotdataplane.GetThingShadowInput{
		ThingName: aws.String(assignment.RigID), ShadowName: aws.String("sparkplug"),
	})
	var missing *dataplanetypes.ResourceNotFoundException
	if errors.As(err, &missing) {
		return false, nil
	}
	if err != nil {
		return false, fmt.Errorf("read cloud rig projection: %w", err)
	}
	var shadow struct {
		State struct {
			Reported struct {
				Topic struct {
					Namespace   string `json:"namespace"`
					MessageType string `json:"messageType"`
					GroupID     string `json:"groupId"`
					EdgeNodeID  string `json:"edgeNodeId"`
				} `json:"topic"`
				Payload struct {
					Metrics struct {
						REDCON int `json:"redcon"`
					} `json:"metrics"`
				} `json:"payload"`
			} `json:"reported"`
		} `json:"state"`
	}
	if err := json.Unmarshal(result.Payload, &shadow); err != nil {
		return false, fmt.Errorf("decode cloud rig projection: %w", err)
	}
	reported := shadow.State.Reported
	return reported.Topic.Namespace == "spBv1.0" && reported.Topic.GroupID == assignment.TownID &&
		reported.Topic.EdgeNodeID == assignment.RigID && (reported.Topic.MessageType == "NBIRTH" || reported.Topic.MessageType == "NDATA") &&
		reported.Payload.Metrics.REDCON == 1, nil
}
