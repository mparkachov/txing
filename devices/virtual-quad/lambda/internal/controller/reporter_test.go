package controller

import (
	"context"
	"encoding/json"
	"testing"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/service/iotdataplane"
	"github.com/aws/aws-sdk-go-v2/service/iotdataplane/types"
	"google.golang.org/protobuf/encoding/protowire"
	"txing.dev/virtual-quad-lambda/internal/lifecycle"
)

type testProjectionClient struct {
	t                 *testing.T
	simulationVersion int64
	revision          uint64
	observed          int64
	conflicts         int
	writes            int
	stamps            []int64
}

func (c *testProjectionClient) GetThingShadow(_ context.Context, input *iotdataplane.GetThingShadowInput, _ ...func(*iotdataplane.Options)) (*iotdataplane.GetThingShadowOutput, error) {
	var shadow namedProjection
	switch aws.ToString(input.ShadowName) {
	case "simulation":
		shadow.Version = c.simulationVersion
		shadow.State.Reported.ControllerRevision = c.revision
	case "sparkplug":
		shadow.Version = 7
		topic := &shadow.State.Reported.Topic
		topic.Namespace, topic.MessageType, topic.DeviceID = "spBv1.0", "DBIRTH", testAssignment.DeviceID
		topic.GroupID, topic.EdgeNodeID = testAssignment.TownID, testAssignment.RigID
		shadow.State.Reported.Payload.Timestamp = c.observed
	default:
		c.t.Fatal("unexpected named shadow")
	}
	payload, err := json.Marshal(shadow)
	return &iotdataplane.GetThingShadowOutput{Payload: payload}, err
}

func (c *testProjectionClient) UpdateThingShadow(_ context.Context, input *iotdataplane.UpdateThingShadowInput, _ ...func(*iotdataplane.Options)) (*iotdataplane.UpdateThingShadowOutput, error) {
	c.writes++
	var body namedProjection
	if err := json.Unmarshal(input.Payload, &body); err != nil || body.Version != c.simulationVersion {
		c.t.Fatalf("simulation write omitted its current shadow version: %#v %v", body, err)
	}
	c.simulationVersion++
	if c.conflicts > 0 {
		c.conflicts--
		return nil, &types.ConflictException{}
	}
	c.revision = body.State.Reported.ControllerRevision
	return &iotdataplane.UpdateThingShadowOutput{}, nil
}

func (c *testProjectionClient) Publish(_ context.Context, input *iotdataplane.PublishInput, _ ...func(*iotdataplane.Options)) (*iotdataplane.PublishOutput, error) {
	if aws.ToString(input.Topic) != "spBv1.0/town-test/DDATA/cloud-test/virtual-quad-test" || input.Qos != 1 {
		c.t.Fatal("projection was published outside the current rig/device topic")
	}
	field, kind, n := protowire.ConsumeTag(input.Payload)
	if field != 1 || kind != protowire.VarintType || n < 0 {
		c.t.Fatal("missing Sparkplug report timestamp")
	}
	stamp, _ := protowire.ConsumeVarint(input.Payload[n:])
	if int64(stamp) <= c.observed {
		c.t.Fatal("stale Sparkplug report timestamp")
	}
	c.observed = int64(stamp)
	c.stamps = append(c.stamps, c.observed)
	return &iotdataplane.PublishOutput{}, nil
}

func TestProjectionRetriesShadowConflictAndSkipsUnchangedSparkplug(t *testing.T) {
	store := &testStore{}
	ledger := lifecycle.NewLedger(store)
	now := time.UnixMilli(1794408173798)
	client := &testProjectionClient{t: t, simulationVersion: 2, observed: now.UnixMilli(), conflicts: 1}
	reporter := NewAWSReporter(ledger, client)
	reporter.now = func() time.Time { return now }
	_, receipt, err := ledger.Reserve(t.Context(), testAssignment, lifecycle.CommandRequest{ID: startID, Sequence: 25}, 0, true, now.UnixMilli())
	if err != nil {
		t.Fatal(err)
	}
	if err := reporter.Publish(t.Context(), testAssignment, &receipt); err != nil {
		t.Fatal(err)
	}
	if client.writes != 2 || len(client.stamps) != 1 || client.stamps[0] != now.UnixMilli()+1 {
		t.Fatalf("expected one report following an optimistic shadow retry: writes=%d stamps=%v", client.writes, client.stamps)
	}
	if err := reporter.Publish(t.Context(), testAssignment, nil); err != nil || client.writes != 2 || len(client.stamps) != 1 {
		t.Fatalf("unchanged state was written or republished: %v", err)
	}
	failure := lifecycle.Receipt{RequestID: stopID, Sequence: 26, REDCON: 4, Status: lifecycle.Failed, Reason: "stale target"}
	if err := reporter.Publish(t.Context(), testAssignment, &failure); err != nil {
		t.Fatal(err)
	}
	if err := reporter.Publish(t.Context(), testAssignment, nil); err != nil || len(client.stamps) != 2 || client.stamps[1] != now.UnixMilli()+2 {
		t.Fatalf("unchanged repair replaced a correlated rejection or moved time backwards: %v", err)
	}
}
