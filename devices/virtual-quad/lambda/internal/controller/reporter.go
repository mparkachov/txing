package controller

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/service/iotdataplane"
	"github.com/aws/aws-sdk-go-v2/service/iotdataplane/types"
	"google.golang.org/protobuf/encoding/protowire"
	"txing.dev/virtual-quad-lambda/internal/lifecycle"
)

type ReportClient interface {
	ShadowReader
	UpdateThingShadow(context.Context, *iotdataplane.UpdateThingShadowInput, ...func(*iotdataplane.Options)) (*iotdataplane.UpdateThingShadowOutput, error)
	Publish(context.Context, *iotdataplane.PublishInput, ...func(*iotdataplane.Options)) (*iotdataplane.PublishOutput, error)
}

type AWSReporter struct {
	ledger lifecycle.Ledger
	client ReportClient
	now    func() time.Time
}

func NewAWSReporter(ledger lifecycle.Ledger, client ReportClient) AWSReporter {
	return AWSReporter{ledger: ledger, client: client, now: time.Now}
}

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

func (r AWSReporter) Publish(ctx context.Context, target lifecycle.Assignment, requested *lifecycle.Receipt) error {
	for attempt := 0; attempt < 4; attempt++ {
		sparkplug, err := r.readShadow(ctx, target.DeviceID, "sparkplug")
		if err != nil {
			return err
		}
		observed := sparkplug.State.Reported.Payload.Timestamp
		nowMS := r.now().UnixMilli()
		record, err := r.ledger.PrepareProjection(ctx, target.DeviceID, requested, nowMS, observed)
		if err != nil {
			return err
		}
		simulation, err := r.readShadow(ctx, target.DeviceID, "simulation")
		if err != nil {
			return err
		}
		if simulation.State.Reported.ControllerRevision > record.Version {
			// Retry the caller's correlated receipt against the current record.
			continue
		}
		if simulation.State.Reported.ControllerRevision < record.Version {
			if err := r.writeSimulation(ctx, record, simulation.Version, nowMS); err != nil {
				var conflict *types.ConflictException
				if errors.As(err, &conflict) {
					continue
				}
				return err
			}
		}
		topic := sparkplug.State.Reported.Topic
		if observed >= record.Projection.TimestampMS || topic.Namespace != "spBv1.0" ||
			topic.GroupID != target.TownID || topic.EdgeNodeID != target.RigID || topic.DeviceID != target.DeviceID ||
			(topic.MessageType != "DBIRTH" && topic.MessageType != "DDATA") ||
			(record.Session != nil && record.Session.Assignment != target) {
			return nil
		}
		name := fmt.Sprintf("spBv1.0/%s/DDATA/%s/%s", target.TownID, target.RigID, target.DeviceID)
		_, err = r.client.Publish(ctx, &iotdataplane.PublishInput{
			Topic: aws.String(name), Qos: 1, Payload: encodeProjection(*record.Projection),
		})
		return err
	}
	return lifecycle.ErrContention
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

func (r AWSReporter) writeSimulation(ctx context.Context, record lifecycle.Record, version, nowMS int64) error {
	reported := map[string]any{
		"controllerRevision": record.Version, "phase": record.Phase(), "terminalRevision": record.TerminalRevision,
		"availabilityWatermarkMs": record.AvailabilityWatermarkMS, "availabilityExpiresAtMs": nil,
		"sessionId": nil, "startupDeadlineMs": nil, "flightDeadlineMs": nil, "shutdownDeadlineMs": nil,
		"lastSessionId": nil, "lastOutcome": nil, "lastReason": nil,
	}
	if s := record.Session; s != nil {
		reported["sessionId"] = s.ID
		reported["startupDeadlineMs"] = s.StartupDeadlineMS
		reported["shutdownDeadlineMs"] = s.ShutdownDeadlineMS
		if s.Stop != nil {
			reported["shutdownDeadlineMs"] = s.Stop.DeadlineMS
		}
		if s.FlightDeadlineMS > 0 {
			reported["flightDeadlineMs"] = s.FlightDeadlineMS
		}
		if expiry := record.Availability(nowMS).ExpiresMS; expiry > 0 {
			reported["availabilityExpiresAtMs"] = expiry
		}
	}
	if last := record.Last; last != nil {
		reported["lastSessionId"], reported["lastOutcome"], reported["lastReason"] = last.SessionID, last.Outcome, last.Reason
	}
	payload, err := json.Marshal(map[string]any{"version": version, "state": map[string]any{"reported": reported}})
	if err != nil {
		return err
	}
	_, err = r.client.UpdateThingShadow(ctx, &iotdataplane.UpdateThingShadowInput{
		ThingName: aws.String(record.DeviceID), ShadowName: aws.String("simulation"), Payload: payload,
	})
	return err
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
	boolean("simulation", true)
	boolean("mavlink", p.Mavlink)
	boolean("video", p.Video)
	boolean("agent", false)
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
