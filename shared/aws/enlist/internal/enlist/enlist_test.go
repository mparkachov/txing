package enlist

import (
	"context"
	"encoding/json"
	"fmt"
	"reflect"
	"sort"
	"strings"
	"testing"
)

type sequenceShortIDs struct {
	ids  []string
	next int
}

func newSequenceShortIDs() *sequenceShortIDs {
	return &sequenceShortIDs{
		ids:  []string{"000001", "000002", "000003", "000004", "000005", "000006", "000007", "000008"},
		next: 9,
	}
}

func (s *sequenceShortIDs) NextShortID() string {
	if len(s.ids) > 0 {
		id := s.ids[0]
		s.ids = s.ids[1:]
		return id
	}
	id := fmt.Sprintf("%06d", s.next)
	s.next++
	return id
}

type fakeAWS struct {
	things            map[string]*ThingRecord
	shadows           map[string][]byte
	shadowUpdates     []string
	parameters        map[string]string
	principals        map[string][]string
	thingGroups       map[string]map[string]bool
	signalingChannels map[string]bool
	parameterPageSize int
	searchPageSize    int
	parameterErr      error
}

func seededFakeAWS() *fakeAWS {
	aws := &fakeAWS{
		things:            map[string]*ThingRecord{},
		shadows:           map[string][]byte{},
		parameters:        map[string]string{},
		principals:        map[string][]string{},
		thingGroups:       map[string]map[string]bool{},
		signalingChannels: map[string]bool{},
	}
	seedTypeCatalog(aws)
	return aws
}

func shadowKey(thingName, shadowName string) string {
	return thingName + "\x00" + shadowName
}

func (f *fakeAWS) DescribeThing(_ context.Context, thingName string) (*ThingRecord, error) {
	thing := f.things[thingName]
	if thing == nil {
		return nil, nil
	}
	clone := *thing
	clone.Attributes = cloneStringMap(thing.Attributes)
	return &clone, nil
}

func (f *fakeAWS) CreateThing(_ context.Context, thingName, thingTypeName string, attributes map[string]string) error {
	if _, ok := f.things[thingName]; ok {
		return fmt.Errorf("thing already exists")
	}
	version := int64(1)
	f.things[thingName] = &ThingRecord{ThingName: thingName, ThingTypeName: thingTypeName, Attributes: cloneStringMap(attributes), Version: &version}
	return nil
}

func (f *fakeAWS) UpdateThingAttributes(_ context.Context, thingName string, attributes map[string]string, expectedVersion *int64) error {
	thing := f.things[thingName]
	if thing == nil {
		return fmt.Errorf("thing not found")
	}
	if expectedVersion != nil && thing.Version != nil && *expectedVersion != *thing.Version {
		return fmt.Errorf("version conflict")
	}
	for key, value := range attributes {
		thing.Attributes[key] = value
	}
	next := int64(1)
	if thing.Version != nil {
		next = *thing.Version + 1
	}
	thing.Version = &next
	return nil
}

func (f *fakeAWS) DeleteThing(_ context.Context, thingName string) (bool, error) {
	if len(f.principals[thingName]) > 0 {
		return false, fmt.Errorf("principals are still attached")
	}
	_, ok := f.things[thingName]
	delete(f.things, thingName)
	return ok, nil
}

func (f *fakeAWS) SearchIndex(_ context.Context, query string, nextToken *string) (SearchPage, error) {
	var names []string
	for _, thing := range f.things {
		if matchesQuery(thing, query) {
			names = append(names, thing.ThingName)
		}
	}
	sort.Strings(names)
	start := 0
	if nextToken != nil {
		fmt.Sscanf(*nextToken, "%d", &start)
	}
	if f.searchPageSize > 0 {
		end := start + f.searchPageSize
		if end > len(names) {
			end = len(names)
		}
		var next *string
		if end < len(names) {
			token := fmt.Sprint(end)
			next = &token
		}
		return SearchPage{ThingNames: names[start:end], NextToken: next}, nil
	}
	return SearchPage{ThingNames: names}, nil
}

