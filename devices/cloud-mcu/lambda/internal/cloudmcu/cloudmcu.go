package cloudmcu

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"hash/fnv"
	"os"
	"sort"
	"strings"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/service/ecs"
	ecstypes "github.com/aws/aws-sdk-go-v2/service/ecs/types"
	"github.com/aws/aws-sdk-go-v2/service/iot"
	"github.com/aws/aws-sdk-go-v2/service/iotdataplane"
	"github.com/aws/aws-sdk-go-v2/service/sqs"
	sqstypes "github.com/aws/aws-sdk-go-v2/service/sqs/types"
)

const (
	CloudMcuThingType      = "cloud-mcu"
	CloudRigThingType      = "cloud"
	ThingIndexName         = "AWS_Things"
	CloudMcuSearchQuery    = "thingTypeName:cloud-mcu"
	CloudMcuSearchPageSize = int32(100)
	SparkplugNamespace     = "spBv1.0"
	CapabilitySparkplug    = "sparkplug"
	CapabilitySQS          = "sqs"
	CapabilityPower        = "power"
	CapabilityECS          = "ecs"
	RedconReady            = uint8(1)
	RedconWakeup           = uint8(3)
	RedconSleep            = uint8(4)
	NodeBdSeq              = uint64(1)
	CommandSucceeded       = "succeeded"
	CommandFailed          = "failed"
	ECSStartedByPrefix     = "txing-cloud-mcu"
)

var TickOffsetsSeconds = []int32{0, 6, 12, 18, 24, 30, 36, 42, 48, 54}

type CloudMcuDevice struct {
	ThingName string
	TownID    string
	RigID     string
}

type SearchPage struct {
	Devices   []CloudMcuDevice
	NextToken *string
}

type ThingDescription struct {
	ThingTypeName *string
	Attributes    map[string]string
}

type CloudMcuTick struct {
	SchemaVersion     string `json:"schemaVersion"`
	ThingName         string `json:"thingName"`
	TownID            string `json:"townId"`
	RigID             string `json:"rigId"`
	TickOffsetSeconds int32  `json:"tickOffsetSeconds"`
	ScheduledAtMs     int64  `json:"scheduledAtMs"`
}

func NewTick(device CloudMcuDevice, offset int32, scheduledAtMs int64) CloudMcuTick {
	return CloudMcuTick{
		SchemaVersion:     "1.0",
		ThingName:         device.ThingName,
		TownID:            device.TownID,
		RigID:             device.RigID,
		TickOffsetSeconds: offset,
		ScheduledAtMs:     scheduledAtMs,
	}
}

func (t CloudMcuTick) Validate() error {
	if t.SchemaVersion != "1.0" {
		return errors.New("cloud MCU tick schemaVersion must be 1.0")
	}
	if _, err := Segment(t.ThingName, "thingName"); err != nil {
		return err
	}
	if _, err := Segment(t.TownID, "townId"); err != nil {
		return err
	}
	if _, err := Segment(t.RigID, "rigId"); err != nil {
		return err
	}
	for _, offset := range TickOffsetsSeconds {
		if t.TickOffsetSeconds == offset {
			return nil
		}
	}
	return errors.New("tickOffsetSeconds must be one of 0,6,...,54")
}

type EcsTaskState struct {
	TaskARN    string
	LastStatus *string
}

func (s EcsTaskState) IsActive() bool {
	if s.LastStatus == nil {
		return true
	}
	return *s.LastStatus != "STOPPED" && *s.LastStatus != "DEPROVISIONING"
}

type AWSClientAPI interface {
	SearchCloudMcuDevices(ctx context.Context, nextToken *string) (SearchPage, error)
	DescribeThing(ctx context.Context, thingName string) (ThingDescription, error)
	Publish(ctx context.Context, topic string, payload []byte) error
	SendTickBatch(ctx context.Context, ticks []CloudMcuTick) error
	GetThingShadow(ctx context.Context, thingName, shadowName string) ([]byte, bool, error)
	UpdateThingShadow(ctx context.Context, thingName, shadowName string, payload []byte) error
	ListDeviceTasks(ctx context.Context, thingName string) ([]EcsTaskState, error)
	DescribeTask(ctx context.Context, taskARN string) (*EcsTaskState, error)
	RunTask(ctx context.Context, thingName, rigID string) (EcsTaskState, error)
	StopTask(ctx context.Context, taskARN string) error
}

type AWSClient struct {
	iot               *iot.Client
	iotData           *iotdataplane.Client
	sqs               *sqs.Client
	ecs               *ecs.Client
	tickQueueURL      string
	ecsCluster        string
	ecsTaskDefinition string
	ecsSubnets        []string
	ecsSecurityGroups []string
}

func NewAWSClient(ctx context.Context) (*AWSClient, error) {
	cfg, err := config.LoadDefaultConfig(ctx)
	if err != nil {
		return nil, err
	}
	iotClient := iot.NewFromConfig(cfg)
	endpoint, err := iotClient.DescribeEndpoint(ctx, &iot.DescribeEndpointInput{EndpointType: aws.String("iot:Data-ATS")})
	if err != nil {
		return nil, fmt.Errorf("describe AWS IoT data endpoint: %w", err)
	}
	if endpoint.EndpointAddress == nil || strings.TrimSpace(*endpoint.EndpointAddress) == "" {
		return nil, errors.New("AWS IoT describe_endpoint returned no endpointAddress")
	}
	iotData := iotdataplane.NewFromConfig(cfg, func(options *iotdataplane.Options) {
		options.BaseEndpoint = aws.String("https://" + strings.TrimSpace(*endpoint.EndpointAddress))
	})
	return &AWSClient{
		iot:               iotClient,
		iotData:           iotData,
		sqs:               sqs.NewFromConfig(cfg),
		ecs:               ecs.NewFromConfig(cfg),
		tickQueueURL:      envNonempty("CLOUD_MCU_TICK_QUEUE_URL"),
		ecsCluster:        envNonempty("CLOUD_MCU_ECS_CLUSTER"),
		ecsTaskDefinition: envNonempty("CLOUD_MCU_ECS_TASK_DEFINITION"),
		ecsSubnets:        envCSV("CLOUD_MCU_ECS_SUBNETS"),
		ecsSecurityGroups: envCSV("CLOUD_MCU_ECS_SECURITY_GROUPS"),
	}, nil
}

