package witness

import (
	"context"
	"encoding/base64"
	"encoding/binary"
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"strings"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/service/iot"
	"github.com/aws/aws-sdk-go-v2/service/iotdataplane"
)

const (
	SparkplugNamespace = "spBv1.0"
	RigKindAttribute   = "rigType"
)

var (
	deviceMessageTypes         = map[string]bool{"DBIRTH": true, "DDATA": true, "DDEATH": true}
	nodeMessageTypes           = map[string]bool{"NBIRTH": true, "NDATA": true, "NDEATH": true}
	replaceMetricsMessageTypes = map[string]bool{"DBIRTH": true, "NBIRTH": true}
	mergeMetricsMessageTypes   = map[string]bool{"DDATA": true, "NDATA": true}
	clearMetricsMessageTypes   = map[string]bool{"DDEATH": true, "NDEATH": true}
	commandResultMetricKeys    = []string{
		"redconCommandId",
		"redconCommandObservedAt",
		"redconCommandSeq",
		"redconCommandStatus",
		"redconCommandTarget",
		"redconCommandMessage",
	}
)

type SparkplugMessage struct {
	GroupID            string
	MessageType        string
	EdgeNodeID         string
	DeviceID           *string
	Seq                *int64
	SparkplugTimestamp *int64
	Metrics            map[string]any
}

type ThingDescription struct {
	ThingTypeName *string
	Attributes    map[string]string
}

type AWS interface {
	DescribeThing(ctx context.Context, thingName string) (ThingDescription, error)
	GetSparkplugShadow(ctx context.Context, thingName string) (map[string]any, bool, error)
	UpdateSparkplugShadow(ctx context.Context, thingName string, payload map[string]any) error
}

type AWSClient struct {
	iot     *iot.Client
	iotData *iotdataplane.Client
}

func NewAWSClient(ctx context.Context) (*AWSClient, error) {
	cfg, err := config.LoadDefaultConfig(ctx)
	if err != nil {
		return nil, err
	}
	iotClient := iot.NewFromConfig(cfg)
	endpoint, err := iotClient.DescribeEndpoint(ctx, &iot.DescribeEndpointInput{
		EndpointType: aws.String("iot:Data-ATS"),
	})
	if err != nil {
		return nil, fmt.Errorf("describe AWS IoT data endpoint: %w", err)
	}
	if endpoint.EndpointAddress == nil || strings.TrimSpace(*endpoint.EndpointAddress) == "" {
		return nil, errors.New("AWS IoT describe_endpoint returned no endpointAddress")
	}
	iotData := iotdataplane.NewFromConfig(cfg, func(options *iotdataplane.Options) {
		options.BaseEndpoint = aws.String("https://" + strings.TrimSpace(*endpoint.EndpointAddress))
	})
	return &AWSClient{iot: iotClient, iotData: iotData}, nil
}

func (c *AWSClient) DescribeThing(ctx context.Context, thingName string) (ThingDescription, error) {
	out, err := c.iot.DescribeThing(ctx, &iot.DescribeThingInput{ThingName: aws.String(thingName)})
	if err != nil {
		return ThingDescription{}, fmt.Errorf("describe AWS IoT thing: %w", err)
	}
	return ThingDescription{
		ThingTypeName: out.ThingTypeName,
		Attributes:    cloneStringMap(out.Attributes),
	}, nil
}

func (c *AWSClient) GetSparkplugShadow(ctx context.Context, thingName string) (map[string]any, bool, error) {
	out, err := c.iotData.GetThingShadow(ctx, &iotdataplane.GetThingShadowInput{
		ThingName:  aws.String(thingName),
		ShadowName: aws.String("sparkplug"),
	})
	if err != nil {
		if errorIsNotFound(err) {
			return nil, false, nil
		}
		return nil, false, fmt.Errorf("get sparkplug shadow: %w", err)
	}
	if out.Payload == nil {
		return nil, false, nil
	}
	var decoded map[string]any
	if err := json.Unmarshal(out.Payload, &decoded); err != nil {
		return nil, false, fmt.Errorf("decode sparkplug shadow payload: %w", err)
	}
	return decoded, true, nil
}

