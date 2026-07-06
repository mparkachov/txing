package registry

import (
	"context"
	"fmt"
	"sort"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/service/iot"
	iottypes "github.com/aws/aws-sdk-go-v2/service/iot/types"
	"github.com/aws/aws-sdk-go-v2/service/ssm"
	"github.com/mparkachov/txing/rig/internal/catalog"
	"github.com/mparkachov/txing/rig/internal/protocol"
)

const (
	ThingIndexName  = "AWS_Things"
	TypeCatalogRoot = "/txing/town"
	// TypeCatalogCacheTTL bounds how long SSM type catalog records are reused
	// across inventory refreshes. Catalog changes are deploy-time events; a
	// rig restart is the manual force-refresh.
	TypeCatalogCacheTTL = time.Hour
)

type ThingRegistration struct {
	ThingName    string
	ThingType    string
	RigID        *string
	TownID       *string
	Capabilities []string
}

type Inventory struct {
	RigType string
	Devices []protocol.InventoryDevice
}

type IoTAPI interface {
	SearchIndex(ctx context.Context, input *iot.SearchIndexInput, optFns ...func(*iot.Options)) (*iot.SearchIndexOutput, error)
	DescribeThing(ctx context.Context, input *iot.DescribeThingInput, optFns ...func(*iot.Options)) (*iot.DescribeThingOutput, error)
	DescribeEndpoint(ctx context.Context, input *iot.DescribeEndpointInput, optFns ...func(*iot.Options)) (*iot.DescribeEndpointOutput, error)
}

type SSMAPI interface {
	GetParametersByPath(ctx context.Context, input *ssm.GetParametersByPathInput, optFns ...func(*ssm.Options)) (*ssm.GetParametersByPathOutput, error)
}

type Client struct {
	IoT IoTAPI
	SSM SSMAPI
	// Now is the cache clock; nil means time.Now.
	Now func() time.Time

	mu          sync.Mutex
	rigType     string
	typeCatalog map[string]typeCatalogEntry

	searchIndexCalls   atomic.Uint64
	describeThingCalls atomic.Uint64
	ssmReadCalls       atomic.Uint64
}

// CallCounts reports cumulative AWS API calls since process start, for
// counted idle-cost soaks.
type CallCounts struct {
	SearchIndex   uint64
	DescribeThing uint64
	SSMReads      uint64
}

func (c *Client) Counts() CallCounts {
	return CallCounts{
		SearchIndex:   c.searchIndexCalls.Load(),
		DescribeThing: c.describeThingCalls.Load(),
		SSMReads:      c.ssmReadCalls.Load(),
	}
}

type typeCatalogEntry struct {
	record   catalog.TypeCatalogDevice
	loadedAt time.Time
}

func New(awsConfig aws.Config) *Client {
	return &Client{IoT: iot.NewFromConfig(awsConfig), SSM: ssm.NewFromConfig(awsConfig)}
}

// LoadInventory performs one fleet-indexing SearchIndex query per call. The
// rig's own thing type and the SSM type catalog are cached across calls so an
// idle rig makes no recurring per-device registry calls or SSM reads.
func (c *Client) LoadInventory(ctx context.Context, rigID string) (Inventory, error) {
	rigType, err := c.rigThingType(ctx, rigID)
	if err != nil {
		return Inventory{}, err
	}
	registrations, err := c.searchRigRegistrations(ctx, rigID)
	if err != nil {
		return Inventory{}, err
	}
	var devices []protocol.InventoryDevice
	for _, registration := range registrations {
		if !isManagedDeviceRegistration(registration, rigID) {
			continue
		}
		typeRecord, err := c.deviceTypeRecord(ctx, rigType, registration.ThingType)
		if err != nil {
			continue
		}
		if len(typeRecord.RedconRules) == 0 {
			continue
		}
		capabilities, err := validateRegistrationCapabilities(registration, typeRecord)
		if err != nil {
			continue
		}
		devices = append(devices, typeRecord.ToInventoryDeviceWithCapabilities(registration.ThingName, capabilities))
	}
	sort.Slice(devices, func(i, j int) bool { return devices[i].ThingName < devices[j].ThingName })
	return Inventory{RigType: rigType, Devices: devices}, nil
}