func (f *fakeAWS) GetShadow(_ context.Context, thingName, shadowName string) ([]byte, bool, error) {
	body, ok := f.shadows[shadowKey(thingName, shadowName)]
	return append([]byte(nil), body...), ok, nil
}

func (f *fakeAWS) UpdateShadow(_ context.Context, thingName, shadowName string, payload []byte) error {
	f.shadows[shadowKey(thingName, shadowName)] = append([]byte(nil), payload...)
	f.shadowUpdates = append(f.shadowUpdates, shadowKey(thingName, shadowName))
	return nil
}

func (f *fakeAWS) DeleteShadow(_ context.Context, thingName, shadowName string) (bool, error) {
	key := shadowKey(thingName, shadowName)
	_, ok := f.shadows[key]
	delete(f.shadows, key)
	return ok, nil
}

func (f *fakeAWS) GetParametersByPath(_ context.Context, path string, nextToken *string) (ParameterPage, error) {
	if f.parameterErr != nil {
		return ParameterPage{}, f.parameterErr
	}
	normalized := normalizeCatalogPath(path)
	prefix := normalized + "/"
	var parameters []ParameterRecord
	for name, value := range f.parameters {
		if strings.HasPrefix(name, prefix) {
			parameters = append(parameters, ParameterRecord{Name: name, Value: value})
		}
	}
	sort.Slice(parameters, func(i, j int) bool { return parameters[i].Name < parameters[j].Name })
	start := 0
	if nextToken != nil {
		fmt.Sscanf(*nextToken, "%d", &start)
	}
	if f.parameterPageSize > 0 {
		end := start + f.parameterPageSize
		if end > len(parameters) {
			end = len(parameters)
		}
		var next *string
		if end < len(parameters) {
			token := fmt.Sprint(end)
			next = &token
		}
		return ParameterPage{Parameters: parameters[start:end], NextToken: next}, nil
	}
	return ParameterPage{Parameters: parameters}, nil
}

func (f *fakeAWS) ListThingPrincipals(_ context.Context, thingName string, _ *string) (PrincipalPage, error) {
	return PrincipalPage{Principals: append([]string(nil), f.principals[thingName]...)}, nil
}

func (f *fakeAWS) DetachThingPrincipal(_ context.Context, thingName, principal string) error {
	var kept []string
	for _, candidate := range f.principals[thingName] {
		if candidate != principal {
			kept = append(kept, candidate)
		}
	}
	f.principals[thingName] = kept
	return nil
}

func (f *fakeAWS) CreateThingGroup(_ context.Context, thingGroupName string) error {
	if f.thingGroups[thingGroupName] == nil {
		f.thingGroups[thingGroupName] = map[string]bool{}
	}
	return nil
}

func (f *fakeAWS) ListThingGroupsForThing(_ context.Context, thingName string, _ *string) (ThingGroupMembershipPage, error) {
	var names []string
	for group, members := range f.thingGroups {
		if members[thingName] {
			names = append(names, group)
		}
	}
	sort.Strings(names)
	return ThingGroupMembershipPage{ThingGroupNames: names}, nil
}

func (f *fakeAWS) AddThingToThingGroup(_ context.Context, thingName, thingGroupName string) error {
	if f.things[thingName] == nil {
		return fmt.Errorf("thing not found")
	}
	if f.thingGroups[thingGroupName] == nil {
		f.thingGroups[thingGroupName] = map[string]bool{}
	}
	f.thingGroups[thingGroupName][thingName] = true
	return nil
}

func (f *fakeAWS) RemoveThingFromThingGroup(_ context.Context, thingName, thingGroupName string) error {
	if f.thingGroups[thingGroupName] != nil {
		delete(f.thingGroups[thingGroupName], thingName)
	}
	return nil
}

func (f *fakeAWS) EnsureSignalingChannel(_ context.Context, channelName string) (bool, error) {
	created := !f.signalingChannels[channelName]
	f.signalingChannels[channelName] = true
	return created, nil
}