func (c *AWSClient) requiredTickQueueURL() (string, error) {
	if c.tickQueueURL == "" {
		return "", errors.New("CLOUD_MCU_TICK_QUEUE_URL is required")
	}
	return c.tickQueueURL, nil
}

func (c *AWSClient) requiredECSCluster() (string, error) {
	if c.ecsCluster == "" {
		return "", errors.New("CLOUD_MCU_ECS_CLUSTER is required")
	}
	return c.ecsCluster, nil
}

func (c *AWSClient) requiredECSTaskDefinition() (string, error) {
	if c.ecsTaskDefinition == "" {
		return "", errors.New("CLOUD_MCU_ECS_TASK_DEFINITION is required")
	}
	return c.ecsTaskDefinition, nil
}

func (c *AWSClient) SearchCloudMcuDevices(ctx context.Context, nextToken *string) (SearchPage, error) {
	out, err := c.iot.SearchIndex(ctx, &iot.SearchIndexInput{
		IndexName:   aws.String(ThingIndexName),
		QueryString: aws.String(CloudMcuSearchQuery),
		MaxResults:  aws.Int32(CloudMcuSearchPageSize),
		NextToken:   nextToken,
	})
	if err != nil {
		return SearchPage{}, err
	}
	var devices []CloudMcuDevice
	for _, thing := range out.Things {
		if thing.ThingName == nil || strings.TrimSpace(*thing.ThingName) == "" {
			continue
		}
		townID := strings.TrimSpace(thing.Attributes["townId"])
		rigID := strings.TrimSpace(thing.Attributes["rigId"])
		if townID == "" || rigID == "" {
			continue
		}
		devices = append(devices, CloudMcuDevice{ThingName: strings.TrimSpace(*thing.ThingName), TownID: townID, RigID: rigID})
	}
	return SearchPage{Devices: devices, NextToken: blankPtrToNil(out.NextToken)}, nil
}

func (c *AWSClient) DescribeThing(ctx context.Context, thingName string) (ThingDescription, error) {
	out, err := c.iot.DescribeThing(ctx, &iot.DescribeThingInput{ThingName: aws.String(thingName)})
	if err != nil {
		return ThingDescription{}, err
	}
	return ThingDescription{ThingTypeName: out.ThingTypeName, Attributes: cloneStringMap(out.Attributes)}, nil
}

func (c *AWSClient) Publish(ctx context.Context, topic string, payload []byte) error {
	_, err := c.iotData.Publish(ctx, &iotdataplane.PublishInput{Topic: aws.String(topic), Qos: 1, Payload: payload})
	return err
}

func (c *AWSClient) SendTickBatch(ctx context.Context, ticks []CloudMcuTick) error {
	if len(ticks) == 0 {
		return errors.New("cloud MCU tick batch must not be empty")
	}
	queueURL, err := c.requiredTickQueueURL()
	if err != nil {
		return err
	}
	entries := make([]sqstypes.SendMessageBatchRequestEntry, 0, len(ticks))
	for _, tick := range ticks {
		if err := tick.Validate(); err != nil {
			return err
		}
		body, err := json.Marshal(tick)
		if err != nil {
			return err
		}
		entries = append(entries, sqstypes.SendMessageBatchRequestEntry{
			Id:           aws.String(fmt.Sprintf("tick-%d", tick.TickOffsetSeconds)),
			DelaySeconds: tick.TickOffsetSeconds,
			MessageBody:  aws.String(string(body)),
		})
	}
	out, err := c.sqs.SendMessageBatch(ctx, &sqs.SendMessageBatchInput{QueueUrl: aws.String(queueURL), Entries: entries})
	if err != nil {
		return err
	}
	if len(out.Failed) > 0 {
		var failures []string
		for _, failure := range out.Failed {
			failures = append(failures, fmt.Sprintf("%s:%s:%s", stringPtr(failure.Id), stringPtr(failure.Code), stringPtr(failure.Message)))
		}
		return fmt.Errorf("cloud MCU SQS tick batch had failed entries: %s", strings.Join(failures, ","))
	}
	return nil
}

func (c *AWSClient) GetThingShadow(ctx context.Context, thingName, shadowName string) ([]byte, bool, error) {
	out, err := c.iotData.GetThingShadow(ctx, &iotdataplane.GetThingShadowInput{ThingName: aws.String(thingName), ShadowName: aws.String(shadowName)})
	if err != nil {
		if errorIsNotFound(err) {
			return nil, false, nil
		}
		return nil, false, err
	}
	return out.Payload, out.Payload != nil, nil
}

func (c *AWSClient) UpdateThingShadow(ctx context.Context, thingName, shadowName string, payload []byte) error {
	_, err := c.iotData.UpdateThingShadow(ctx, &iotdataplane.UpdateThingShadowInput{ThingName: aws.String(thingName), ShadowName: aws.String(shadowName), Payload: payload})
	return err
}

