package registry

import (
	"context"
	"fmt"
	"reflect"
	"testing"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/service/iot"
	iottypes "github.com/aws/aws-sdk-go-v2/service/iot/types"
	"github.com/aws/aws-sdk-go-v2/service/ssm"
	ssmtypes "github.com/aws/aws-sdk-go-v2/service/ssm/types"
)

type fakeIoT struct {
	searchCalls   int
	describeCalls int
	things        []iottypes.ThingDocument
	rigThingType  string
}

func (f *fakeIoT) SearchIndex(_ context.Context, input *iot.SearchIndexInput, _ ...func(*iot.Options)) (*iot.SearchIndexOutput, error) {
	f.searchCalls++
	if input.IndexName == nil || *input.IndexName != ThingIndexName {
		return nil, fmt.Errorf("unexpected index name")
	}
	return &iot.SearchIndexOutput{Things: f.things}, nil
}

func (f *fakeIoT) DescribeThing(_ context.Context, input *iot.DescribeThingInput, _ ...func(*iot.Options)) (*iot.DescribeThingOutput, error) {
	f.describeCalls++
	return &iot.DescribeThingOutput{
		ThingName:     input.ThingName,
		ThingTypeName: aws.String(f.rigThingType),
	}, nil
}

func (f *fakeIoT) DescribeEndpoint(context.Context, *iot.DescribeEndpointInput, ...func(*iot.Options)) (*iot.DescribeEndpointOutput, error) {
	return &iot.DescribeEndpointOutput{EndpointAddress: aws.String("endpoint.example")}, nil
}

type fakeSSM struct {
	calls      int
	parameters map[string][]ssmtypes.Parameter
}

func (f *fakeSSM) GetParametersByPath(_ context.Context, input *ssm.GetParametersByPathInput, _ ...func(*ssm.Options)) (*ssm.GetParametersByPathOutput, error) {
	f.calls++
	return &ssm.GetParametersByPathOutput{Parameters: f.parameters[*input.Path]}, nil
}

func catalogParameters(path string) []ssmtypes.Parameter {
	return []ssmtypes.Parameter{
		{Name: aws.String(path + "/thingType"), Value: aws.String("unit")},
		{Name: aws.String(path + "/capabilities"), Value: aws.String("sparkplug,ble")},
		{Name: aws.String(path + "/redconCommandLevels"), Value: aws.String("1,4")},
		{Name: aws.String(path + "/redconRules/1"), Value: aws.String("sparkplug,ble")},
	}
}

func deviceDocument(thingName string, rigID string) iottypes.ThingDocument {
	return iottypes.ThingDocument{
		ThingName:     aws.String(thingName),
		ThingTypeName: aws.String("unit"),
		Attributes: map[string]string{
			"rigId":        rigID,
			"townId":       "town-1",
			"capabilities": "sparkplug,ble",
		},
	}
}

func newTestClient(iotAPI *fakeIoT, ssmAPI *fakeSSM, now *time.Time) *Client {
	return &Client{IoT: iotAPI, SSM: ssmAPI, Now: func() time.Time { return *now }}
}

