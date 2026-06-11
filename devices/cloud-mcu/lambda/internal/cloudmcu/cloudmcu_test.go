package cloudmcu

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"reflect"
	"sort"
	"testing"
)

type publishedMessage struct {
	topic   string
	payload []byte
}

type sentTick struct {
	tick         CloudMcuTick
	delaySeconds int32
}

type fakeAWS struct {
	pages           []SearchPage
	descriptions    map[string]ThingDescription
	published       []publishedMessage
	sentTickBatches [][]sentTick
	shadows         map[string][]byte
	tasks           map[string]EcsTaskState
	taskDevices     map[string]string
	searchErr       error
	publishErr      error
	shadowErr       error
	runTaskCount    int
	enableSchedule  int
	disableSchedule int
	stoppedTasks    []string
}

func newFakeAWS() *fakeAWS {
	thingType := CloudMcuThingType
	rigThingType := CloudRigThingType
	return &fakeAWS{
		descriptions: map[string]ThingDescription{
			"cloud-1": {
				ThingTypeName: &thingType,
				Attributes: map[string]string{
					"townId": "town-1",
					"rigId":  "rig-1",
				},
			},
			"rig-1": {
				ThingTypeName: &rigThingType,
				Attributes: map[string]string{
					"kind":   RigKindAttribute,
					"townId": "town-1",
				},
			},
		},
		shadows:     map[string][]byte{},
		tasks:       map[string]EcsTaskState{},
		taskDevices: map[string]string{},
	}
}

func cloudShadowKey(thingName, shadowName string) string {
	return thingName + "\x00" + shadowName
}

func (f *fakeAWS) SearchCloudMcuDevices(context.Context, *string) (SearchPage, error) {
	if f.searchErr != nil {
		return SearchPage{}, f.searchErr
	}
	if len(f.pages) == 0 {
		return SearchPage{}, nil
	}
	page := f.pages[0]
	f.pages = f.pages[1:]
	return page, nil
}

func (f *fakeAWS) DescribeThing(_ context.Context, thingName string) (ThingDescription, error) {
	description, ok := f.descriptions[thingName]
	if !ok {
		return ThingDescription{}, fmt.Errorf("missing thing %s", thingName)
	}
	return description, nil
}

func (f *fakeAWS) Publish(_ context.Context, topic string, payload []byte) error {
	if f.publishErr != nil {
		return f.publishErr
	}
	f.published = append(f.published, publishedMessage{topic: topic, payload: append([]byte(nil), payload...)})
	return nil
}

func (f *fakeAWS) SendTickBatch(_ context.Context, ticks []CloudMcuTick) error {
	batch := make([]sentTick, 0, len(ticks))
	for _, tick := range ticks {
		batch = append(batch, sentTick{tick: tick, delaySeconds: tick.TickOffsetSeconds})
	}
	f.sentTickBatches = append(f.sentTickBatches, batch)
	return nil
}

func (f *fakeAWS) EnableCloudRigSchedule(context.Context) error {
	f.enableSchedule++
	return nil
}

func (f *fakeAWS) DisableCloudRigSchedule(context.Context) error {
	f.disableSchedule++
	return nil
}

func (f *fakeAWS) GetThingShadow(_ context.Context, thingName, shadowName string) ([]byte, bool, error) {
	if f.shadowErr != nil {
		return nil, false, f.shadowErr
	}
	body, ok := f.shadows[cloudShadowKey(thingName, shadowName)]
	return append([]byte(nil), body...), ok, nil
}

func (f *fakeAWS) UpdateThingShadow(_ context.Context, thingName, shadowName string, payload []byte) error {
	f.shadows[cloudShadowKey(thingName, shadowName)] = append([]byte(nil), payload...)
	return nil
}

func (f *fakeAWS) ListDeviceTasks(_ context.Context, thingName string) ([]EcsTaskState, error) {
	var tasks []EcsTaskState
	for taskARN, taskThing := range f.taskDevices {
		if taskThing == thingName && f.tasks[taskARN].IsActive() {
			tasks = append(tasks, f.tasks[taskARN])
		}
	}
	sort.Slice(tasks, func(i, j int) bool { return tasks[i].TaskARN < tasks[j].TaskARN })
	return tasks, nil
}