type fakeResponder struct {
	calls []cfnCall
}

type cfnCall struct {
	status             CfnStatus
	data               map[string]any
	reason             *string
	physicalResourceID string
}

func (f *fakeResponder) Send(_ context.Context, _ map[string]any, status CfnStatus, data map[string]any, reason *string, physicalResourceID string) error {
	f.calls = append(f.calls, cfnCall{status: status, data: data, reason: reason, physicalResourceID: physicalResourceID})
	return nil
}

func seedTypeCatalog(aws *fakeAWS) {
	putRecord(aws, "/txing/town", map[string]string{
		"kind":                 "townType",
		"displayName":          "Town",
		"defaultName":          "town",
		"capabilities":         "sparkplug",
		"requiredAttributes":   "name,shortId",
		"searchableAttributes": "name",
	})
	putRecord(aws, "/txing/town/cloud", map[string]string{
		"kind":                 "rigType",
		"thingType":            "cloud",
		"rigType":              "cloud",
		"displayName":          "Cloud Rig",
		"defaultName":          "aws",
		"capabilities":         "sparkplug",
		"requiredAttributes":   "name,shortId,townId",
		"searchableAttributes": "name,townId",
	})
	putRecord(aws, "/txing/town/raspi", map[string]string{
		"kind":                 "rigType",
		"thingType":            "raspi",
		"rigType":              "raspi",
		"displayName":          "Raspberry Pi Rig",
		"defaultName":          "server",
		"capabilities":         "sparkplug",
		"hostServices":         "bluetooth.service",
		"requiredAttributes":   "name,shortId,townId",
		"searchableAttributes": "name,townId",
	})
	putRecord(aws, "/txing/town/cloud/cloud-mcu", map[string]string{
		"kind":                         "deviceType",
		"thingType":                    "cloud-mcu",
		"deviceType":                   "cloud-mcu",
		"rigType":                      "cloud",
		"displayName":                  "Cloud MCU",
		"defaultName":                  "cloud",
		"capabilities":                 "sparkplug,sqs,power,ecs",
		"redconCommandLevels":          "4,3",
		"redconRules/4":                "sparkplug,sqs",
		"redconRules/3":                "sparkplug,sqs,power",
		"requiredAttributes":           "name,shortId,townId,rigId",
		"searchableAttributes":         "name,townId,rigId",
		"web/adapter":                  "web/cloud-mcu-adapter.tsx",
		"shadows/sqs/defaultPayload":   `{"state":{"reported":{}}}`,
		"shadows/power/defaultPayload": `{"state":{"reported":{"desiredRedcon":4,"powered":false,"ecsTaskArn":null,"ecsTaskStatus":null,"pendingCommand":null,"sparkplugBorn":false}}}`,
		"shadows/ecs/defaultPayload":   `{"state":{"reported":{}}}`,
	})
	putRecord(aws, "/txing/town/raspi/unit", map[string]string{
		"kind":                             "deviceType",
		"thingType":                        "unit",
		"deviceType":                       "unit",
		"rigType":                          "raspi",
		"displayName":                      "Unit",
		"defaultName":                      "bot",
		"capabilities":                     "sparkplug,ble,power,board,mcp,video",
		"redconCommandLevels":              "4,3,2,1",
		"redconRules/4":                    "sparkplug,ble",
		"redconRules/3":                    "sparkplug,ble,power",
		"redconRules/2":                    "sparkplug,ble,power,board,mcp",
		"redconRules/1":                    "sparkplug,ble,power,board,mcp,video",
		"requiredAttributes":               "name,shortId,townId,rigId",
		"searchableAttributes":             "name,townId,rigId",
		"web/adapter":                      "web/unit-adapter.tsx",
		"shadows/ble/defaultPayload":       `{"state":{"reported":{}}}`,
		"shadows/power/defaultPayload":     `{"state":{"reported":{}}}`,
		"shadows/board/defaultPayload":     `{"state":{"reported":{}}}`,
		"shadows/mcp/defaultPayload":       `{"state":{"reported":{}}}`,
		"shadows/video/defaultPayload":     `{"state":{"reported":{}}}`,
		"resources/boardVideo/channelName": "{device_id}-board-video",
	})
}