func (c *AWSClient) UpdateSparkplugShadow(ctx context.Context, thingName string, payload map[string]any) error {
	body, err := json.Marshal(payload)
	if err != nil {
		return fmt.Errorf("encode sparkplug shadow update: %w", err)
	}
	_, err = c.iotData.UpdateThingShadow(ctx, &iotdataplane.UpdateThingShadowInput{
		ThingName:  aws.String(thingName),
		ShadowName: aws.String("sparkplug"),
		Payload:    body,
	})
	if err != nil {
		return fmt.Errorf("update sparkplug shadow: %w", err)
	}
	return nil
}

func errorIsNotFound(err error) bool {
	text := fmt.Sprintf("%#v %v", err, err)
	return strings.Contains(text, "ResourceNotFoundException") || strings.Contains(text, "NotFoundException")
}

func readVarint(data []byte, start int) (uint64, int, error) {
	var value uint64
	var shift uint
	offset := start
	for offset < len(data) {
		b := data[offset]
		offset++
		value |= uint64(b&0x7f) << shift
		if b&0x80 == 0 {
			return value, offset, nil
		}
		shift += 7
		if shift > 63 {
			return 0, 0, errors.New("Sparkplug varint is too large")
		}
	}
	return 0, 0, errors.New("Unexpected end of Sparkplug payload")
}

func readLengthDelimited(data []byte, start int) ([]byte, int, error) {
	length, next, err := readVarint(data, start)
	if err != nil {
		return nil, 0, err
	}
	end := next + int(length)
	if end > len(data) {
		return nil, 0, errors.New("Unexpected end of Sparkplug payload")
	}
	return data[next:end], end, nil
}

func readKey(data []byte, start int) (uint64, uint64, int, error) {
	key, next, err := readVarint(data, start)
	if err != nil {
		return 0, 0, 0, err
	}
	return key >> 3, key & 0x07, next, nil
}

func skipField(data []byte, start int, wireType uint64) (int, error) {
	switch wireType {
	case 0:
		_, next, err := readVarint(data, start)
		return next, err
	case 1:
		end := start + 8
		if end > len(data) {
			return 0, errors.New("Unexpected end of Sparkplug payload")
		}
		return end, nil
	case 2:
		_, next, err := readLengthDelimited(data, start)
		return next, err
	case 5:
		end := start + 4
		if end > len(data) {
			return 0, errors.New("Unexpected end of Sparkplug payload")
		}
		return end, nil
	default:
		return 0, fmt.Errorf("Unsupported Sparkplug wire type %d", wireType)
	}
}

func decodeMetric(data []byte) (string, any, bool, error) {
	var name string
	var intValue *int64
	var longValue *int64
	var floatValue *float64
	var doubleValue *float64
	var boolValue *bool
	var stringValue *string

	offset := 0
	for offset < len(data) {
		field, wire, next, err := readKey(data, offset)
		if err != nil {
			return "", nil, false, err
		}
		offset = next
		switch {
		case field == 1 && wire == 2:
			raw, n, err := readLengthDelimited(data, offset)
			if err != nil {
				return "", nil, false, err
			}
			name = string(raw)
			offset = n
		case field == 10 && wire == 0:
			value, n, err := readVarint(data, offset)
			if err != nil {
				return "", nil, false, err
			}
			v := int64(value)
			intValue = &v
			offset = n
		case field == 11 && wire == 0:
			value, n, err := readVarint(data, offset)
			if err != nil {
				return "", nil, false, err
			}
			v := int64(value)
			longValue = &v
			offset = n
		case field == 12 && wire == 5:
			if offset+4 > len(data) {
				return "", nil, false, errors.New("Unexpected end of Sparkplug payload")
			}
			v := float64(math.Float32frombits(binary.LittleEndian.Uint32(data[offset : offset+4])))
			floatValue = &v
			offset += 4
		case field == 13 && wire == 1:
			if offset+8 > len(data) {
				return "", nil, false, errors.New("Unexpected end of Sparkplug payload")
			}
			v := math.Float64frombits(binary.LittleEndian.Uint64(data[offset : offset+8]))
			doubleValue = &v
			offset += 8
		case field == 12 && wire == 0:
			value, n, err := readVarint(data, offset)
			if err != nil {
				return "", nil, false, err
			}
			v := value != 0
			boolValue = &v
			offset = n
		case field == 13 && wire == 2:
			raw, n, err := readLengthDelimited(data, offset)
			if err != nil {
				return "", nil, false, err
			}
			v := string(raw)
			stringValue = &v
			offset = n
		case field == 14 && wire == 0:
			value, n, err := readVarint(data, offset)
			if err != nil {
				return "", nil, false, err
			}
			v := value != 0
			boolValue = &v
			offset = n
		case field == 15 && wire == 2:
			raw, n, err := readLengthDelimited(data, offset)
			if err != nil {
				return "", nil, false, err
			}
			v := string(raw)
			stringValue = &v
			offset = n
		default:
			n, err := skipField(data, offset, wire)
			if err != nil {
				return "", nil, false, err
			}
			offset = n
		}
	}

	if name == "" {
		return "", nil, false, nil
	}
	switch {
	case boolValue != nil:
		return name, *boolValue, true, nil
	case intValue != nil:
		return name, *intValue, true, nil
	case longValue != nil:
		return name, *longValue, true, nil
	case floatValue != nil:
		return name, *floatValue, true, nil
	case doubleValue != nil:
		return name, *doubleValue, true, nil
	case stringValue != nil:
		return name, *stringValue, true, nil
	default:
		return "", nil, false, nil
	}
}