func (c *AWSClient) ListDeviceTasks(ctx context.Context, thingName string) ([]EcsTaskState, error) {
	cluster, err := c.requiredECSCluster()
	if err != nil {
		return nil, err
	}
	startedBy, err := ECSStartedBy(thingName)
	if err != nil {
		return nil, err
	}
	var taskARNs []string
	var next *string
	for {
		out, err := c.ecs.ListTasks(ctx, &ecs.ListTasksInput{Cluster: aws.String(cluster), StartedBy: aws.String(startedBy), NextToken: next})
		if err != nil {
			return nil, err
		}
		taskARNs = append(taskARNs, out.TaskArns...)
		next = out.NextToken
		if next == nil {
			break
		}
	}
	var tasks []EcsTaskState
	for start := 0; start < len(taskARNs); start += 100 {
		end := start + 100
		if end > len(taskARNs) {
			end = len(taskARNs)
		}
		out, err := c.ecs.DescribeTasks(ctx, &ecs.DescribeTasksInput{Cluster: aws.String(cluster), Tasks: taskARNs[start:end]})
		if err != nil {
			return nil, err
		}
		for _, task := range out.Tasks {
			if state, ok := taskStateFromAWSTask(task); ok {
				tasks = append(tasks, state)
			}
		}
	}
	return tasks, nil
}

func (c *AWSClient) DescribeTask(ctx context.Context, taskARN string) (*EcsTaskState, error) {
	cluster, err := c.requiredECSCluster()
	if err != nil {
		return nil, err
	}
	out, err := c.ecs.DescribeTasks(ctx, &ecs.DescribeTasksInput{Cluster: aws.String(cluster), Tasks: []string{taskARN}})
	if err != nil {
		return nil, err
	}
	if len(out.Tasks) == 0 {
		return nil, nil
	}
	state, ok := taskStateFromAWSTask(out.Tasks[0])
	if !ok {
		return nil, nil
	}
	return &state, nil
}

func (c *AWSClient) RunTask(ctx context.Context, thingName, rigID string) (EcsTaskState, error) {
	cluster, err := c.requiredECSCluster()
	if err != nil {
		return EcsTaskState{}, err
	}
	taskDefinition, err := c.requiredECSTaskDefinition()
	if err != nil {
		return EcsTaskState{}, err
	}
	if len(c.ecsSubnets) == 0 {
		return EcsTaskState{}, errors.New("CLOUD_MCU_ECS_SUBNETS is required")
	}
	if len(c.ecsSecurityGroups) == 0 {
		return EcsTaskState{}, errors.New("CLOUD_MCU_ECS_SECURITY_GROUPS is required")
	}
	startedBy, err := ECSStartedBy(thingName)
	if err != nil {
		return EcsTaskState{}, err
	}
	out, err := c.ecs.RunTask(ctx, &ecs.RunTaskInput{
		Cluster:        aws.String(cluster),
		TaskDefinition: aws.String(taskDefinition),
		LaunchType:     ecstypes.LaunchTypeFargate,
		NetworkConfiguration: &ecstypes.NetworkConfiguration{AwsvpcConfiguration: &ecstypes.AwsVpcConfiguration{
			Subnets:        append([]string(nil), c.ecsSubnets...),
			SecurityGroups: append([]string(nil), c.ecsSecurityGroups...),
			AssignPublicIp: ecstypes.AssignPublicIpDisabled,
		}},
		Count:     aws.Int32(1),
		StartedBy: aws.String(startedBy),
		Tags: []ecstypes.Tag{
			{Key: aws.String("txing:thingName"), Value: aws.String(thingName)},
			{Key: aws.String("txing:rigId"), Value: aws.String(rigID)},
		},
	})
	if err != nil {
		return EcsTaskState{}, err
	}
	for _, task := range out.Tasks {
		if state, ok := taskStateFromAWSTask(task); ok {
			return state, nil
		}
	}
	return EcsTaskState{}, errors.New("ECS RunTask returned no task ARN")
}

func (c *AWSClient) StopTask(ctx context.Context, taskARN string) error {
	cluster, err := c.requiredECSCluster()
	if err != nil {
		return err
	}
	_, err = c.ecs.StopTask(ctx, &ecs.StopTaskInput{Cluster: aws.String(cluster), Task: aws.String(taskARN), Reason: aws.String("txing cloud MCU REDCON 4")})
	return err
}

func taskStateFromAWSTask(task ecstypes.Task) (EcsTaskState, bool) {
	if task.TaskArn == nil {
		return EcsTaskState{}, false
	}
	return EcsTaskState{TaskARN: *task.TaskArn, LastStatus: task.LastStatus}, true
}

func ECSStartedBy(thingName string) (string, error) {
	segment, err := Segment(thingName, "thingName")
	if err != nil {
		return "", err
	}
	var sanitized strings.Builder
	for _, ch := range segment {
		if sanitized.Len() >= 80 {
			break
		}
		if ch >= 'a' && ch <= 'z' || ch >= 'A' && ch <= 'Z' || ch >= '0' && ch <= '9' || ch == '-' || ch == '_' {
			sanitized.WriteRune(ch)
		} else {
			sanitized.WriteByte('_')
		}
	}
	hash := fnv.New64a()
	_, _ = hash.Write([]byte(segment))
	return fmt.Sprintf("%s-%s-%016x", ECSStartedByPrefix, sanitized.String(), hash.Sum64()), nil
}

func errorIsNotFound(err error) bool {
	text := fmt.Sprintf("%#v %v", err, err)
	return strings.Contains(text, "ResourceNotFoundException") || strings.Contains(text, "NotFoundException")
}

func envNonempty(name string) string {
	return strings.TrimSpace(os.Getenv(name))
}