func (c *Client) rigThingType(ctx context.Context, rigID string) (string, error) {
	c.mu.Lock()
	rigType := c.rigType
	c.mu.Unlock()
	if rigType != "" {
		return rigType, nil
	}
	rig, err := c.DescribeThing(ctx, rigID)
	if err != nil {
		return "", err
	}
	c.mu.Lock()
	c.rigType = rig.ThingType
	c.mu.Unlock()
	return rig.ThingType, nil
}

func (c *Client) deviceTypeRecord(ctx context.Context, rigType string, deviceType string) (catalog.TypeCatalogDevice, error) {
	now := c.currentTime()
	c.mu.Lock()
	entry, ok := c.typeCatalog[deviceType]
	c.mu.Unlock()
	if ok && now.Sub(entry.loadedAt) < TypeCatalogCacheTTL {
		return entry.record, nil
	}
	record, err := c.LoadDeviceType(ctx, rigType, deviceType)
	if err != nil {
		return catalog.TypeCatalogDevice{}, err
	}
	c.mu.Lock()
	if c.typeCatalog == nil {
		c.typeCatalog = map[string]typeCatalogEntry{}
	}
	c.typeCatalog[deviceType] = typeCatalogEntry{record: record, loadedAt: now}
	c.mu.Unlock()
	return record, nil
}

func (c *Client) currentTime() time.Time {
	if c.Now != nil {
		return c.Now()
	}
	return time.Now()
}

func (c *Client) DescribeEndpoint(ctx context.Context) (string, error) {
	response, err := c.IoT.DescribeEndpoint(ctx, &iot.DescribeEndpointInput{EndpointType: aws.String("iot:Data-ATS")})
	if err != nil {
		return "", err
	}
	if response.EndpointAddress == nil || strings.TrimSpace(*response.EndpointAddress) == "" {
		return "", fmt.Errorf("AWS IoT DescribeEndpoint returned no endpointAddress")
	}
	return strings.TrimSpace(*response.EndpointAddress), nil
}

// searchRigRegistrations builds device registrations from the fleet-indexing
// documents directly; the index carries thing name, thing type, and
// attributes, so no per-device DescribeThing is needed.
func (c *Client) searchRigRegistrations(ctx context.Context, rigID string) ([]ThingRegistration, error) {
	query := fmt.Sprintf("attributes.rigId:%s AND attributes.townId:*", rigID)
	registrations := map[string]ThingRegistration{}
	var nextToken *string
	for {
		c.searchIndexCalls.Add(1)
		response, err := c.IoT.SearchIndex(ctx, &iot.SearchIndexInput{
			IndexName:   aws.String(ThingIndexName),
			QueryString: aws.String(query),
			MaxResults:  aws.Int32(100),
			NextToken:   nextToken,
		})
		if err != nil {
			return nil, err
		}
		for _, thing := range response.Things {
			registration, err := registrationFromDocument(thing)
			if err != nil {
				continue
			}
			registrations[registration.ThingName] = registration
		}
		nextToken = response.NextToken
		if nextToken == nil {
			break
		}
	}
	names := make([]string, 0, len(registrations))
	for name := range registrations {
		names = append(names, name)
	}
	sort.Strings(names)
	result := make([]ThingRegistration, 0, len(names))
	for _, name := range names {
		result = append(result, registrations[name])
	}
	return result, nil
}