func putRecord(aws *fakeAWS, path string, leaves map[string]string) {
	for leaf, value := range leaves {
		aws.parameters[path+"/"+leaf] = value
	}
}

func matchesQuery(thing *ThingRecord, query string) bool {
	for _, predicate := range strings.Split(query, " AND ") {
		parts := strings.SplitN(predicate, ":", 2)
		if len(parts) != 2 {
			return false
		}
		key, value := parts[0], parts[1]
		if key == "thingTypeName" {
			if value != "*" && thing.ThingTypeName != value {
				return false
			}
			continue
		}
		if attr, ok := strings.CutPrefix(key, "attributes."); ok {
			actual, exists := thing.Attributes[attr]
			if value == "*" {
				if !exists {
					return false
				}
			} else if actual != value {
				return false
			}
			continue
		}
		return false
	}
	return true
}

func resultString(value map[string]any, key string) string {
	text, _ := value[key].(string)
	return text
}

func enlistTown(t *testing.T, service *Service) map[string]any {
	t.Helper()
	result, err := service.Handle(context.Background(), map[string]any{"action": "enlistTown", "townName": "town"})
	if err != nil {
		t.Fatal(err)
	}
	return result
}

func enlistRig(t *testing.T, service *Service, townID, rigType, rigName string) map[string]any {
	t.Helper()
	result, err := service.Handle(context.Background(), map[string]any{"action": "enlistRig", "townId": townID, "rigType": rigType, "rigName": rigName})
	if err != nil {
		t.Fatal(err)
	}
	return result
}

func enlistDevice(t *testing.T, service *Service, rigID, deviceType, deviceName string) map[string]any {
	t.Helper()
	result, err := service.Handle(context.Background(), map[string]any{"action": "enlistDevice", "rigId": rigID, "deviceType": deviceType, "deviceName": deviceName})
	if err != nil {
		t.Fatal(err)
	}
	return result
}

func TestEnlistTownCreatesAttributesAndSparkplugShadow(t *testing.T) {
	aws := seededFakeAWS()
	service := NewService(aws, newSequenceShortIDs())
	result := enlistTown(t, service)
	if result["created"] != true || result["thingTypeName"] != "town" || result["thingName"] != "town-000001" {
		t.Fatalf("unexpected result: %#v", result)
	}
	attrs := result["attributes"].(map[string]string)
	if attrs["name"] != "town" || attrs["shortId"] != "000001" || attrs["kind"] != "townType" || attrs["capabilities"] != "sparkplug" {
		t.Fatalf("unexpected attributes: %#v", attrs)
	}
	var shadow map[string]any
	if err := json.Unmarshal(aws.shadows[shadowKey("town-000001", "sparkplug")], &shadow); err != nil {
		t.Fatal(err)
	}
	if shadow["state"].(map[string]any)["reported"].(map[string]any)["payload"].(map[string]any)["metrics"].(map[string]any)["redcon"].(float64) != 1 {
		t.Fatalf("unexpected shadow: %#v", shadow)
	}
}

func TestEnlistRigsUseTypeCatalogAttributesAndInitializeShadow(t *testing.T) {
	aws := seededFakeAWS()
	service := NewService(aws, newSequenceShortIDs())
	town := enlistTown(t, service)
	cloud := enlistRig(t, service, resultString(town, "thingName"), "cloud", "aws")
	raspi := enlistRig(t, service, resultString(town, "thingName"), "raspi", "server")
	if cloud["thingTypeName"] != "cloud" || cloud["attributes"].(map[string]string)["displayName"] != "Cloud-Rig" {
		t.Fatalf("bad cloud rig: %#v", cloud)
	}
	if cloud["auxiliaryResources"].(map[string]any)["thingGroupName"] != "txing-rig-type-cloud" {
		t.Fatalf("bad cloud resources: %#v", cloud["auxiliaryResources"])
	}
	if raspi["attributes"].(map[string]string)["hostServices"] != "bluetooth.service" {
		t.Fatalf("bad raspi attributes: %#v", raspi["attributes"])
	}
}