func assignMetricPath(root map[string]any, metricName string, value any) {
	normalized := strings.ReplaceAll(metricName, ".", "/")
	var parts []string
	for _, part := range strings.Split(normalized, "/") {
		if part != "" {
			parts = append(parts, part)
		}
	}
	if len(parts) == 0 {
		return
	}
	current := root
	for _, part := range parts[:len(parts)-1] {
		child, ok := current[part].(map[string]any)
		if !ok {
			child = map[string]any{}
			current[part] = child
		}
		current = child
	}
	current[parts[len(parts)-1]] = value
}

func parseTopic(topic string) (string, string, string, *string, bool) {
	parts := strings.Split(topic, "/")
	if len(parts) != 4 && len(parts) != 5 {
		return "", "", "", nil, false
	}
	if parts[0] != SparkplugNamespace {
		return "", "", "", nil, false
	}
	for _, part := range parts {
		if part == "" {
			return "", "", "", nil, false
		}
	}
	messageType := parts[2]
	if len(parts) == 4 {
		if !nodeMessageTypes[messageType] {
			return "", "", "", nil, false
		}
		return parts[1], messageType, parts[3], nil, true
	}
	if !deviceMessageTypes[messageType] {
		return "", "", "", nil, false
	}
	deviceID := parts[4]
	return parts[1], messageType, parts[3], &deviceID, true
}

func DecodeSparkplugPayload(payloadBase64, mqttTopic string) (*SparkplugMessage, bool) {
	groupID, messageType, edgeNodeID, deviceID, ok := parseTopic(mqttTopic)
	if !ok {
		return nil, false
	}
	payload, err := base64.StdEncoding.DecodeString(payloadBase64)
	if err != nil {
		return nil, false
	}
	var sparkplugTimestamp *int64
	var seq *int64
	metrics := map[string]any{}

	offset := 0
	for offset < len(payload) {
		field, wire, next, err := readKey(payload, offset)
		if err != nil {
			return nil, false
		}
		offset = next
		switch {
		case field == 1 && wire == 0:
			value, n, err := readVarint(payload, offset)
			if err != nil {
				return nil, false
			}
			v := int64(value)
			sparkplugTimestamp = &v
			offset = n
		case field == 2 && wire == 2:
			metricBytes, n, err := readLengthDelimited(payload, offset)
			if err != nil {
				return nil, false
			}
			name, value, ok, err := decodeMetric(metricBytes)
			if err != nil {
				return nil, false
			}
			if ok {
				assignMetricPath(metrics, name, value)
			}
			offset = n
		case field == 3 && wire == 0:
			value, n, err := readVarint(payload, offset)
			if err != nil {
				return nil, false
			}
			v := int64(value)
			seq = &v
			offset = n
		default:
			n, err := skipField(payload, offset, wire)
			if err != nil {
				return nil, false
			}
			offset = n
		}
	}

	return &SparkplugMessage{
		GroupID:            groupID,
		MessageType:        messageType,
		EdgeNodeID:         edgeNodeID,
		DeviceID:           deviceID,
		Seq:                seq,
		SparkplugTimestamp: sparkplugTimestamp,
		Metrics:            metrics,
	}, true
}