func envCSV(name string) []string {
	var values []string
	for _, raw := range strings.Split(os.Getenv(name), ",") {
		if value := strings.TrimSpace(raw); value != "" {
			values = append(values, value)
		}
	}
	return values
}

func UTCNowMs() int64 {
	return time.Now().UTC().UnixMilli()
}

func Segment(value, fieldName string) (string, error) {
	text := strings.TrimSpace(value)
	if text == "" {
		return "", fmt.Errorf("%s must not be empty", fieldName)
	}
	if strings.ContainsAny(text, "/+#") {
		return "", fmt.Errorf("%s must be a literal MQTT segment", fieldName)
	}
	return text, nil
}

func BuildNodeTopic(townID, messageType, rigID string) (string, error) {
	townID, err := Segment(townID, "townId")
	if err != nil {
		return "", err
	}
	messageType, err = Segment(messageType, "messageType")
	if err != nil {
		return "", err
	}
	rigID, err = Segment(rigID, "rigId")
	if err != nil {
		return "", err
	}
	return fmt.Sprintf("%s/%s/%s/%s", SparkplugNamespace, townID, messageType, rigID), nil
}

func BuildDeviceTopic(townID, messageType, rigID, thingName string) (string, error) {
	townID, err := Segment(townID, "townId")
	if err != nil {
		return "", err
	}
	messageType, err = Segment(messageType, "messageType")
	if err != nil {
		return "", err
	}
	rigID, err = Segment(rigID, "rigId")
	if err != nil {
		return "", err
	}
	thingName, err = Segment(thingName, "thingName")
	if err != nil {
		return "", err
	}
	return fmt.Sprintf("%s/%s/%s/%s/%s", SparkplugNamespace, townID, messageType, rigID, thingName), nil
}

type metricValue struct {
	kind string
	i32  int32
	u64  uint64
	b    bool
	s    string
}

type metric struct {
	name  string
	value metricValue
}

func int32Metric(name string, value int32) metric {
	return metric{name: name, value: metricValue{kind: "int32", i32: value}}
}
func uint64Metric(name string, value uint64) metric {
	return metric{name: name, value: metricValue{kind: "uint64", u64: value}}
}
func boolMetric(name string, value bool) metric {
	return metric{name: name, value: metricValue{kind: "bool", b: value}}
}
func stringMetric(name string, value string) metric {
	return metric{name: name, value: metricValue{kind: "string", s: value}}
}

func BuildNodeBirthPayload(seq uint64, timestamp int64) ([]byte, error) {
	return encodePayload(uint64(timestamp), &seq, []metric{uint64Metric("bdSeq", NodeBdSeq), int32Metric("redcon", int32(RedconReady))})
}

func buildDeviceReportPayload(redcon uint8, seq uint64, timestamp int64, metrics []metric) ([]byte, error) {
	all := []metric{int32Metric("redcon", int32(redcon))}
	all = append(all, metrics...)
	return encodePayload(uint64(timestamp), &seq, all)
}

func buildCapabilityMetrics(power bool) []metric {
	return []metric{
		boolMetric("capability."+CapabilitySparkplug, true),
		boolMetric("capability."+CapabilitySQS, true),
		boolMetric("capability."+CapabilityPower, power),
		boolMetric("capability."+CapabilityECS, false),
	}
}

func buildCommandResultMetrics(seq uint64, targetRedcon uint8, status string, message string) []metric {
	metrics := []metric{
		stringMetric("redconCommandStatus", status),
		int32Metric("redconCommandSeq", int32(seq)),
		stringMetric("redconCommandId", fmt.Sprintf("dcmd-%d", seq)),
		int32Metric("redconCommandTarget", int32(targetRedcon)),
	}
	if message != "" {
		metrics = append(metrics, stringMetric("redconCommandMessage", message))
	}
	return metrics
}

func encodePayload(timestamp uint64, seq *uint64, metrics []metric) ([]byte, error) {
	var out []byte
	appendVarintField(&out, 1, timestamp)
	for _, metric := range metrics {
		encoded, err := encodeMetric(metric)
		if err != nil {
			return nil, err
		}
		appendBytesField(&out, 2, encoded)
	}
	if seq != nil {
		appendVarintField(&out, 3, *seq)
	}
	return out, nil
}

func encodeMetric(metric metric) ([]byte, error) {
	var out []byte
	appendStringField(&out, 1, metric.name)
	switch metric.value.kind {
	case "int32":
		appendVarintField(&out, 4, 3)
		appendVarintField(&out, 10, uint64(metric.value.i32))
	case "uint64":
		appendVarintField(&out, 4, 8)
		appendVarintField(&out, 11, metric.value.u64)
	case "bool":
		appendVarintField(&out, 4, 11)
		if metric.value.b {
			appendVarintField(&out, 14, 1)
		} else {
			appendVarintField(&out, 14, 0)
		}
	case "string":
		appendVarintField(&out, 4, 12)
		appendStringField(&out, 15, metric.value.s)
	default:
		return nil, fmt.Errorf("unsupported metric kind %q", metric.value.kind)
	}
	return out, nil
}

func appendKey(out *[]byte, field, wire uint64) { appendVarint(out, (field<<3)|wire) }
func appendVarintField(out *[]byte, field, value uint64) {
	appendKey(out, field, 0)
	appendVarint(out, value)
}
func appendStringField(out *[]byte, field uint64, value string) {
	appendBytesField(out, field, []byte(value))
}
func appendBytesField(out *[]byte, field uint64, value []byte) {
	appendKey(out, field, 2)
	appendVarint(out, uint64(len(value)))
	*out = append(*out, value...)
}
func appendVarint(out *[]byte, value uint64) {
	for {
		next := byte(value & 0x7f)
		value >>= 7
		if value == 0 {
			*out = append(*out, next)
			return
		}
		*out = append(*out, next|0x80)
	}
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
	return key >> 3, key & 0x07, next, err
}