func TestRepeatedEnlistRepairsRigTypeGroupMembership(t *testing.T) {
	aws := seededFakeAWS()
	service := NewService(aws, newSequenceShortIDs())
	town := enlistTown(t, service)
	cloud := enlistRig(t, service, resultString(town, "thingName"), "cloud", "aws")
	thingName := resultString(cloud, "thingName")
	if err := aws.CreateThingGroup(context.Background(), "txing-rig-type-raspi"); err != nil {
		t.Fatal(err)
	}
	if err := aws.AddThingToThingGroup(context.Background(), thingName, "txing-rig-type-raspi"); err != nil {
		t.Fatal(err)
	}
	repaired := enlistRig(t, service, resultString(town, "thingName"), "cloud", "aws")
	if repaired["created"] != false {
		t.Fatalf("bad repaired result: %#v", repaired)
	}
	if !aws.thingGroups["txing-rig-type-cloud"][thingName] {
		t.Fatalf("missing repaired cloud membership: %#v", aws.thingGroups)
	}
	if aws.thingGroups["txing-rig-type-raspi"][thingName] {
		t.Fatalf("stale raspi membership remains: %#v", aws.thingGroups)
	}
}

func TestEnlistCloudMcuDeviceValidatesCompatibilityAndInitializesShadows(t *testing.T) {
	aws := seededFakeAWS()
	service := NewService(aws, newSequenceShortIDs())
	town := enlistTown(t, service)
	raspi := enlistRig(t, service, resultString(town, "thingName"), "raspi", "server")
	if _, err := service.Handle(context.Background(), map[string]any{"action": "enlistDevice", "rigId": resultString(raspi, "thingName"), "deviceType": "cloud-mcu", "deviceName": "cloud"}); err == nil || !strings.Contains(err.Error(), "not compatible") {
		t.Fatalf("expected compatibility error, got %v", err)
	}
	cloud := enlistRig(t, service, resultString(town, "thingName"), "cloud", "aws")
	device := enlistDevice(t, service, resultString(cloud, "thingName"), "cloud-mcu", "cloud")
	attrs := device["attributes"].(map[string]string)
	if attrs["capabilities"] != "sparkplug,sqs,power,ecs" || attrs["webAdapter"] != "web/cloud-mcu-adapter.tsx" {
		t.Fatalf("bad cloud mcu attributes: %#v", attrs)
	}
	want := []string{"sparkplug", "sqs", "power", "ecs"}
	if !reflect.DeepEqual(device["initializedShadows"], want) {
		t.Fatalf("initialized = %#v", device["initializedShadows"])
	}
}

func TestEnlistUnitCreatesAllShadowsAndBoardVideoChannel(t *testing.T) {
	aws := seededFakeAWS()
	service := NewService(aws, newSequenceShortIDs())
	town := enlistTown(t, service)
	raspi := enlistRig(t, service, resultString(town, "thingName"), "raspi", "server")
	unit := enlistDevice(t, service, resultString(raspi, "thingName"), "unit", "bot")
	if unit["attributes"].(map[string]string)["redconCommandLevels"] != "4,3,2,1" {
		t.Fatalf("bad unit attrs: %#v", unit["attributes"])
	}
	boardVideo := unit["auxiliaryResources"].(map[string]any)["boardVideo"].(map[string]any)
	if boardVideo["channelName"] != "unit-000003-board-video" || boardVideo["created"] != true {
		t.Fatalf("bad board video resource: %#v", boardVideo)
	}
}

