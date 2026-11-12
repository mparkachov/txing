package witness

import (
	"context"
	"errors"
	"fmt"

	"github.com/aws/aws-sdk-go-v2/service/iotdataplane/types"
)

func projectVirtualQuad(ctx context.Context, message *SparkplugMessage, reported map[string]any, client AWS) error {
	if message.SparkplugTimestamp == nil || *message.SparkplugTimestamp <= 0 {
		return nil
	}
	deviceID := *message.DeviceID
	thing, err := client.DescribeThing(ctx, deviceID)
	if err != nil {
		if errorIsNotFound(err) {
			return nil
		}
		return err
	}
	if thing.ThingTypeName == nil || *thing.ThingTypeName != "virtual-quad" ||
		thing.Attributes["townId"] != message.GroupID || thing.Attributes["rigId"] != message.EdgeNodeID {
		return nil
	}

	payload := reported["payload"].(map[string]any)
	for attempt := 0; attempt < 5; attempt++ {
		shadow, found, err := client.GetSparkplugShadow(ctx, deviceID)
		if err != nil {
			return err
		}
		version := numberAsInt64(shadow["version"])
		if !found || version <= 0 {
			return fmt.Errorf("virtual quad %q has no versioned sparkplug shadow", deviceID)
		}
		state, _ := shadow["state"].(map[string]any)
		current, _ := state["reported"].(map[string]any)
		currentPayload, _ := current["payload"].(map[string]any)
		currentTopic, _ := current["topic"].(map[string]any)
		if *message.SparkplugTimestamp <= numberAsInt64(currentPayload["timestamp"]) {
			return nil
		}
		if message.MessageType == "DDATA" {
			currentType, _ := currentTopic["messageType"].(string)
			if (currentType != "DBIRTH" && currentType != "DDATA") ||
				currentTopic["groupId"] != message.GroupID || currentTopic["edgeNodeId"] != message.EdgeNodeID ||
				currentTopic["deviceId"] != deviceID {
				return nil
			}
			payload["metrics"] = prepareMetricPatchForMerge(message.Metrics)
		} else {
			currentMetrics, _ := currentPayload["metrics"].(map[string]any)
			payload["metrics"] = replaceVirtualQuadMetrics(currentMetrics, message.Metrics)
		}
		err = client.UpdateSparkplugShadow(ctx, deviceID, map[string]any{
			"version": version,
			"state":   map[string]any{"reported": reported},
		})
		var conflict *types.ConflictException
		if !errors.As(err, &conflict) {
			return err
		}
	}
	return fmt.Errorf("virtual quad %q sparkplug shadow update contention", deviceID)
}

// A shadow update merges objects. Null each retired field in the same update
// that replaces the metrics and advances the payload timestamp.
func replaceVirtualQuadMetrics(current, next map[string]any) map[string]any {
	patch := cloneAnyMap(next)
	for key, value := range current {
		nextValue, exists := next[key]
		if !exists {
			patch[key] = nil
			continue
		}
		currentObject, currentIsObject := value.(map[string]any)
		nextObject, nextIsObject := nextValue.(map[string]any)
		if currentIsObject && nextIsObject {
			patch[key] = replaceVirtualQuadMetrics(currentObject, nextObject)
		}
	}
	return patch
}