func skipField(data []byte, start int, wire uint64) (int, error) {
	switch wire {
	case 0:
		_, next, err := readVarint(data, start)
		return next, err
	case 1:
		if start+8 > len(data) {
			return 0, errors.New("Unexpected end of Sparkplug payload")
		}
		return start + 8, nil
	case 2:
		_, next, err := readLengthDelimited(data, start)
		return next, err
	case 5:
		if start+4 > len(data) {
			return 0, errors.New("Unexpected end of Sparkplug payload")
		}
		return start + 4, nil
	default:
		return 0, fmt.Errorf("Unsupported Sparkplug wire type %d", wire)
	}
}

func decodeRedconCommand(payload []byte) (uint8, uint64, bool, error) {
	offset := 0
	var seq uint64
	var redcon *uint8
	for offset < len(payload) {
		field, wire, next, err := readKey(payload, offset)
		if err != nil {
			return 0, 0, false, err
		}
		offset = next
		switch {
		case field == 2 && wire == 2:
			metricBytes, n, err := readLengthDelimited(payload, offset)
			if err != nil {
				return 0, 0, false, err
			}
			offset = n
			if redcon == nil {
				if value, ok, err := decodeRedconMetric(metricBytes); err != nil {
					return 0, 0, false, err
				} else if ok {
					redcon = &value
				}
			}
		case field == 3 && wire == 0:
			value, n, err := readVarint(payload, offset)
			if err != nil {
				return 0, 0, false, err
			}
			seq = value
			offset = n
		default:
			n, err := skipField(payload, offset, wire)
			if err != nil {
				return 0, 0, false, err
			}
			offset = n
		}
	}
	if redcon == nil {
		return 0, 0, false, nil
	}
	return *redcon, seq, true, nil
}

func decodeRedconMetric(data []byte) (uint8, bool, error) {
	offset := 0
	var name string
	var value *int32
	for offset < len(data) {
		field, wire, next, err := readKey(data, offset)
		if err != nil {
			return 0, false, err
		}
		offset = next
		switch {
		case field == 1 && wire == 2:
			raw, n, err := readLengthDelimited(data, offset)
			if err != nil {
				return 0, false, err
			}
			name = string(raw)
			offset = n
		case field == 10 && wire == 0:
			raw, n, err := readVarint(data, offset)
			if err != nil {
				return 0, false, err
			}
			v := int32(raw)
			value = &v
			offset = n
		default:
			n, err := skipField(data, offset, wire)
			if err != nil {
				return 0, false, err
			}
			offset = n
		}
	}
	if name != "redcon" || value == nil || *value < 1 || *value > 4 {
		return 0, false, nil
	}
	return uint8(*value), true, nil
}

type pendingCommand struct {
	Seq          uint64
	TargetRedcon uint8
}

type powerState struct {
	DesiredRedcon uint8
	Powered       bool
	ECSTaskARN    *string
	ECSTaskStatus *string
	Pending       *pendingCommand
	SparkplugBorn bool
}

func defaultPowerState() powerState {
	return powerState{DesiredRedcon: RedconSleep}
}

func powerStateFromShadow(payload []byte, ok bool) (powerState, error) {
	if !ok {
		return defaultPowerState(), nil
	}
	var decoded map[string]any
	if err := json.Unmarshal(payload, &decoded); err != nil {
		return powerState{}, err
	}
	stateObject, _ := decoded["state"].(map[string]any)
	reported, ok := stateObject["reported"].(map[string]any)
	if !ok {
		return defaultPowerState(), nil
	}
	state := defaultPowerState()
	if numberAsUint64(reported["desiredRedcon"]) == uint64(RedconWakeup) {
		state.DesiredRedcon = RedconWakeup
	}
	if powered, ok := reported["powered"].(bool); ok {
		state.Powered = powered
	}
	if taskARN, ok := reported["ecsTaskArn"].(string); ok && strings.TrimSpace(taskARN) != "" {
		state.ECSTaskARN = aws.String(strings.TrimSpace(taskARN))
	}
	if status, ok := reported["ecsTaskStatus"].(string); ok && strings.TrimSpace(status) != "" {
		state.ECSTaskStatus = aws.String(strings.TrimSpace(status))
	}
	if pending, ok := reported["pendingCommand"].(map[string]any); ok {
		seq := numberAsUint64(pending["seq"])
		target := numberAsUint64(pending["targetRedcon"])
		if target == uint64(RedconWakeup) || target == uint64(RedconSleep) {
			state.Pending = &pendingCommand{Seq: seq, TargetRedcon: uint8(target)}
		}
	}
	if born, ok := reported["sparkplugBorn"].(bool); ok {
		state.SparkplugBorn = born
	}
	return state, nil
}

func (s powerState) shadowUpdate() map[string]any {
	var pending any
	if s.Pending != nil {
		pending = map[string]any{"seq": s.Pending.Seq, "targetRedcon": s.Pending.TargetRedcon}
	}
	return map[string]any{"state": map[string]any{"reported": map[string]any{
		"desiredRedcon":  s.DesiredRedcon,
		"powered":        s.Powered,
		"ecsTaskArn":     stringPtrValue(s.ECSTaskARN),
		"ecsTaskStatus":  stringPtrValue(s.ECSTaskStatus),
		"pendingCommand": pending,
		"sparkplugBorn":  s.SparkplugBorn,
	}}}
}