func BuildReportedPayload(message *SparkplugMessage, observedAt int64) map[string]any {
	topic := map[string]any{
		"namespace":   SparkplugNamespace,
		"groupId":     message.GroupID,
		"messageType": message.MessageType,
		"edgeNodeId":  message.EdgeNodeID,
	}
	if message.DeviceID != nil {
		topic["deviceId"] = *message.DeviceID
	}
	return map[string]any{
		"topic": topic,
		"payload": map[string]any{
			"timestamp": int64PtrValue(message.SparkplugTimestamp),
			"seq":       int64PtrValue(message.Seq),
			"metrics":   message.Metrics,
		},
		"projection": map[string]any{
			"observedAt": observedAt,
		},
	}
}

func ResolveThingName(ctx context.Context, message *SparkplugMessage, awsClient AWS) (string, error) {
	if message.DeviceID != nil {
		return *message.DeviceID, nil
	}
	town, err := awsClient.DescribeThing(ctx, message.GroupID)
	if err != nil {
		return "", err
	}
	if town.ThingTypeName == nil || *town.ThingTypeName != "town" {
		return "", fmt.Errorf("Sparkplug group id %q does not identify a town thing", message.GroupID)
	}
	rig, err := awsClient.DescribeThing(ctx, message.EdgeNodeID)
	if err != nil {
		return "", err
	}
	if rig.Attributes["kind"] != RigKindAttribute {
		return "", fmt.Errorf("Sparkplug edge node id %q does not identify a rig thing", message.EdgeNodeID)
	}
	if rig.Attributes["townId"] != message.GroupID {
		return "", fmt.Errorf("Rig thing %q is not assigned to town %q", message.EdgeNodeID, message.GroupID)
	}
	return message.EdgeNodeID, nil
}

func reportedMetricsFromShadow(shadow map[string]any) (map[string]any, bool) {
	state, ok := shadow["state"].(map[string]any)
	if !ok {
		return nil, false
	}
	reported, ok := state["reported"].(map[string]any)
	if !ok {
		return nil, false
	}
	payload, ok := reported["payload"].(map[string]any)
	if !ok {
		return nil, false
	}
	metrics, ok := payload["metrics"].(map[string]any)
	return metrics, ok
}

func metricPatchIsNoop(current, patch map[string]any) bool {
	for key, value := range patch {
		currentValue, ok := current[key]
		if !ok {
			return false
		}
		if patchObject, ok := value.(map[string]any); ok {
			currentObject, ok := currentValue.(map[string]any)
			if !ok || !metricPatchIsNoop(currentObject, patchObject) {
				return false
			}
			continue
		}
		if !metricValuesEqual(currentValue, value) {
			return false
		}
	}
	return true
}

func metricValuesEqual(left, right any) bool {
	if left == nil || right == nil {
		return left == nil && right == nil
	}
	if leftNumber, ok := numberAsFloat64(left); ok {
		rightNumber, ok := numberAsFloat64(right)
		return ok && leftNumber == rightNumber
	}
	switch leftValue := left.(type) {
	case bool:
		rightValue, ok := right.(bool)
		return ok && leftValue == rightValue
	case string:
		rightValue, ok := right.(string)
		return ok && leftValue == rightValue
	default:
		return fmt.Sprintf("%v", left) == fmt.Sprintf("%v", right)
	}
}

func prepareMetricPatchForMerge(metrics map[string]any) map[string]any {
	hasCommandResult := false
	for _, key := range commandResultMetricKeys {
		if _, ok := metrics[key]; ok {
			hasCommandResult = true
			break
		}
	}
	if !hasCommandResult {
		return cloneAnyMap(metrics)
	}
	prepared := cloneAnyMap(metrics)
	prepared["commands"] = nil
	if _, ok := prepared["redconCommandMessage"]; !ok {
		prepared["redconCommandMessage"] = nil
	}
	if _, ok := prepared["redconCommandTarget"]; !ok {
		prepared["redconCommandTarget"] = nil
	}
	return prepared
}