func TestLoadInventoryUsesOneSearchQueryAndCachesRegistryReads(t *testing.T) {
	iotAPI := &fakeIoT{
		rigThingType: "raspi",
		things: []iottypes.ThingDocument{
			deviceDocument("unit-1", "rig-1"),
			deviceDocument("unit-2", "rig-1"),
		},
	}
	ssmAPI := &fakeSSM{parameters: map[string][]ssmtypes.Parameter{
		TypeCatalogRoot + "/raspi/unit": catalogParameters(TypeCatalogRoot + "/raspi/unit"),
	}}
	now := time.Unix(1714380000, 0)
	client := newTestClient(iotAPI, ssmAPI, &now)

	inventory, err := client.LoadInventory(context.Background(), "rig-1")
	if err != nil {
		t.Fatal(err)
	}
	if inventory.RigType != "raspi" {
		t.Fatalf("rigType = %s, want raspi", inventory.RigType)
	}
	wantNames := []string{"unit-1", "unit-2"}
	names := make([]string, 0, len(inventory.Devices))
	for _, device := range inventory.Devices {
		names = append(names, device.ThingName)
	}
	if !reflect.DeepEqual(names, wantNames) {
		t.Fatalf("devices = %#v, want %#v", names, wantNames)
	}
	if !reflect.DeepEqual(inventory.Devices[0].Capabilities, []string{"sparkplug", "ble"}) {
		t.Fatalf("capabilities = %#v", inventory.Devices[0].Capabilities)
	}
	if iotAPI.searchCalls != 1 || iotAPI.describeCalls != 1 || ssmAPI.calls != 1 {
		t.Fatalf("first refresh calls: search=%d describe=%d ssm=%d, want 1/1/1", iotAPI.searchCalls, iotAPI.describeCalls, ssmAPI.calls)
	}

	second, err := client.LoadInventory(context.Background(), "rig-1")
	if err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(second, inventory) {
		t.Fatalf("second inventory differs: %#v", second)
	}
	if iotAPI.searchCalls != 2 || iotAPI.describeCalls != 1 || ssmAPI.calls != 1 {
		t.Fatalf("steady-state refresh calls: search=%d describe=%d ssm=%d, want 2/1/1", iotAPI.searchCalls, iotAPI.describeCalls, ssmAPI.calls)
	}
	wantCounts := CallCounts{SearchIndex: 2, DescribeThing: 1, SSMReads: 1}
	if counts := client.Counts(); counts != wantCounts {
		t.Fatalf("counts = %#v, want %#v", counts, wantCounts)
	}
}

func TestLoadInventoryReloadsTypeCatalogAfterTTL(t *testing.T) {
	iotAPI := &fakeIoT{
		rigThingType: "raspi",
		things:       []iottypes.ThingDocument{deviceDocument("unit-1", "rig-1")},
	}
	ssmAPI := &fakeSSM{parameters: map[string][]ssmtypes.Parameter{
		TypeCatalogRoot + "/raspi/unit": catalogParameters(TypeCatalogRoot + "/raspi/unit"),
	}}
	now := time.Unix(1714380000, 0)
	client := newTestClient(iotAPI, ssmAPI, &now)

	for range 2 {
		if _, err := client.LoadInventory(context.Background(), "rig-1"); err != nil {
			t.Fatal(err)
		}
	}
	if ssmAPI.calls != 1 {
		t.Fatalf("ssm calls before TTL = %d, want 1", ssmAPI.calls)
	}

	now = now.Add(TypeCatalogCacheTTL + time.Second)
	if _, err := client.LoadInventory(context.Background(), "rig-1"); err != nil {
		t.Fatal(err)
	}
	if ssmAPI.calls != 2 {
		t.Fatalf("ssm calls after TTL = %d, want 2", ssmAPI.calls)
	}
}

func TestLoadInventoryFiltersUnmanagedSearchDocuments(t *testing.T) {
	iotAPI := &fakeIoT{
		rigThingType: "raspi",
		things: []iottypes.ThingDocument{
			deviceDocument("unit-1", "rig-1"),
			deviceDocument("unit-other", "rig-2"),
			deviceDocument("rig-1", "rig-1"),
			{ThingName: aws.String("typeless"), Attributes: map[string]string{"rigId": "rig-1", "townId": "town-1"}},
		},
	}
	ssmAPI := &fakeSSM{parameters: map[string][]ssmtypes.Parameter{
		TypeCatalogRoot + "/raspi/unit": catalogParameters(TypeCatalogRoot + "/raspi/unit"),
	}}
	now := time.Unix(1714380000, 0)
	client := newTestClient(iotAPI, ssmAPI, &now)

	inventory, err := client.LoadInventory(context.Background(), "rig-1")
	if err != nil {
		t.Fatal(err)
	}
	if len(inventory.Devices) != 1 || inventory.Devices[0].ThingName != "unit-1" {
		t.Fatalf("devices = %#v, want only unit-1", inventory.Devices)
	}
	if iotAPI.describeCalls != 1 {
		t.Fatalf("describe calls = %d, want 1 (rig only)", iotAPI.describeCalls)
	}
}