func TestRepeatedEnlistRepairsAttributesWithoutReplacingShadows(t *testing.T) {
	aws := seededFakeAWS()
	service := NewService(aws, newSequenceShortIDs())
	town := enlistTown(t, service)
	cloud := enlistRig(t, service, resultString(town, "thingName"), "cloud", "aws")
	first := enlistDevice(t, service, resultString(cloud, "thingName"), "cloud-mcu", "cloud")
	thingName := resultString(first, "thingName")
	delete(aws.things[thingName].Attributes, "webAdapter")
	aws.shadows[shadowKey(thingName, "sqs")] = []byte(`{"state":{"reported":{"custom":true}}}`)
	updateCount := len(aws.shadowUpdates)
	second := enlistDevice(t, service, resultString(cloud, "thingName"), "cloud-mcu", "cloud")
	if second["created"] != false || len(second["initializedShadows"].([]string)) != 0 {
		t.Fatalf("bad repeated enlist: %#v", second)
	}
	if len(aws.shadowUpdates) != updateCount {
		t.Fatalf("unexpected shadow update")
	}
}

func TestAssignDeviceValidatesCompatibilityAndDoesNotResetShadows(t *testing.T) {
	aws := seededFakeAWS()
	service := NewService(aws, newSequenceShortIDs())
	town := enlistTown(t, service)
	cloudA := enlistRig(t, service, resultString(town, "thingName"), "cloud", "aws")
	cloudB := enlistRig(t, service, resultString(town, "thingName"), "cloud", "backup")
	device := enlistDevice(t, service, resultString(cloudA, "thingName"), "cloud-mcu", "cloud")
	updateCount := len(aws.shadowUpdates)
	result, err := service.Handle(context.Background(), map[string]any{"action": "assignDevice", "deviceId": resultString(device, "thingName"), "rigId": resultString(cloudB, "thingName")})
	if err != nil {
		t.Fatal(err)
	}
	if result["attributes"].(map[string]string)["rigId"] != resultString(cloudB, "thingName") || len(aws.shadowUpdates) != updateCount {
		t.Fatalf("bad assign result: %#v", result)
	}
}

func TestDischargeThingDeletesShadowsPrincipalsAndThing(t *testing.T) {
	aws := seededFakeAWS()
	service := NewService(aws, newSequenceShortIDs())
	town := enlistTown(t, service)
	raspi := enlistRig(t, service, resultString(town, "thingName"), "raspi", "server")
	device := enlistDevice(t, service, resultString(raspi, "thingName"), "unit", "bot")
	thingName := resultString(device, "thingName")
	aws.principals[thingName] = []string{"arn:aws:iot:eu-central-1:123:cert/one", "arn:aws:iot:eu-central-1:123:cert/two"}
	result, err := service.Handle(context.Background(), map[string]any{"action": "dischargeThing", "thingId": thingName})
	if err != nil {
		t.Fatal(err)
	}
	if result["deleted"] != true || aws.things[thingName] != nil {
		t.Fatalf("bad discharge: %#v", result)
	}
	want := []string{"sparkplug", "ble", "power", "board", "mcp", "video"}
	if !reflect.DeepEqual(result["deletedShadows"], want) {
		t.Fatalf("deleted shadows = %#v", result["deletedShadows"])
	}
}

func TestDischargeAllDeletesDevicesThenRigsThenTownsWithPaginatedSearch(t *testing.T) {
	aws := seededFakeAWS()
	aws.searchPageSize = 1
	service := NewService(aws, newSequenceShortIDs())
	town := enlistTown(t, service)
	cloud := enlistRig(t, service, resultString(town, "thingName"), "cloud", "aws")
	device := enlistDevice(t, service, resultString(cloud, "thingName"), "cloud-mcu", "cloud")
	result, err := service.Handle(context.Background(), map[string]any{"action": "dischargeAll"})
	if err != nil {
		t.Fatal(err)
	}
	if result["deletedThingCount"] != 3 {
		t.Fatalf("bad deleted count: %#v", result)
	}
	rows := result["deletedThings"].([]any)
	got := []string{rows[0].(map[string]any)["thingName"].(string), rows[1].(map[string]any)["thingName"].(string), rows[2].(map[string]any)["thingName"].(string)}
	want := []string{resultString(device, "thingName"), resultString(cloud, "thingName"), resultString(town, "thingName")}
	if !reflect.DeepEqual(got, want) || len(aws.things) != 0 {
		t.Fatalf("got order %v want %v things=%v", got, want, aws.things)
	}
}