type RigScheduler struct{ aws AWSClientAPI }

func NewRigScheduler(aws AWSClientAPI) RigScheduler { return RigScheduler{aws: aws} }

func (s RigScheduler) HandleScheduleWithNow(ctx context.Context, nowMs int64) (map[string]any, error) {
	devices, err := discoverCloudMcuDevices(ctx, s.aws)
	if err != nil {
		return nil, err
	}
	rigSet := map[string]CloudMcuDevice{}
	for _, device := range devices {
		rigSet[device.TownID+"\x00"+device.RigID] = device
	}
	var rigKeys []string
	for key := range rigSet {
		rigKeys = append(rigKeys, key)
	}
	sort.Strings(rigKeys)
	var publishedRigs []any
	for _, key := range rigKeys {
		device := rigSet[key]
		topic, err := BuildNodeTopic(device.TownID, "NBIRTH", device.RigID)
		if err != nil {
			return nil, err
		}
		seq := uint64(0)
		if nowMs > 0 {
			seq = uint64(nowMs / 60000)
		}
		payload, err := BuildNodeBirthPayload(seq, nowMs)
		if err != nil {
			return nil, err
		}
		if err := s.aws.Publish(ctx, topic, payload); err != nil {
			return nil, err
		}
		publishedRigs = append(publishedRigs, map[string]any{"townId": device.TownID, "rigId": device.RigID})
	}
	sentTicks := 0
	sentBatches := 0
	for _, device := range devices {
		ticks := make([]CloudMcuTick, 0, len(TickOffsetsSeconds))
		for _, offset := range TickOffsetsSeconds {
			ticks = append(ticks, NewTick(device, offset, nowMs))
		}
		if err := s.aws.SendTickBatch(ctx, ticks); err != nil {
			return nil, err
		}
		sentBatches++
		sentTicks += len(ticks)
	}
	return map[string]any{"eventType": "schedule", "deviceCount": len(devices), "rigCount": len(rigKeys), "tickCount": sentTicks, "batchCount": sentBatches, "publishedRigs": publishedRigs}, nil
}

func discoverCloudMcuDevices(ctx context.Context, awsClient AWSClientAPI) ([]CloudMcuDevice, error) {
	var devices []CloudMcuDevice
	var next *string
	for {
		page, err := awsClient.SearchCloudMcuDevices(ctx, next)
		if err != nil {
			return nil, err
		}
		devices = append(devices, page.Devices...)
		next = page.NextToken
		if next == nil {
			sort.Slice(devices, func(i, j int) bool { return devices[i].ThingName < devices[j].ThingName })
			return devices, nil
		}
	}
}

type Runtime struct{ aws AWSClientAPI }

func NewRuntime(aws AWSClientAPI) Runtime { return Runtime{aws: aws} }

func (r Runtime) HandleTickWithNow(ctx context.Context, tick CloudMcuTick, nowMs int64) (map[string]any, error) {
	if err := tick.Validate(); err != nil {
		return nil, err
	}
	if err := r.validateDeviceIdentity(ctx, tick.ThingName, tick.TownID, tick.RigID); err != nil {
		return nil, err
	}
	shadow, ok, err := r.aws.GetThingShadow(ctx, tick.ThingName, CapabilityPower)
	if err != nil {
		return nil, err
	}
	power, err := powerStateFromShadow(shadow, ok)
	if err != nil {
		return nil, err
	}
	actualRedcon := RedconSleep
	if power.DesiredRedcon == RedconWakeup {
		if err := r.ensureTaskRunning(ctx, tick, &power); err != nil {
			return nil, err
		}
		if power.Powered {
			actualRedcon = RedconWakeup
		}
	} else if err := r.ensureTaskStopped(ctx, tick, &power); err != nil {
		return nil, err
	}
	if err := r.updateSQSShadow(ctx, tick); err != nil {
		return nil, err
	}
	extraMetrics := buildCapabilityMetrics(actualRedcon == RedconWakeup)
	var commandResult any
	if power.Pending != nil && power.Pending.TargetRedcon == actualRedcon {
		pending := power.Pending
		power.Pending = nil
		extraMetrics = append(extraMetrics, buildCommandResultMetrics(pending.Seq, pending.TargetRedcon, CommandSucceeded, "")...)
		commandResult = map[string]any{"seq": pending.Seq, "targetRedcon": pending.TargetRedcon, "status": CommandSucceeded}
	}
	messageType := "DBIRTH"
	if power.SparkplugBorn {
		messageType = "DDATA"
	}
	topic, err := BuildDeviceTopic(tick.TownID, messageType, tick.RigID, tick.ThingName)
	if err != nil {
		return nil, err
	}
	payload, err := buildDeviceReportPayload(actualRedcon, uint64(tick.TickOffsetSeconds), nowMs, extraMetrics)
	if err != nil {
		return nil, err
	}
	if err := r.aws.Publish(ctx, topic, payload); err != nil {
		return nil, err
	}
	power.SparkplugBorn = true
	if err := r.updatePowerShadow(ctx, tick.ThingName, power); err != nil {
		return nil, err
	}
	return map[string]any{"eventType": "sqsTick", "thingName": tick.ThingName, "redcon": actualRedcon, "messageType": messageType, "powered": power.Powered, "ecsTaskArn": stringPtrValue(power.ECSTaskARN), "commandResult": commandResult}, nil
}

