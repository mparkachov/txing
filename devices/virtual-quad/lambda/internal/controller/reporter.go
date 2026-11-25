package controller

import (
	"context"
	"encoding/json"
	"fmt"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/service/iotdataplane"
	"google.golang.org/protobuf/encoding/protowire"
	"txing.dev/virtual-quad-lambda/internal/lifecycle"
)

type ReportClient interface {
	ShadowReader
	UpdateThingShadow(context.Context, *iotdataplane.UpdateThingShadowInput, ...func(*iotdataplane.Options)) (*iotdataplane.UpdateThingShadowOutput, error)
	Publish(context.Context, *iotdataplane.PublishInput, ...func(*iotdataplane.Options)) (*iotdataplane.PublishOutput, error)
}

type AWSReporter struct{ client ReportClient }

type namedProjection struct {
	Version int64 `json:"version"`
	State   struct {
		Reported struct {
			ControllerRevision uint64 `json:"controllerRevision"`
			Topic              struct {
				Namespace   string `json:"namespace"`
				MessageType string `json:"messageType"`
				GroupID     string `json:"groupId"`
				EdgeNodeID  string `json:"edgeNodeId"`
				DeviceID    string `json:"deviceId"`
			} `json:"topic"`
			Payload struct {
				Timestamp int64 `json:"timestamp"`
			} `json:"payload"`
		} `json:"reported"`
	} `json:"state"`
}

func (r AWSReporter) readShadow(ctx context.Context, device, name string) (namedProjection, error) {
	out, err := r.client.GetThingShadow(ctx, &iotdataplane.GetThingShadowInput{ThingName: aws.String(device), ShadowName: aws.String(name)})
	if err != nil {
		return namedProjection{}, fmt.Errorf("read %s shadow: %w", name, err)
	}
	var shadow namedProjection
	if err := json.Unmarshal(out.Payload, &shadow); err != nil {
		return namedProjection{}, fmt.Errorf("decode %s shadow: %w", name, err)
	}
	if shadow.Version < 1 {
		return namedProjection{}, fmt.Errorf("%s shadow has no version", name)
	}
	return shadow, nil
}

func encodeProjection(p lifecycle.Projection) []byte {
	payload := protowire.AppendVarint(protowire.AppendTag(nil, 1, protowire.VarintType), uint64(p.TimestampMS))
	metric := func(name string, datatype uint64, value []byte) {
		body := protowire.AppendString(protowire.AppendTag(nil, 1, protowire.BytesType), name)
		body = protowire.AppendVarint(protowire.AppendTag(body, 4, protowire.VarintType), datatype)
		body = append(body, value...)
		payload = protowire.AppendBytes(protowire.AppendTag(payload, 2, protowire.BytesType), body)
	}
	integer := func(name string, value uint64) {
		metric(name, typeInt32, protowire.AppendVarint(protowire.AppendTag(nil, 10, protowire.VarintType), value))
	}
	text := func(name, value string) {
		metric(name, typeString, protowire.AppendString(protowire.AppendTag(nil, 15, protowire.BytesType), value))
	}
	boolean := func(name string, value bool) {
		metric("capability."+name, 11, protowire.AppendVarint(protowire.AppendTag(nil, 14, protowire.VarintType), protowire.EncodeBool(value)))
	}
	integer("redcon", uint64(p.REDCON))
	boolean("sparkplug", true)
	boolean("simulation", p.Simulation != nil && *p.Simulation)
	boolean("mavlink", p.Mavlink)
	boolean("video", p.Video)
	boolean("agent", p.Agent)
	text(sessionMetric, p.SessionID)
	if p.Receipt.RequestID != "" {
		text("redconCommandId", p.Receipt.RequestID)
		text("redconCommandStatus", string(p.Receipt.Status))
		text("redconCommandMessage", p.Receipt.Reason)
		integer("redconCommandSeq", uint64(p.Receipt.Sequence))
		integer("redconCommandTarget", uint64(p.Receipt.REDCON))
	}
	return protowire.AppendVarint(protowire.AppendTag(payload, 3, protowire.VarintType), uint64(p.TimestampMS%256))
}