func registrationFromDocument(document iottypes.ThingDocument) (ThingRegistration, error) {
	if document.ThingName == nil || strings.TrimSpace(*document.ThingName) == "" {
		return ThingRegistration{}, fmt.Errorf("search index document is missing thingName")
	}
	thingName := strings.TrimSpace(*document.ThingName)
	if document.ThingTypeName == nil || strings.TrimSpace(*document.ThingTypeName) == "" {
		return ThingRegistration{}, fmt.Errorf("thing %s is missing thingTypeName", thingName)
	}
	attributes := document.Attributes
	var capabilities []string
	if raw, ok := attributes["capabilities"]; ok && strings.TrimSpace(raw) != "" {
		parsed, err := catalog.ParseStringList(raw)
		if err != nil {
			return ThingRegistration{}, err
		}
		capabilities = parsed
	}
	return ThingRegistration{
		ThingName:    thingName,
		ThingType:    strings.TrimSpace(*document.ThingTypeName),
		RigID:        normalizeAttribute(attributes["rigId"]),
		TownID:       normalizeAttribute(attributes["townId"]),
		Capabilities: capabilities,
	}, nil
}

func (c *Client) DescribeThing(ctx context.Context, thingName string) (ThingRegistration, error) {
	c.describeThingCalls.Add(1)
	response, err := c.IoT.DescribeThing(ctx, &iot.DescribeThingInput{ThingName: aws.String(thingName)})
	if err != nil {
		return ThingRegistration{}, err
	}
	if response.ThingTypeName == nil || strings.TrimSpace(*response.ThingTypeName) == "" {
		return ThingRegistration{}, fmt.Errorf("thing %s is missing thingTypeName", thingName)
	}
	attributes := response.Attributes
	var capabilities []string
	if raw, ok := attributes["capabilities"]; ok && strings.TrimSpace(raw) != "" {
		parsed, err := catalog.ParseStringList(raw)
		if err != nil {
			return ThingRegistration{}, err
		}
		capabilities = parsed
	}
	return ThingRegistration{
		ThingName:    thingName,
		ThingType:    strings.TrimSpace(*response.ThingTypeName),
		RigID:        normalizeAttribute(attributes["rigId"]),
		TownID:       normalizeAttribute(attributes["townId"]),
		Capabilities: capabilities,
	}, nil
}

func (c *Client) LoadDeviceType(ctx context.Context, rigType string, deviceType string) (catalog.TypeCatalogDevice, error) {
	path := fmt.Sprintf("%s/%s/%s", TypeCatalogRoot, rigType, deviceType)
	var parameters [][2]string
	var nextToken *string
	for {
		c.ssmReadCalls.Add(1)
		response, err := c.SSM.GetParametersByPath(ctx, &ssm.GetParametersByPathInput{
			Path:           aws.String(path),
			Recursive:      aws.Bool(true),
			WithDecryption: aws.Bool(false),
			MaxResults:     aws.Int32(10),
			NextToken:      nextToken,
		})
		if err != nil {
			return catalog.TypeCatalogDevice{}, err
		}
		for _, parameter := range response.Parameters {
			if parameter.Name != nil && parameter.Value != nil {
				parameters = append(parameters, [2]string{*parameter.Name, *parameter.Value})
			}
		}
		nextToken = response.NextToken
		if nextToken == nil {
			break
		}
	}
	return catalog.ReconstructTypeRecord(parameters)
}

func normalizeAttribute(value string) *string {
	value = strings.TrimSpace(value)
	if value == "" {
		return nil
	}
	return &value
}

func isManagedDeviceRegistration(registration ThingRegistration, rigID string) bool {
	return registration.ThingName != rigID && registration.RigID != nil && *registration.RigID == rigID
}

func validateRegistrationCapabilities(registration ThingRegistration, typeRecord catalog.TypeCatalogDevice) ([]string, error) {
	if len(registration.Capabilities) == 0 {
		return nil, fmt.Errorf("missing capabilities attribute")
	}
	if strings.Join(registration.Capabilities, ",") != strings.Join(typeRecord.Capabilities, ",") {
		return nil, fmt.Errorf("thing capabilities [%s] do not match type catalog capabilities [%s]", strings.Join(registration.Capabilities, ","), strings.Join(typeRecord.Capabilities, ","))
	}
	return append([]string(nil), registration.Capabilities...), nil
}