func (f *fakeAWS) DescribeTask(_ context.Context, taskARN string) (*EcsTaskState, error) {
	task, ok := f.tasks[taskARN]
	if !ok {
		return nil, nil
	}
	return &task, nil
}

func (f *fakeAWS) RunTask(_ context.Context, thingName, _ string) (EcsTaskState, error) {
	f.runTaskCount++
	status := "PENDING"
	task := EcsTaskState{TaskARN: fmt.Sprintf("arn:aws:ecs:task/%s-%d", thingName, f.runTaskCount), LastStatus: &status}
	f.tasks[task.TaskARN] = task
	f.taskDevices[task.TaskARN] = thingName
	return task, nil
}

func (f *fakeAWS) StopTask(_ context.Context, taskARN string) error {
	f.stoppedTasks = append(f.stoppedTasks, taskARN)
	if task, ok := f.tasks[taskARN]; ok {
		status := "STOPPED"
		task.LastStatus = &status
		f.tasks[taskARN] = task
	}
	return nil
}

func addDeviceTask(f *fakeAWS, thingName, taskARN, lastStatus string) EcsTaskState {
	status := lastStatus
	task := EcsTaskState{TaskARN: taskARN, LastStatus: &status}
	f.tasks[taskARN] = task
	f.taskDevices[taskARN] = thingName
	return task
}

func tick() CloudMcuTick {
	return CloudMcuTick{
		SchemaVersion:     "1.0",
		ThingName:         "cloud-1",
		TownID:            "town-1",
		RigID:             "rig-1",
		TickOffsetSeconds: 6,
		ScheduledAtMs:     1714380000000,
	}
}

func redconCommand(redcon uint8, seq uint64) []byte {
	payload, err := encodePayload(1714380000000, &seq, []metric{int32Metric("redcon", int32(redcon))})
	if err != nil {
		panic(err)
	}
	return payload
}

func TestSchedulerPublishesRigBirthAndOneTickBatchPerDevice(t *testing.T) {
	aws := newFakeAWS()
	aws.pages = append(aws.pages, SearchPage{Devices: []CloudMcuDevice{
		{ThingName: "cloud-1", TownID: "town-1", RigID: "rig-1"},
		{ThingName: "cloud-2", TownID: "town-1", RigID: "rig-1"},
	}})
	result, err := NewRigScheduler(aws).HandleScheduleWithNow(context.Background(), 1714380000000)
	if err != nil {
		t.Fatal(err)
	}
	if result["deviceCount"] != 2 || result["tickCount"] != 20 || result["batchCount"] != 2 {
		t.Fatalf("bad schedule result: %#v", result)
	}
	if len(aws.published) != 1 || aws.published[0].topic != "spBv1.0/town-1/NBIRTH/rig-1" {
		t.Fatalf("bad published rigs: %#v", aws.published)
	}
	if len(aws.sentTickBatches) != 2 {
		t.Fatalf("batches = %d", len(aws.sentTickBatches))
	}
	for index, thingName := range []string{"cloud-1", "cloud-2"} {
		var delays []int32
		for _, sent := range aws.sentTickBatches[index] {
			delays = append(delays, sent.delaySeconds)
			if sent.tick.ThingName != thingName {
				t.Fatalf("bad thing in batch: %#v", sent.tick)
			}
		}
		if !reflect.DeepEqual(delays, TickOffsetsSeconds) {
			t.Fatalf("delays = %#v", delays)
		}
	}
}

func TestSchedulerPropagatesSearchErrors(t *testing.T) {
	aws := newFakeAWS()
	aws.searchErr = fmt.Errorf("search failed")
	if _, err := NewRigScheduler(aws).HandleScheduleWithNow(context.Background(), 1714380000000); err == nil {
		t.Fatal("expected search error")
	}
}

func TestRigNCMDRedconFourDisablesScheduleAndPublishesLowCostBirth(t *testing.T) {
	aws := newFakeAWS()
	event := map[string]any{
		"mqttTopic":     "spBv1.0/town-1/NCMD/rig-1",
		"payloadBase64": base64.StdEncoding.EncodeToString(redconCommand(RedconSleep, 7)),
	}
	result, err := HandleRigLambdaEventWithNow(context.Background(), event, aws, 1714380000000)
	if err != nil {
		t.Fatal(err)
	}
	if result["status"] != CommandSucceeded || result["redcon"] != RedconSleep || aws.disableSchedule != 1 || aws.enableSchedule != 0 {
		t.Fatalf("bad ncmd result=%#v enable=%d disable=%d", result, aws.enableSchedule, aws.disableSchedule)
	}
	if len(aws.sentTickBatches) != 0 {
		t.Fatalf("redcon 4 must not schedule ticks: %#v", aws.sentTickBatches)
	}
	assertPublishedNodeRedcon(t, aws.published, RedconSleep, 7)
}