func replaceMetrics(ctx context.Context, thingName string, reported map[string]any, awsClient AWS) error {
	if err := awsClient.UpdateSparkplugShadow(ctx, thingName, map[string]any{
		"state": map[string]any{
			"reported": map[string]any{
				"payload": map[string]any{"metrics": nil},
			},
		},
	}); err != nil {
		return err
	}
	return awsClient.UpdateSparkplugShadow(ctx, thingName, map[string]any{
		"state": map[string]any{"reported": reported},
	})
}

func mergeMetrics(ctx context.Context, thingName string, reported map[string]any, awsClient AWS) error {
	payload, _ := reported["payload"].(map[string]any)
	patchMetrics, _ := payload["metrics"].(map[string]any)
	preparedPatch := prepareMetricPatchForMerge(patchMetrics)
	payload["metrics"] = preparedPatch
	if currentShadow, ok, err := awsClient.GetSparkplugShadow(ctx, thingName); err != nil {
		return err
	} else if ok {
		if currentMetrics, ok := reportedMetricsFromShadow(currentShadow); ok && metricPatchIsNoop(currentMetrics, preparedPatch) {
			return nil
		}
	}
	return awsClient.UpdateSparkplugShadow(ctx, thingName, map[string]any{
		"state": map[string]any{"reported": reported},
	})
}

func ProjectSparkplugMessage(ctx context.Context, message *SparkplugMessage, observedAt int64, awsClient AWS) (string, error) {
	thingName, err := ResolveThingName(ctx, message, awsClient)
	if err != nil {
		return "", err
	}
	reported := BuildReportedPayload(message, observedAt)
	if replaceMetricsMessageTypes[message.MessageType] || clearMetricsMessageTypes[message.MessageType] {
		return thingName, replaceMetrics(ctx, thingName, reported, awsClient)
	}
	if mergeMetricsMessageTypes[message.MessageType] {
		return thingName, mergeMetrics(ctx, thingName, reported, awsClient)
	}
	return "ignored", nil
}

func HandleLambdaEvent(ctx context.Context, event map[string]any, awsClient AWS) (map[string]any, error) {
	mqttTopic, mqttOK := event["mqttTopic"].(string)
	payloadBase64, payloadOK := event["payloadBase64"].(string)
	if !mqttOK || mqttTopic == "" || !payloadOK {
		return map[string]any{"status": "ignored", "reason": "malformed-event"}, nil
	}
	observedAt := numberAsInt64(event["observedAt"])
	message, ok := DecodeSparkplugPayload(payloadBase64, mqttTopic)
	if !ok {
		return map[string]any{"status": "ignored", "reason": "unsupported-topic"}, nil
	}
	thingName, err := ProjectSparkplugMessage(ctx, message, observedAt, awsClient)
	if err != nil {
		return nil, err
	}
	return map[string]any{"status": "ok", "thingName": thingName}, nil
}

func int64PtrValue(value *int64) any {
	if value == nil {
		return nil
	}
	return *value
}

func numberAsInt64(value any) int64 {
	switch v := value.(type) {
	case int:
		return int64(v)
	case int64:
		return v
	case float64:
		return int64(v)
	case json.Number:
		n, _ := v.Int64()
		return n
	default:
		return 0
	}
}

func numberAsFloat64(value any) (float64, bool) {
	switch v := value.(type) {
	case int:
		return float64(v), true
	case int8:
		return float64(v), true
	case int16:
		return float64(v), true
	case int32:
		return float64(v), true
	case int64:
		return float64(v), true
	case uint:
		return float64(v), true
	case uint8:
		return float64(v), true
	case uint16:
		return float64(v), true
	case uint32:
		return float64(v), true
	case uint64:
		return float64(v), true
	case float32:
		return float64(v), true
	case float64:
		return v, true
	case json.Number:
		n, err := v.Float64()
		return n, err == nil
	default:
		return 0, false
	}
}

func cloneStringMap(input map[string]string) map[string]string {
	out := make(map[string]string, len(input))
	for key, value := range input {
		out[key] = value
	}
	return out
}

func cloneAnyMap(input map[string]any) map[string]any {
	out := make(map[string]any, len(input))
	for key, value := range input {
		if child, ok := value.(map[string]any); ok {
			out[key] = cloneAnyMap(child)
		} else {
			out[key] = value
		}
	}
	return out
}