func (r Runtime) HandleDCMDWithNow(ctx context.Context, event map[string]any, nowMs int64) (map[string]any, error) {
	topic, ok := event["mqttTopic"].(string)
	if !ok {
		return nil, errors.New("DCMD event is missing mqttTopic")
	}
	townID, rigID, thingName, ok := parseDCMDTopic(topic)
	if !ok {
		return nil, fmt.Errorf("unsupported DCMD topic: %s", topic)
	}
	if err := r.validateDeviceIdentity(ctx, thingName, townID, rigID); err != nil {
		return nil, err
	}
	payload, err := decodeEventPayload(event)
	if err != nil {
		return nil, fmt.Errorf("decode DCMD payload: %w", err)
	}
	redcon, seq, ok, err := decodeRedconCommand(payload)
	if err != nil {
		return nil, err
	}
	if !ok {
		return map[string]any{"eventType": "dcmd", "thingName": thingName, "status": "ignored"}, nil
	}
	if redcon != RedconWakeup && redcon != RedconSleep {
		topic, err := BuildDeviceTopic(townID, "DDATA", rigID, thingName)
		if err != nil {
			return nil, err
		}
		metrics := buildCapabilityMetrics(false)
		metrics = append(metrics, buildCommandResultMetrics(seq, redcon, CommandFailed, "cloud-mcu supports REDCON 3 and 4 only")...)
		payload, err := buildDeviceReportPayload(RedconSleep, seq, nowMs, metrics)
		if err != nil {
			return nil, err
		}
		if err := r.aws.Publish(ctx, topic, payload); err != nil {
			return nil, err
		}
		return map[string]any{"eventType": "dcmd", "thingName": thingName, "status": CommandFailed, "targetRedcon": redcon}, nil
	}
	shadow, shadowOK, err := r.aws.GetThingShadow(ctx, thingName, CapabilityPower)
	if err != nil {
		return nil, err
	}
	power, err := powerStateFromShadow(shadow, shadowOK)
	if err != nil {
		return nil, err
	}
	power.DesiredRedcon = redcon
	power.Pending = &pendingCommand{Seq: seq, TargetRedcon: redcon}
	if err := r.updatePowerShadow(ctx, thingName, power); err != nil {
		return nil, err
	}
	return map[string]any{"eventType": "dcmd", "thingName": thingName, "status": "accepted", "targetRedcon": redcon, "seq": seq}, nil
}

func (r Runtime) validateDeviceIdentity(ctx context.Context, thingName, townID, rigID string) error {
	description, err := r.aws.DescribeThing(ctx, thingName)
	if err != nil {
		return err
	}
	if description.ThingTypeName == nil || *description.ThingTypeName != CloudMcuThingType {
		return fmt.Errorf("%s is not a cloud-mcu thing", thingName)
	}
	if description.Attributes["townId"] != townID {
		return fmt.Errorf("%s townId does not match event", thingName)
	}
	if description.Attributes["rigId"] != rigID {
		return fmt.Errorf("%s rigId does not match event", thingName)
	}
	return nil
}

func (r Runtime) ensureTaskRunning(ctx context.Context, tick CloudMcuTick, power *powerState) error {
	tracked := stringPtrOrEmpty(power.ECSTaskARN)
	active, err := r.activeDeviceTasks(ctx, tick.ThingName, tracked)
	if err != nil {
		return err
	}
	if keep, ok, err := r.keepSingleActiveTask(ctx, tracked, active); err != nil {
		return err
	} else if ok {
		power.Powered = true
		power.ECSTaskARN = &keep.TaskARN
		power.ECSTaskStatus = keep.LastStatus
		return nil
	}
	task, err := r.aws.RunTask(ctx, tick.ThingName, tick.RigID)
	if err != nil {
		return err
	}
	launchedARN := task.TaskARN
	active, err = r.activeDeviceTasks(ctx, tick.ThingName, task.TaskARN)
	if err != nil {
		return err
	}
	if task.IsActive() && !containsTask(active, task.TaskARN) {
		active = append(active, task)
	}
	preferred := launchedARN
	if power.ECSTaskARN != nil && containsTask(active, *power.ECSTaskARN) {
		preferred = *power.ECSTaskARN
	}
	if keep, ok, err := r.keepSingleActiveTask(ctx, preferred, active); err != nil {
		return err
	} else if ok {
		power.Powered = true
		power.ECSTaskARN = &keep.TaskARN
		power.ECSTaskStatus = keep.LastStatus
	} else {
		power.Powered = false
		power.ECSTaskARN = nil
		power.ECSTaskStatus = nil
	}
	return nil
}

func (r Runtime) ensureTaskStopped(ctx context.Context, tick CloudMcuTick, power *powerState) error {
	taskSet := map[string]bool{}
	if power.ECSTaskARN != nil {
		taskSet[*power.ECSTaskARN] = true
	}
	tasks, err := r.aws.ListDeviceTasks(ctx, tick.ThingName)
	if err != nil {
		return err
	}
	for _, task := range tasks {
		if task.IsActive() {
			taskSet[task.TaskARN] = true
		}
	}
	var taskARNs []string
	for taskARN := range taskSet {
		taskARNs = append(taskARNs, taskARN)
	}
	sort.Strings(taskARNs)
	for _, taskARN := range taskARNs {
		if err := r.aws.StopTask(ctx, taskARN); err != nil {
			return err
		}
	}
	power.Powered = false
	power.ECSTaskARN = nil
	power.ECSTaskStatus = nil
	return nil
}

func (r Runtime) activeDeviceTasks(ctx context.Context, thingName string, trackedTaskARN string) ([]EcsTaskState, error) {
	tasks, err := r.aws.ListDeviceTasks(ctx, thingName)
	if err != nil {
		return nil, err
	}
	if trackedTaskARN != "" && !containsTask(tasks, trackedTaskARN) {
		task, err := r.aws.DescribeTask(ctx, trackedTaskARN)
		if err != nil {
			return nil, err
		}
		if task != nil {
			tasks = append(tasks, *task)
		}
	}
	var active []EcsTaskState
	seen := map[string]bool{}
	for _, task := range tasks {
		if task.IsActive() && !seen[task.TaskARN] {
			seen[task.TaskARN] = true
			active = append(active, task)
		}
	}
	sort.Slice(active, func(i, j int) bool { return active[i].TaskARN < active[j].TaskARN })
	return active, nil
}