func TestMalformedEventsAndUnsupportedActionsReturnErrorEnvelope(t *testing.T) {
	aws := seededFakeAWS()
	responder := &fakeResponder{}
	service := NewService(aws, newSequenceShortIDs())
	result := HandleLambdaEventWithService(context.Background(), map[string]any{"action": "unsupported"}, service, responder)
	if result["ok"] != false || result["errorType"] != "EnlistError" || result["message"] != "unsupported enlist action: 'unsupported'" {
		t.Fatalf("bad unsupported result: %#v", result)
	}
	missing := HandleLambdaEventWithService(context.Background(), map[string]any{}, service, responder)
	if missing["ok"] != false || !strings.Contains(missing["message"].(string), "missing required field") {
		t.Fatalf("bad missing result: %#v", missing)
	}
}

func TestAWSClientErrorsReturnErrorEnvelope(t *testing.T) {
	aws := seededFakeAWS()
	aws.parameterErr = fmt.Errorf("ssm failed")
	responder := &fakeResponder{}
	service := NewService(aws, newSequenceShortIDs())
	result := HandleLambdaEventWithService(context.Background(), map[string]any{"action": "enlistTown", "townName": "town"}, service, responder)
	if result["ok"] != false || result["errorType"] != "Error" || !strings.Contains(result["message"].(string), "ssm failed") {
		t.Fatalf("bad aws error result: %#v", result)
	}
}

func TestCfnCreateUpdateSkipDeleteDischargesAndFailureSendsFailed(t *testing.T) {
	aws := seededFakeAWS()
	aws.parameterPageSize = 2
	responder := &fakeResponder{}
	service := NewService(aws, newSequenceShortIDs())
	town := enlistTown(t, service)
	cloud := enlistRig(t, service, resultString(town, "thingName"), "cloud", "aws")
	_ = enlistDevice(t, service, resultString(cloud, "thingName"), "cloud-mcu", "cloud")
	create := HandleLambdaEventWithService(context.Background(), cfnEvent("Create", "TxingDischargeThings"), service, responder)
	if create["ok"] != true || create["skipped"] != true {
		t.Fatalf("bad create: %#v", create)
	}
	deleteResult := HandleLambdaEventWithService(context.Background(), cfnEvent("Delete", "TxingDischargeThings"), service, responder)
	if deleteResult["ok"] != true || deleteResult["deletedThingCount"] != 3 {
		t.Fatalf("bad delete: %#v", deleteResult)
	}
	failed := HandleLambdaEventWithService(context.Background(), cfnEvent("Delete", "Wrong"), service, responder)
	if failed["ok"] != false || failed["errorType"] != "EnlistError" || !strings.Contains(failed["message"].(string), "Unsupported CleanupType") {
		t.Fatalf("bad failed: %#v", failed)
	}
	if responder.calls[0].status != CfnSuccess || responder.calls[1].status != CfnSuccess || responder.calls[2].status != CfnFailed || responder.calls[2].physicalResourceID != cfnDischargePhysicalID {
		t.Fatalf("bad cfn calls: %#v", responder.calls)
	}
}

func cfnEvent(requestType, cleanupType string) map[string]any {
	return map[string]any{
		"RequestType":       requestType,
		"ResponseURL":       "https://cloudformation-response.example",
		"StackId":           "stack",
		"RequestId":         "request",
		"LogicalResourceId": activeCfnDischargeLogicalID,
		"ResourceProperties": map[string]any{
			"CleanupType":        cleanupType,
			"PhysicalResourceId": cfnDischargePhysicalID,
		},
	}
}