func TestRigNCMDRedconOneEnablesScheduleAndRunsSchedulerOnce(t *testing.T) {
	aws := newFakeAWS()
	aws.pages = append(aws.pages, SearchPage{Devices: []CloudMcuDevice{
		{ThingName: "cloud-1", TownID: "town-1", RigID: "rig-1"},
	}})
	event := map[string]any{
		"mqttTopic":     "spBv1.0/town-1/NCMD/rig-1",
		"payloadBase64": base64.StdEncoding.EncodeToString(redconCommand(RedconReady, 8)),
	}
	result, err := HandleRigLambdaEventWithNow(context.Background(), event, aws, 1714380000000)
	if err != nil {
		t.Fatal(err)
	}
	if result["status"] != CommandSucceeded || result["redcon"] != RedconReady || aws.enableSchedule != 1 || aws.disableSchedule != 0 {
		t.Fatalf("bad ncmd result=%#v enable=%d disable=%d", result, aws.enableSchedule, aws.disableSchedule)
	}
	if len(aws.sentTickBatches) != 1 {
		t.Fatalf("redcon 1 should schedule ticks immediately, batches=%d", len(aws.sentTickBatches))
	}
	assertPublishedNodeRedcon(t, aws.published[:1], RedconReady, 8)
}

func TestRigNCMDRejectsInvalidRigIdentity(t *testing.T) {
	aws := newFakeAWS()
	event := map[string]any{
		"mqttTopic":     "spBv1.0/town-1/NCMD/missing-rig",
		"payloadBase64": base64.StdEncoding.EncodeToString(redconCommand(RedconSleep, 7)),
	}
	if _, err := HandleRigLambdaEventWithNow(context.Background(), event, aws, 1714380000000); err == nil {
		t.Fatal("expected invalid rig identity error")
	}
}

func TestRigNCMDUnsupportedRedconPublishesFailureBirth(t *testing.T) {
	aws := newFakeAWS()
	event := map[string]any{
		"mqttTopic":     "spBv1.0/town-1/NCMD/rig-1",
		"payloadBase64": base64.StdEncoding.EncodeToString(redconCommand(2, 9)),
	}
	result, err := HandleRigLambdaEventWithNow(context.Background(), event, aws, 1714380000000)
	if err != nil {
		t.Fatal(err)
	}
	if result["status"] != CommandFailed || aws.enableSchedule != 0 || aws.disableSchedule != 0 {
		t.Fatalf("bad unsupported result=%#v enable=%d disable=%d", result, aws.enableSchedule, aws.disableSchedule)
	}
	if len(aws.published) != 1 || aws.published[0].topic != "spBv1.0/town-1/NDATA/rig-1" {
		t.Fatalf("bad failure publication: %#v", aws.published)
	}
}

func TestDCMDStoresDesiredRedconAndPendingCommand(t *testing.T) {
	aws := newFakeAWS()
	event := map[string]any{
		"mqttTopic":     "spBv1.0/town-1/DCMD/rig-1/cloud-1",
		"payloadBase64": base64.StdEncoding.EncodeToString(redconCommand(RedconWakeup, 7)),
	}
	result, err := NewRuntime(aws).HandleDCMDWithNow(context.Background(), event, 1714380000000)
	if err != nil {
		t.Fatal(err)
	}
	if result["status"] != "accepted" {
		t.Fatalf("bad dcmd result: %#v", result)
	}
	var shadow map[string]any
	if err := json.Unmarshal(aws.shadows[cloudShadowKey("cloud-1", "power")], &shadow); err != nil {
		t.Fatal(err)
	}
	reported := shadow["state"].(map[string]any)["reported"].(map[string]any)
	if reported["desiredRedcon"].(float64) != 3 || reported["pendingCommand"].(map[string]any)["seq"].(float64) != 7 {
		t.Fatalf("bad power shadow: %#v", shadow)
	}
}