func (r Runtime) keepSingleActiveTask(ctx context.Context, trackedTaskARN string, active []EcsTaskState) (EcsTaskState, bool, error) {
	if len(active) == 0 {
		return EcsTaskState{}, false, nil
	}
	sort.Slice(active, func(i, j int) bool { return active[i].TaskARN < active[j].TaskARN })
	keepIndex := 0
	if trackedTaskARN != "" {
		for i, task := range active {
			if task.TaskARN == trackedTaskARN {
				keepIndex = i
				break
			}
		}
	}
	keep := active[keepIndex]
	for i, duplicate := range active {
		if i == keepIndex {
			continue
		}
		if err := r.aws.StopTask(ctx, duplicate.TaskARN); err != nil {
			return EcsTaskState{}, false, err
		}
	}
	return keep, true, nil
}

func (r Runtime) updateSQSShadow(ctx context.Context, tick CloudMcuTick) error {
	body, err := json.Marshal(map[string]any{"state": map[string]any{"reported": map[string]any{"lastTickOffsetSeconds": tick.TickOffsetSeconds, "lastTickScheduledAtMs": tick.ScheduledAtMs}}})
	if err != nil {
		return err
	}
	return r.aws.UpdateThingShadow(ctx, tick.ThingName, CapabilitySQS, body)
}

func (r Runtime) updatePowerShadow(ctx context.Context, thingName string, power powerState) error {
	body, err := json.Marshal(power.shadowUpdate())
	if err != nil {
		return err
	}
	return r.aws.UpdateThingShadow(ctx, thingName, CapabilityPower, body)
}

func parseDCMDTopic(topic string) (string, string, string, bool) {
	parts := strings.Split(topic, "/")
	if len(parts) != 5 || parts[0] != SparkplugNamespace || parts[2] != "DCMD" {
		return "", "", "", false
	}
	for _, part := range parts {
		if part == "" {
			return "", "", "", false
		}
	}
	return parts[1], parts[3], parts[4], true
}

func decodeEventPayload(event map[string]any) ([]byte, error) {
	if payloadBase64, ok := event["payloadBase64"].(string); ok {
		return base64.StdEncoding.DecodeString(payloadBase64)
	}
	if rawPayload, ok := event["rawPayload"].(string); ok {
		return []byte(rawPayload), nil
	}
	return nil, errors.New("event does not contain payloadBase64 or rawPayload")
}

func HandleRigLambdaEvent(ctx context.Context, awsClient AWSClientAPI) (map[string]any, error) {
	return NewRigScheduler(awsClient).HandleScheduleWithNow(ctx, UTCNowMs())
}

func HandleMcuLambdaEvent(ctx context.Context, event map[string]any, awsClient AWSClientAPI) (map[string]any, error) {
	return HandleMcuLambdaEventWithNow(ctx, event, awsClient, UTCNowMs())
}

func HandleMcuLambdaEventWithNow(ctx context.Context, event map[string]any, awsClient AWSClientAPI, nowMs int64) (map[string]any, error) {
	runtime := NewRuntime(awsClient)
	if _, ok := event["mqttTopic"].(string); ok {
		return runtime.HandleDCMDWithNow(ctx, event, nowMs)
	}
	if records, ok := event["Records"].([]any); ok {
		var processed []any
		for _, recordValue := range records {
			record, _ := recordValue.(map[string]any)
			body, ok := record["body"].(string)
			if !ok {
				return nil, errors.New("SQS record is missing body")
			}
			var tick CloudMcuTick
			if err := json.Unmarshal([]byte(body), &tick); err != nil {
				return nil, fmt.Errorf("decode SQS tick body: %w", err)
			}
			result, err := runtime.HandleTickWithNow(ctx, tick, nowMs)
			if err != nil {
				return nil, err
			}
			processed = append(processed, result)
		}
		return map[string]any{"eventType": "sqsBatch", "processedCount": len(processed), "processed": processed}, nil
	}
	return nil, errors.New("unsupported cloud MCU Lambda event")
}

func containsTask(tasks []EcsTaskState, taskARN string) bool {
	for _, task := range tasks {
		if task.TaskARN == taskARN {
			return true
		}
	}
	return false
}

func blankPtrToNil(value *string) *string {
	if value == nil || strings.TrimSpace(*value) == "" {
		return nil
	}
	trimmed := strings.TrimSpace(*value)
	return &trimmed
}

func stringPtr(value *string) string {
	if value == nil {
		return ""
	}
	return *value
}

func stringPtrValue(value *string) any {
	if value == nil {
		return nil
	}
	return *value
}

func stringPtrOrEmpty(value *string) string {
	if value == nil {
		return ""
	}
	return *value
}

func cloneStringMap(input map[string]string) map[string]string {
	out := make(map[string]string, len(input))
	for key, value := range input {
		out[key] = value
	}
	return out
}

func numberAsUint64(value any) uint64 {
	switch v := value.(type) {
	case uint64:
		return v
	case uint8:
		return uint64(v)
	case int:
		return uint64(v)
	case int32:
		return uint64(v)
	case int64:
		return uint64(v)
	case float64:
		return uint64(v)
	case json.Number:
		n, _ := v.Int64()
		return uint64(n)
	default:
		return 0
	}
}
