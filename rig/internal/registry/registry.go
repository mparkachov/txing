package registry

import (
	"context"
	"fmt"
	"sort"
	"strings"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/service/iot"
	"github.com/aws/aws-sdk-go-v2/service/ssm"
	"github.com/mparkachov/txing/rig/internal/catalog"
	"github.com/mparkachov/txing/rig/internal/protocol"
)

const (
	ThingIndexName  = "AWS_Things"
	TypeCatalogRoot = "/txing/town"
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

type Client struct {
	IoT *iot.Client
	SSM *ssm.Client
}

func New(awsConfig aws.Config) *Client {
	return &Client{IoT: iot.NewFromConfig(awsConfig), SSM: ssm.NewFromConfig(awsConfig)}
}

func (c *Client) LoadInventory(ctx context.Context, rigID string) (Inventory, error) {
	rig, err := c.DescribeThing(ctx, rigID)
	if err != nil {
		return Inventory{}, err
	}
	thingNames, err := c.ListRigThingNames(ctx, rigID)
	if err != nil {
		return Inventory{}, err
	}
	typeCache := map[string]catalog.TypeCatalogDevice{}
	var devices []protocol.InventoryDevice
	for _, thingName := range thingNames {
		registration, err := c.DescribeThing(ctx, thingName)
		if err != nil {
			continue
		}
		if !isManagedDeviceRegistration(registration, rigID) {
			continue
		}
		typeRecord, ok := typeCache[registration.ThingType]
		if !ok {
			typeRecord, err = c.LoadDeviceType(ctx, rig.ThingType, registration.ThingType)
			if err != nil {
				continue
			}
			typeCache[registration.ThingType] = typeRecord
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
	return Inventory{RigType: rig.ThingType, Devices: devices}, nil
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

func (c *Client) ListRigThingNames(ctx context.Context, rigID string) ([]string, error) {
	query := fmt.Sprintf("attributes.rigId:%s AND attributes.townId:*", rigID)
	names := map[string]struct{}{}
	var nextToken *string
	for {
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
			if thing.ThingName != nil && strings.TrimSpace(*thing.ThingName) != "" {
				names[strings.TrimSpace(*thing.ThingName)] = struct{}{}
			}
		}
		nextToken = response.NextToken
		if nextToken == nil {
			break
		}
	}
	result := make([]string, 0, len(names))
	for name := range names {
		result = append(result, name)
	}
	sort.Strings(result)
	return result, nil
}

func (c *Client) DescribeThing(ctx context.Context, thingName string) (ThingRegistration, error) {
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