func TestDCMDPropagatesPublishErrors(t *testing.T) {
	aws := newFakeAWS()
	aws.publishErr = fmt.Errorf("publish failed")
	event := map[string]any{
		"mqttTopic":     "spBv1.0/town-1/DCMD/rig-1/cloud-1",
		"payloadBase64": base64.StdEncoding.EncodeToString(redconCommand(2, 7)),
	}
	if _, err := NewRuntime(aws).HandleDCMDWithNow(context.Background(), event, 1714380000000); err == nil {
		t.Fatal("expected publish error")
	}
}

func TestFirstTickDefaultsToRedconFourBirth(t *testing.T) {
	aws := newFakeAWS()
	result, err := NewRuntime(aws).HandleTickWithNow(context.Background(), tick(), 1714380006000)
	if err != nil {
		t.Fatal(err)
	}
	if result["redcon"] != RedconSleep || result["messageType"] != "DBIRTH" {
		t.Fatalf("bad first tick: %#v", result)
	}
	if len(aws.published) != 1 || aws.published[0].topic != "spBv1.0/town-1/DBIRTH/rig-1/cloud-1" || len(aws.published[0].payload) == 0 {
		t.Fatalf("bad publish: %#v", aws.published)
	}
	var power map[string]any
	if err := json.Unmarshal(aws.shadows[cloudShadowKey("cloud-1", "power")], &power); err != nil {
		t.Fatal(err)
	}
	reported := power["state"].(map[string]any)["reported"].(map[string]any)
	if reported["powered"] != false || reported["sparkplugBorn"] != true {
		t.Fatalf("bad power shadow: %#v", power)
	}
}

func TestRedconThreeTickStartsTaskAndCompletesCommand(t *testing.T) {
	aws := newFakeAWS()
	aws.shadows[cloudShadowKey("cloud-1", "power")] = mustJSON(map[string]any{"state": map[string]any{"reported": map[string]any{
		"desiredRedcon":  3,
		"pendingCommand": map[string]any{"seq": 8, "targetRedcon": 3},
		"sparkplugBorn":  true,
	}}})
	result, err := NewRuntime(aws).HandleTickWithNow(context.Background(), tick(), 1714380006000)
	if err != nil {
		t.Fatal(err)
	}
	if result["redcon"] != RedconWakeup || aws.runTaskCount != 1 {
		t.Fatalf("bad redcon 3 tick: result=%#v runs=%d", result, aws.runTaskCount)
	}
	var power map[string]any
	_ = json.Unmarshal(aws.shadows[cloudShadowKey("cloud-1", "power")], &power)
	reported := power["state"].(map[string]any)["reported"].(map[string]any)
	if reported["powered"] != true || reported["pendingCommand"] != nil {
		t.Fatalf("bad power shadow: %#v", power)
	}
}

func TestRedconThreeTickReusesExistingDeviceTaskWithoutShadowARN(t *testing.T) {
	aws := newFakeAWS()
	addDeviceTask(aws, "cloud-1", "arn:aws:ecs:task/cloud-1-existing", "RUNNING")
	aws.shadows[cloudShadowKey("cloud-1", "power")] = mustJSON(map[string]any{"state": map[string]any{"reported": map[string]any{"desiredRedcon": 3, "sparkplugBorn": true}}})
	result, err := NewRuntime(aws).HandleTickWithNow(context.Background(), tick(), 1714380006000)
	if err != nil {
		t.Fatal(err)
	}
	if result["redcon"] != RedconWakeup || aws.runTaskCount != 0 {
		t.Fatalf("bad reuse result: %#v runs=%d", result, aws.runTaskCount)
	}
	var power map[string]any
	_ = json.Unmarshal(aws.shadows[cloudShadowKey("cloud-1", "power")], &power)
	if power["state"].(map[string]any)["reported"].(map[string]any)["ecsTaskArn"] != "arn:aws:ecs:task/cloud-1-existing" {
		t.Fatalf("bad power shadow: %#v", power)
	}
}

