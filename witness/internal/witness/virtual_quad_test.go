package witness

import (
	"context"
	"testing"

	"github.com/aws/aws-sdk-go-v2/service/iotdataplane/types"
)

type conflictingQuadShadow struct {
	fakeAWS
	newer map[string]any
}

func (f *conflictingQuadShadow) UpdateSparkplugShadow(ctx context.Context, thingName string, payload map[string]any) error {
	if f.newer != nil {
		f.shadow, f.newer = f.newer, nil
		return &types.ConflictException{}
	}
	return f.fakeAWS.UpdateSparkplugShadow(ctx, thingName, payload)
}

func TestVirtualQuadProjectionFencesOldReportsAndReplacesBirthAtomically(t *testing.T) {
	kind, device := "virtual-quad", "virtual-quad-test"
	ts := int64(100)
	message := SparkplugMessage{
		GroupID: "town-test", EdgeNodeID: "cloud-test", DeviceID: &device, MessageType: "DDATA",
		SparkplugTimestamp: &ts, Metrics: map[string]any{"redcon": 1},
	}
	shadow := func(stamp, version int64, messageType string) map[string]any {
		existing := message
		existing.SparkplugTimestamp, existing.MessageType = &stamp, messageType
		existing.Metrics = map[string]any{
			"redcon": 1, "virtualQuad": map[string]any{"sessionId": "old-session"},
			"capability": map[string]any{"video": true, "retired": true},
		}
		return map[string]any{"version": version, "state": map[string]any{
			"reported": BuildReportedPayload(&existing, stamp),
		}}
	}
	client := &conflictingQuadShadow{
		fakeAWS: fakeAWS{
			things: map[string]ThingDescription{device: {ThingTypeName: &kind, Attributes: map[string]string{
				"townId": message.GroupID, "rigId": message.EdgeNodeID,
			}}},
			shadow: shadow(99, 6, "DBIRTH"),
		},
		newer: shadow(101, 7, "DDATA"),
	}
	if _, err := ProjectSparkplugMessage(t.Context(), &message, 103, client); err != nil || len(client.updates) != 0 {
		t.Fatalf("delayed report was not fenced after conflict: writes=%d err=%v", len(client.updates), err)
	}
	client.shadow = shadow(102, 8, "DDEATH")
	ts = 103
	if _, err := ProjectSparkplugMessage(t.Context(), &message, 104, client); err != nil || len(client.updates) != 0 {
		t.Fatalf("DDATA resurrected a dead projection: writes=%d err=%v", len(client.updates), err)
	}
	ts = 104
	message.MessageType = "DBIRTH"
	message.Metrics = map[string]any{"redcon": 4, "capability": map[string]any{"video": false}}
	if _, err := ProjectSparkplugMessage(t.Context(), &message, 105, client); err != nil || len(client.updates) != 1 {
		t.Fatalf("birth failed to commit in one write: writes=%d err=%v", len(client.updates), err)
	}
	update := client.updates[0].payload
	metrics, _ := reportedMetricsFromShadow(update)
	capabilities, _ := metrics["capability"].(map[string]any)
	if update["version"] != int64(8) || metrics["redcon"] != 4 || capabilities["video"] != false ||
		!hasNullPatch(metrics, "virtualQuad") || !hasNullPatch(capabilities, "retired") {
		t.Fatalf("birth did not replace old state with a version check: %+v", update)
	}
}

func hasNullPatch(patch map[string]any, key string) bool {
	value, present := patch[key]
	return present && value == nil
}
