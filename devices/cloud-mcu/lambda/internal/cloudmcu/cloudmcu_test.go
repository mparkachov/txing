package cloudmcu

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"reflect"
	"sort"
	"strings"
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
	shadowUpdates   map[string]int
	tasks           map[string]EcsTaskState
	taskDevices     map[string]string
	searchErr       error
	publishErr      error
	shadowErr       error
	describeCalls   int
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
		shadows:       map[string][]byte{},
		shadowUpdates: map[string]int{},
		tasks:         map[string]EcsTaskState{},
		taskDevices:   map[string]string{},
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
	f.describeCalls++
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
	key := cloudShadowKey(thingName, shadowName)
	f.shadowUpdates[key]++
	f.shadows[key] = append([]byte(nil), payload...)
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

func TestSchedulerPublishesRigBirthAndUsesRedconAwareTickCadence(t *testing.T) {
	aws := newFakeAWS()
	aws.pages = append(aws.pages, SearchPage{Devices: []CloudMcuDevice{
		{ThingName: "cloud-1", TownID: "town-1", RigID: "rig-1"},
		{ThingName: "cloud-2", TownID: "town-1", RigID: "rig-1"},
	}})
	aws.descriptions["cloud-2"] = aws.descriptions["cloud-1"]
	aws.shadows[cloudShadowKey("cloud-2", "power")] = mustJSON(map[string]any{"state": map[string]any{"reported": map[string]any{"desiredRedcon": 3}}})
	result, err := NewRigScheduler(aws).HandleScheduleWithNow(context.Background(), 1714380000000)
	if err != nil {
		t.Fatal(err)
	}
	if result["deviceCount"] != 2 || result["tickCount"] != 11 || result["batchCount"] != 2 {
		t.Fatalf("bad schedule result: %#v", result)
	}
	if len(aws.published) != 1 || aws.published[0].topic != "spBv1.0/town-1/NBIRTH/rig-1" {
		t.Fatalf("bad published rigs: %#v", aws.published)
	}
	if len(aws.sentTickBatches) != 2 {
		t.Fatalf("batches = %d", len(aws.sentTickBatches))
	}
	wantDelays := [][]int32{SleepingTickOffsetsSeconds, TickOffsetsSeconds}
	for index, thingName := range []string{"cloud-1", "cloud-2"} {
		var delays []int32
		for _, sent := range aws.sentTickBatches[index] {
			delays = append(delays, sent.delaySeconds)
			if sent.tick.ThingName != thingName {
				t.Fatalf("bad thing in batch: %#v", sent.tick)
			}
		}
		if !reflect.DeepEqual(delays, wantDelays[index]) {
			t.Fatalf("delays for %s = %#v, want %#v", thingName, delays, wantDelays[index])
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

func TestDCMDStoresDesiredRedconPendingCommandAndQueuesImmediateTick(t *testing.T) {
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
	if result["tickQueued"] != true {
		t.Fatalf("dcmd did not queue immediate tick: %#v", result)
	}
	var shadow map[string]any
	if err := json.Unmarshal(aws.shadows[cloudShadowKey("cloud-1", "power")], &shadow); err != nil {
		t.Fatal(err)
	}
	reported := shadow["state"].(map[string]any)["reported"].(map[string]any)
	if reported["desiredRedcon"].(float64) != 3 || reported["pendingCommand"].(map[string]any)["seq"].(float64) != 7 {
		t.Fatalf("bad power shadow: %#v", shadow)
	}
	if len(aws.sentTickBatches) != 1 || len(aws.sentTickBatches[0]) != 1 {
		t.Fatalf("dcmd should enqueue one immediate tick: %#v", aws.sentTickBatches)
	}
	sent := aws.sentTickBatches[0][0]
	if sent.delaySeconds != 0 || sent.tick.ThingName != "cloud-1" || sent.tick.TownID != "town-1" || sent.tick.RigID != "rig-1" {
		t.Fatalf("bad immediate tick: %#v", sent)
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
	metrics := decodePayloadMetrics(t, aws.published[0].payload)
	requireMetric(t, metrics, "redcon", int32(RedconSleep))
	requireMetric(t, metrics, "capability.sparkplug", true)
	requireMetric(t, metrics, "capability.sqs", true)
	requireMetric(t, metrics, "capability.power", false)
	requireMetric(t, metrics, "capability.ecs", false)
	if _, ok := metrics["redconCommandStatus"]; ok {
		t.Fatalf("sleeping DBIRTH should not include command feedback: %#v", metrics)
	}
	var power map[string]any
	if err := json.Unmarshal(aws.shadows[cloudShadowKey("cloud-1", "power")], &power); err != nil {
		t.Fatal(err)
	}
	reported := power["state"].(map[string]any)["reported"].(map[string]any)
	if reported["powered"] != false || reported["sparkplugBorn"] != true {
		t.Fatalf("bad power shadow: %#v", power)
	}
	if aws.shadowUpdates[cloudShadowKey("cloud-1", "sqs")] != 0 {
		t.Fatalf("first tick should not write sqs shadow, updates=%d", aws.shadowUpdates[cloudShadowKey("cloud-1", "sqs")])
	}
}

func TestUnchangedSleepingTickSkipsShadowWritesAndSparkplugPublish(t *testing.T) {
	aws := newFakeAWS()
	aws.shadows[cloudShadowKey("cloud-1", "power")] = mustJSON(map[string]any{"state": map[string]any{"reported": map[string]any{
		"desiredRedcon": 4,
		"powered":       false,
		"sparkplugBorn": true,
	}}})

	result, err := NewRuntime(aws).HandleTickWithNow(context.Background(), tick(), 1714380300000)
	if err != nil {
		t.Fatal(err)
	}
	if result["redcon"] != RedconSleep || result["published"] != false || result["messageType"] != "none" {
		t.Fatalf("bad unchanged sleeping tick: %#v", result)
	}
	if len(aws.published) != 0 {
		t.Fatalf("unchanged sleeping tick published %#v", aws.published)
	}
	if len(aws.shadowUpdates) != 0 {
		t.Fatalf("unchanged sleeping tick wrote shadows: %#v", aws.shadowUpdates)
	}
}

func TestSleepingDeviceIdleWindowsSendOneTickAndNoRecurringWritesOrPublishes(t *testing.T) {
	aws := newFakeAWS()
	device := CloudMcuDevice{ThingName: "cloud-1", TownID: "town-1", RigID: "rig-1"}
	scheduler := NewRigScheduler(aws)
	runtime := NewRuntime(aws)
	ctx := context.Background()
	startMs := int64(1714380000000)

	for minute := 0; minute < 5; minute++ {
		nowMs := startMs + int64(minute)*60000
		aws.pages = []SearchPage{{Devices: []CloudMcuDevice{device}}}
		beforeBatches := len(aws.sentTickBatches)
		scheduleResult, err := scheduler.HandleScheduleWithNow(ctx, nowMs)
		if err != nil {
			t.Fatal(err)
		}
		if scheduleResult["tickCount"] != 1 || scheduleResult["batchCount"] != 1 {
			t.Fatalf("minute %d scheduled unexpected ticks: %#v", minute, scheduleResult)
		}
		if len(aws.sentTickBatches) != beforeBatches+1 {
			t.Fatalf("minute %d did not enqueue one batch: %#v", minute, aws.sentTickBatches)
		}
		batch := aws.sentTickBatches[len(aws.sentTickBatches)-1]
		if len(batch) != 1 || batch[0].delaySeconds != 0 {
			t.Fatalf("minute %d sleeping device should get one immediate tick: %#v", minute, batch)
		}

		beforeDevicePublishes := deviceSparkplugPublishCount(aws.published)
		beforePowerUpdates := aws.shadowUpdates[cloudShadowKey(device.ThingName, CapabilityPower)]
		beforeSQSUpdates := aws.shadowUpdates[cloudShadowKey(device.ThingName, CapabilitySQS)]
		result, err := runtime.HandleTickWithNow(ctx, batch[0].tick, nowMs)
		if err != nil {
			t.Fatal(err)
		}
		devicePublishDelta := deviceSparkplugPublishCount(aws.published) - beforeDevicePublishes
		powerUpdateDelta := aws.shadowUpdates[cloudShadowKey(device.ThingName, CapabilityPower)] - beforePowerUpdates
		sqsUpdateDelta := aws.shadowUpdates[cloudShadowKey(device.ThingName, CapabilitySQS)] - beforeSQSUpdates
		if minute == 0 {
			if result["messageType"] != "DBIRTH" || devicePublishDelta != 1 || powerUpdateDelta != 1 {
				t.Fatalf("initial sleeping tick should birth once and cache born state: result=%#v devicePublishDelta=%d powerUpdateDelta=%d", result, devicePublishDelta, powerUpdateDelta)
			}
			continue
		}
		if result["published"] != false || result["messageType"] != "none" {
			t.Fatalf("minute %d stable sleeping tick should not publish: %#v", minute, result)
		}
		if devicePublishDelta != 0 || powerUpdateDelta != 0 || sqsUpdateDelta != 0 {
			t.Fatalf("minute %d stable sleeping tick changed device state: devicePublishDelta=%d powerUpdateDelta=%d sqsUpdateDelta=%d", minute, devicePublishDelta, powerUpdateDelta, sqsUpdateDelta)
		}
	}
	if deviceSparkplugPublishCount(aws.published) != 1 {
		t.Fatalf("sleeping idle window should only publish initial device birth: %#v", aws.published)
	}
	if aws.shadowUpdates[cloudShadowKey(device.ThingName, CapabilitySQS)] != 0 {
		t.Fatalf("sleeping idle window should not write sqs shadow: %#v", aws.shadowUpdates)
	}
}

func TestUnchangedTickDoesNotDescribeThing(t *testing.T) {
	aws := newFakeAWS()
	aws.shadows[cloudShadowKey("cloud-1", "power")] = mustJSON(map[string]any{"state": map[string]any{"reported": map[string]any{
		"desiredRedcon": 4,
		"powered":       false,
		"sparkplugBorn": true,
	}}})

	if _, err := NewRuntime(aws).HandleTickWithNow(context.Background(), tick(), 1714380300000); err != nil {
		t.Fatal(err)
	}
	if aws.describeCalls != 0 {
		t.Fatalf("tick describeThing calls = %d, want 0", aws.describeCalls)
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
	if result["messageType"] != "DDATA" || result["published"] != true {
		t.Fatalf("redcon 3 command convergence should publish DDATA: %#v", result)
	}
	if len(aws.published) != 1 || aws.published[0].topic != "spBv1.0/town-1/DDATA/rig-1/cloud-1" {
		t.Fatalf("bad redcon 3 publication: %#v", aws.published)
	}
	metrics := decodePayloadMetrics(t, aws.published[0].payload)
	requireMetric(t, metrics, "redcon", int32(RedconWakeup))
	requireMetric(t, metrics, "capability.sparkplug", true)
	requireMetric(t, metrics, "capability.sqs", true)
	requireMetric(t, metrics, "capability.power", true)
	requireMetric(t, metrics, "capability.ecs", false)
	requireMetric(t, metrics, "redconCommandStatus", CommandSucceeded)
	requireMetric(t, metrics, "redconCommandSeq", int32(8))
	requireMetric(t, metrics, "redconCommandId", "dcmd-8")
	requireMetric(t, metrics, "redconCommandTarget", int32(RedconWakeup))
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

func TestUnchangedRedconThreeTickKeepsECSReconciliationWithoutWrites(t *testing.T) {
	aws := newFakeAWS()
	addDeviceTask(aws, "cloud-1", "arn:aws:ecs:task/cloud-1-existing", "RUNNING")
	aws.shadows[cloudShadowKey("cloud-1", "power")] = mustJSON(map[string]any{"state": map[string]any{"reported": map[string]any{
		"desiredRedcon": 4,
		"powered":       false,
		"sparkplugBorn": true,
	}}})
	// Command acceptance remains a power shadow write; the next REDCON 3 tick
	// must still reconcile ECS and publish command feedback.
	event := map[string]any{
		"mqttTopic":     "spBv1.0/town-1/DCMD/rig-1/cloud-1",
		"payloadBase64": base64.StdEncoding.EncodeToString(redconCommand(RedconWakeup, 10)),
	}
	if _, err := NewRuntime(aws).HandleDCMDWithNow(context.Background(), event, 1714380000000); err != nil {
		t.Fatal(err)
	}
	aws.shadowUpdates = map[string]int{}
	aws.published = nil
	result, err := NewRuntime(aws).HandleTickWithNow(context.Background(), tick(), 1714380006000)
	if err != nil {
		t.Fatal(err)
	}
	if result["redcon"] != RedconWakeup || result["published"] != true || len(aws.published) != 1 {
		t.Fatalf("command convergence tick did not publish feedback: result=%#v published=%#v", result, aws.published)
	}
	aws.shadowUpdates = map[string]int{}
	aws.published = nil

	unchanged, err := NewRuntime(aws).HandleTickWithNow(context.Background(), tick(), 1714380012000)
	if err != nil {
		t.Fatal(err)
	}
	if unchanged["redcon"] != RedconWakeup || unchanged["published"] != false {
		t.Fatalf("bad unchanged redcon 3 tick: %#v", unchanged)
	}
	if len(aws.published) != 0 {
		t.Fatalf("unchanged redcon 3 tick published %#v", aws.published)
	}
	if len(aws.shadowUpdates) != 0 {
		t.Fatalf("unchanged redcon 3 tick wrote shadows: %#v", aws.shadowUpdates)
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

func decodePayloadMetrics(t *testing.T, payload []byte) map[string]any {
	t.Helper()
	metrics := map[string]any{}
	offset := 0
	for offset < len(payload) {
		field, wire, next, err := readKey(payload, offset)
		if err != nil {
			t.Fatal(err)
		}
		offset = next
		if field == 2 && wire == 2 {
			metricBytes, n, err := readLengthDelimited(payload, offset)
			if err != nil {
				t.Fatal(err)
			}
			offset = n
			name, value, ok, err := decodePayloadMetric(metricBytes)
			if err != nil {
				t.Fatal(err)
			}
			if ok {
				metrics[name] = value
			}
			continue
		}
		n, err := skipField(payload, offset, wire)
		if err != nil {
			t.Fatal(err)
		}
		offset = n
	}
	return metrics
}

func decodePayloadMetric(data []byte) (string, any, bool, error) {
	offset := 0
	var name string
	var value any
	hasValue := false
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
			raw, n, err := readVarint(data, offset)
			if err != nil {
				return "", nil, false, err
			}
			value = int32(raw)
			hasValue = true
			offset = n
		case field == 11 && wire == 0:
			raw, n, err := readVarint(data, offset)
			if err != nil {
				return "", nil, false, err
			}
			value = raw
			hasValue = true
			offset = n
		case field == 14 && wire == 0:
			raw, n, err := readVarint(data, offset)
			if err != nil {
				return "", nil, false, err
			}
			value = raw != 0
			hasValue = true
			offset = n
		case field == 15 && wire == 2:
			raw, n, err := readLengthDelimited(data, offset)
			if err != nil {
				return "", nil, false, err
			}
			value = string(raw)
			hasValue = true
			offset = n
		default:
			n, err := skipField(data, offset, wire)
			if err != nil {
				return "", nil, false, err
			}
			offset = n
		}
	}
	if name == "" || !hasValue {
		return "", nil, false, nil
	}
	return name, value, true, nil
}

func requireMetric(t *testing.T, metrics map[string]any, name string, want any) {
	t.Helper()
	got, ok := metrics[name]
	if !ok {
		t.Fatalf("missing metric %s in %#v", name, metrics)
	}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("metric %s = %#v, want %#v", name, got, want)
	}
}

func deviceSparkplugPublishCount(published []publishedMessage) int {
	count := 0
	for _, message := range published {
		if strings.Contains(message.topic, "/DBIRTH/") || strings.Contains(message.topic, "/DDATA/") || strings.Contains(message.topic, "/DDEATH/") {
			count++
		}
	}
	return count
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