func TestRedconThreeTickKeepsOneDeviceTaskAndStopsDuplicates(t *testing.T) {
	aws := newFakeAWS()
	addDeviceTask(aws, "cloud-1", "arn:aws:ecs:task/cloud-1-a", "RUNNING")
	addDeviceTask(aws, "cloud-1", "arn:aws:ecs:task/cloud-1-b", "PENDING")
	aws.shadows[cloudShadowKey("cloud-1", "power")] = mustJSON(map[string]any{"state": map[string]any{"reported": map[string]any{"desiredRedcon": 3, "sparkplugBorn": true}}})
	result, err := NewRuntime(aws).HandleTickWithNow(context.Background(), tick(), 1714380006000)
	if err != nil {
		t.Fatal(err)
	}
	if result["redcon"] != RedconWakeup || !reflect.DeepEqual(aws.stoppedTasks, []string{"arn:aws:ecs:task/cloud-1-b"}) {
		t.Fatalf("bad duplicate handling: result=%#v stopped=%#v", result, aws.stoppedTasks)
	}
}

func TestRedconFourTickStopsAllDeviceTasks(t *testing.T) {
	aws := newFakeAWS()
	addDeviceTask(aws, "cloud-1", "arn:aws:ecs:task/cloud-1-extra", "RUNNING")
	aws.shadows[cloudShadowKey("cloud-1", "power")] = mustJSON(map[string]any{"state": map[string]any{"reported": map[string]any{
		"desiredRedcon": 4,
		"powered":       true,
		"ecsTaskArn":    "arn:aws:ecs:task/cloud-1",
		"ecsTaskStatus": "RUNNING",
		"pendingCommand": map[string]any{
			"seq":          9,
			"targetRedcon": 4,
		},
		"sparkplugBorn": true,
	}}})
	result, err := NewRuntime(aws).HandleTickWithNow(context.Background(), tick(), 1714380006000)
	if err != nil {
		t.Fatal(err)
	}
	wantStopped := []string{"arn:aws:ecs:task/cloud-1", "arn:aws:ecs:task/cloud-1-extra"}
	if result["redcon"] != RedconSleep || !reflect.DeepEqual(aws.stoppedTasks, wantStopped) {
		t.Fatalf("bad redcon 4 tick: result=%#v stopped=%#v", result, aws.stoppedTasks)
	}
	var power map[string]any
	_ = json.Unmarshal(aws.shadows[cloudShadowKey("cloud-1", "power")], &power)
	reported := power["state"].(map[string]any)["reported"].(map[string]any)
	if reported["powered"] != false || reported["ecsTaskArn"] != nil || reported["pendingCommand"] != nil {
		t.Fatalf("bad power shadow: %#v", power)
	}
}

func TestHandleMcuLambdaProcessesSQSBatch(t *testing.T) {
	aws := newFakeAWS()
	body, _ := json.Marshal(tick())
	result, err := HandleMcuLambdaEventWithNow(context.Background(), map[string]any{"Records": []any{map[string]any{"body": string(body)}}}, aws, 1714380006000)
	if err != nil {
		t.Fatal(err)
	}
	if result["eventType"] != "sqsBatch" || result["processedCount"] != 1 {
		t.Fatalf("bad batch result: %#v", result)
	}
}

func TestHandleMcuLambdaRejectsMalformedSQSBatch(t *testing.T) {
	aws := newFakeAWS()
	if _, err := HandleMcuLambdaEventWithNow(context.Background(), map[string]any{"Records": []any{map[string]any{}}}, aws, 1714380006000); err == nil {
		t.Fatal("expected malformed SQS record error")
	}
}

func mustJSON(value any) []byte {
	body, err := json.Marshal(value)
	if err != nil {
		panic(err)
	}
	return body
}

func assertPublishedNodeRedcon(t *testing.T, published []publishedMessage, wantRedcon uint8, wantSeq uint64) {
	t.Helper()
	if len(published) == 0 {
		t.Fatal("missing published NBIRTH")
	}
	message := published[0]
	if message.topic != "spBv1.0/town-1/NBIRTH/rig-1" {
		t.Fatalf("publish topic = %s", message.topic)
	}
	redcon, seq, ok, err := decodeRedconCommand(message.payload)
	if err != nil {
		t.Fatal(err)
	}
	if !ok || redcon != wantRedcon || seq != wantSeq {
		t.Fatalf("redcon publish = redcon:%d seq:%d ok:%v, want redcon:%d seq:%d", redcon, seq, ok, wantRedcon, wantSeq)
	}
}
