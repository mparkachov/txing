package enlist

import (
	"bytes"
	"context"
	"crypto/rand"
	"encoding/json"
	"errors"
	"fmt"
	"math/big"
	"net/http"
	"sort"
	"strings"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/service/iot"
	iottypes "github.com/aws/aws-sdk-go-v2/service/iot/types"
	"github.com/aws/aws-sdk-go-v2/service/iotdataplane"
	"github.com/aws/aws-sdk-go-v2/service/kinesisvideo"
	kvtypes "github.com/aws/aws-sdk-go-v2/service/kinesisvideo/types"
	"github.com/aws/aws-sdk-go-v2/service/ssm"
)

const (
	thingIndexName              = "AWS_Things"
	shortIDAlphabet             = "0123456789abcdefghijklmnopqrstuvwxyz"
	shortIDLength               = 6
	townThingType               = "town"
	kindTownType                = "townType"
	kindRigType                 = "rigType"
	kindDeviceType              = "deviceType"
	townIDAttribute             = "townId"
	rigIDAttribute              = "rigId"
	cfnDischargePhysicalID      = "txing-discharge-things-on-delete"
	typeCatalogRoot             = "/txing"
	sparkplugNamespace          = "spBv1.0"
	rigTypeThingGroupPrefix     = "txing-rig-type-"
	activeCfnDischargeLogicalID = "TxingDischargeThingsOnStackDelete"
)

var (
	listLeafFields         = map[string]bool{"capabilities": true, "hostServices": true, "redconCommandLevels": true, "requiredAttributes": true, "searchableAttributes": true}
	requiredListLeafFields = []string{"capabilities", "requiredAttributes", "searchableAttributes"}
	recordKindValues       = map[string]bool{kindTownType: true, kindRigType: true, kindDeviceType: true}
)

type EnlistError struct{ Message string }

func (e EnlistError) Error() string { return e.Message }

func enlistError(format string, args ...any) error {
	if len(args) == 0 {
		return EnlistError{Message: format}
	}
	return EnlistError{Message: fmt.Sprintf(format, args...)}
}

func errorType(err error) string {
	var enlistErr EnlistError
	if errors.As(err, &enlistErr) {
		return "EnlistError"
	}
	return "Error"
}

func utcNowISO() string {
	return time.Now().UTC().Format("2006-01-02T15:04:05Z")
}

func pyReprString(value string) string {
	return "'" + strings.ReplaceAll(strings.ReplaceAll(value, "\\", "\\\\"), "'", "\\'") + "'"
}

func pyReprValue(value any, ok bool) string {
	if !ok || value == nil {
		return "None"
	}
	if text, ok := value.(string); ok {
		return pyReprString(text)
	}
	body, _ := json.Marshal(value)
	return string(body)
}

func errorIsNotFound(err error) bool {
	text := fmt.Sprintf("%#v %v", err, err)
	return strings.Contains(text, "ResourceNotFoundException") ||
		strings.Contains(text, "ResourceNotFound") ||
		strings.Contains(text, "NotFoundException") ||
		strings.Contains(text, "NotFound")
}

func errorIsAlreadyExists(err error) bool {
	text := fmt.Sprintf("%#v %v", err, err)
	return strings.Contains(text, "ResourceAlreadyExistsException") ||
		strings.Contains(text, "ResourceAlreadyExists") ||
		strings.Contains(text, "AlreadyExists")
}

func normalizeSlugText(label, value string) (string, error) {
	text := strings.ToLower(strings.TrimSpace(value))
	if text == "" {
		return "", enlistError("%s must be non-empty", label)
	}
	var b strings.Builder
	previousDash := false
	for _, ch := range text {
		mapped := ch
		if !(ch >= 'a' && ch <= 'z' || ch >= '0' && ch <= '9' || ch == '-') {
			mapped = '-'
		}
		if mapped == '-' {
			if b.Len() > 0 && !previousDash {
				b.WriteByte('-')
			}
			previousDash = true
		} else {
			b.WriteRune(mapped)
			previousDash = false
		}
	}
	normalized := strings.TrimRight(b.String(), "-")
	if normalized == "" || strings.HasPrefix(normalized, "-") || strings.HasSuffix(normalized, "-") || strings.Contains(normalized, "--") {
		return "", enlistError("%s must normalize to '^[a-z0-9]+(?:-[a-z0-9]+)*$'; got %q", label, value)
	}
	return normalized, nil
}

func rigTypeGroupName(rigType string) (string, error) {
	normalized, err := normalizeSlugText("rig type", rigType)
	if err != nil {
		return "", err
	}
	return rigTypeThingGroupPrefix + normalized, nil
}

func requireTextFromValue(mapping map[string]any, key, context string) (string, error) {
	value, ok := mapping[key].(string)
	if !ok || strings.TrimSpace(value) == "" {
		return "", enlistError("%s is missing required field %q", context, key)
	}
	return strings.TrimSpace(value), nil
}

func optionalTextFromValue(mapping map[string]any, key string) (string, bool) {
	value, ok := mapping[key].(string)
	if !ok {
		return "", false
	}
	value = strings.TrimSpace(value)
	return value, value != ""
}

func requireText(record map[string]any, key, context string) (string, error) {
	return requireTextFromValue(record, key, context)
}

func requireThingAttribute(attributes map[string]string, key, context string) (string, error) {
	value := strings.TrimSpace(attributes[key])
	if value == "" {
		return "", enlistError("%s is missing required field %q", context, key)
	}
	return value, nil
}

func isIoTAttributeChar(ch rune) bool {
	return ch >= 'a' && ch <= 'z' || ch >= 'A' && ch <= 'Z' || ch >= '0' && ch <= '9' ||
		strings.ContainsRune("_.,@/:#=[]-", ch)
}

func iotAttributeValue(label, value string) (string, error) {
	for _, ch := range value {
		if !isIoTAttributeChar(ch) {
			goto encode
		}
	}
	return value, nil
encode:
	var b strings.Builder
	previousDash := false
	for _, ch := range value {
		if isIoTAttributeChar(ch) {
			b.WriteRune(ch)
			previousDash = false
		} else if b.Len() > 0 && !previousDash {
			b.WriteByte('-')
			previousDash = true
		}
	}
	encoded := strings.TrimRight(b.String(), "-")
	if encoded == "" {
		return "", enlistError("IoT registry attribute %q cannot be encoded into '^[a-zA-Z0-9_.,@/:#=\\[\\]-]*$': %q", label, value)
	}
	return encoded, nil
}

func iotAttributes(attributes map[string]string) (map[string]string, error) {
	out := make(map[string]string, len(attributes))
	for key, value := range attributes {
		encoded, err := iotAttributeValue(key, value)
		if err != nil {
			return nil, err
		}
		out[key] = encoded
	}
	return out, nil
}

func listValue(record map[string]any, key, context string) ([]string, error) {
	raw, ok := record[key].([]any)
	if !ok {
		return nil, enlistError("%s is missing required list field %q", context, key)
	}
	values := make([]string, 0, len(raw))
	for _, item := range raw {
		text, ok := item.(string)
		if !ok || strings.TrimSpace(text) == "" {
			return nil, enlistError("%s is missing required list field %q", context, key)
		}
		values = append(values, strings.TrimSpace(text))
	}
	return values, nil
}

func encodeCapabilitiesSet(capabilities []string) (string, error) {
	if len(capabilities) == 0 {
		return "", enlistError("capability set must not be empty")
	}
	return strings.Join(capabilities, ","), nil
}

func parseCapabilitiesSet(value, thingName string) ([]string, error) {
	if strings.TrimSpace(value) == "" {
		return nil, enlistError("Thing %q is missing required IoT registry attribute 'capabilities'", thingName)
	}
	var capabilities []string
	seen := map[string]bool{}
	for _, raw := range strings.Split(value, ",") {
		capability := strings.TrimSpace(raw)
		if capability == "" || capability != raw {
			return nil, enlistError("Thing %q has malformed 'capabilities': %q", thingName, value)
		}
		if seen[capability] {
			return nil, enlistError("Thing %q has duplicate capability %q", thingName, capability)
		}
		seen[capability] = true
		capabilities = append(capabilities, capability)
	}
	if !seen["sparkplug"] {
		return nil, enlistError("Thing %q capability set must include 'sparkplug'", thingName)
	}
	return capabilities, nil
}

func capabilities(record map[string]any, context string) ([]string, error) {
	values, err := listValue(record, "capabilities", context)
	if err != nil {
		return nil, err
	}
	encoded, err := encodeCapabilitiesSet(values)
	if err != nil {
		return nil, err
	}
	return parseCapabilitiesSet(encoded, context)
}

func boardVideoChannelName(record map[string]any, thingName string) (string, bool, error) {
	resources, _ := record["resources"].(map[string]any)
	boardVideo, _ := resources["boardVideo"].(map[string]any)
	raw, ok := boardVideo["channelName"]
	if !ok {
		return "", false, nil
	}
	template, ok := raw.(string)
	if !ok {
		return "", false, enlistError("type catalog record %q has non-string resources.boardVideo.channelName", recordContext(record))
	}
	channel := strings.TrimSpace(strings.ReplaceAll(template, "{device_id}", thingName))
	if channel == "" {
		return "", false, enlistError("type catalog record %q has empty resources.boardVideo.channelName", recordContext(record))
	}
	return channel, true, nil
}

func recordContext(record map[string]any) string {
	if value, ok := record["path"].(string); ok && value != "" {
		return value
	}
	return "type catalog record"
}

func catalogPath(parts ...string) string {
	path := typeCatalogRoot
	for _, part := range parts {
		path += "/" + part
	}
	return path
}

func normalizeCatalogPath(value string) string {
	text := strings.TrimSpace(value)
	text = strings.TrimPrefix(text, "ssm:")
	if text == "" {
		return typeCatalogRoot
	}
	if text == typeCatalogRoot || strings.HasPrefix(text, typeCatalogRoot+"/") {
		return strings.TrimRight(text, "/")
	}
	return typeCatalogRoot + "/" + strings.Trim(text, "/")
}

func parseListLeaf(parameterName, value string) ([]any, error) {
	if strings.TrimSpace(value) == "" {
		return []any{}, nil
	}
	var items []any
	for _, raw := range strings.Split(value, ",") {
		item := strings.TrimSpace(raw)
		if item == "" {
			return nil, enlistError("SSM type catalog leaf %q contains an empty list item", parameterName)
		}
		items = append(items, item)
	}
	return items, nil
}

func assignRecordLeaf(record map[string]any, parameterName string, leafPath []string, value string) error {
	if len(leafPath) == 0 {
		return nil
	}
	var decoded any
	if len(leafPath) == 1 && listLeafFields[leafPath[0]] || len(leafPath) == 2 && leafPath[0] == "redconRules" {
		values, err := parseListLeaf(parameterName, value)
		if err != nil {
			return err
		}
		decoded = values
	} else {
		decoded = value
	}
	cursor := record
	for _, part := range leafPath[:len(leafPath)-1] {
		child, ok := cursor[part].(map[string]any)
		if !ok {
			if cursor[part] != nil {
				return enlistError("SSM type catalog leaf %q collides with another leaf", parameterName)
			}
			child = map[string]any{}
			cursor[part] = child
		}
		cursor = child
	}
	cursor[leafPath[len(leafPath)-1]] = decoded
	return nil
}

func reconstructRecordFromParameters(path string, parameters []ParameterRecord) (map[string]any, error) {
	normalized := normalizeCatalogPath(path)
	prefix := normalized + "/"
	var childPrefixes []string
	for _, parameter := range parameters {
		recordPath := strings.TrimSuffix(parameter.Name, "/kind")
		if recordPath == parameter.Name || recordPath == normalized || !strings.HasPrefix(recordPath, prefix) {
			continue
		}
		if recordKindValues[parameter.Value] {
			childPrefixes = append(childPrefixes, recordPath+"/")
		}
	}
	record := map[string]any{}
	for _, parameter := range parameters {
		if !strings.HasPrefix(parameter.Name, prefix) {
			continue
		}
		skip := false
		for _, childPrefix := range childPrefixes {
			if strings.HasPrefix(parameter.Name, childPrefix) {
				skip = true
				break
			}
		}
		if skip {
			continue
		}
		relative := parameter.Name[len(prefix):]
		if relative == "" {
			continue
		}
		if err := assignRecordLeaf(record, parameter.Name, strings.Split(relative, "/"), parameter.Value); err != nil {
			return nil, err
		}
	}
	kind, _ := record["kind"].(string)
	if !recordKindValues[kind] {
		return nil, enlistError("Missing SSM type catalog record %q; run aws::deploy", normalized)
	}
	if _, ok := record["path"]; !ok {
		record["path"] = normalized
	}
	if kind == kindRigType {
		if _, ok := record["hostServices"]; !ok {
			record["hostServices"] = []any{}
		}
	}
	for _, field := range requiredListLeafFields {
		values, ok := record[field].([]any)
		if !ok || len(values) == 0 {
			return nil, enlistError("SSM type catalog record %q is missing %s", normalized, field)
		}
		for _, value := range values {
			if text, ok := value.(string); !ok || strings.TrimSpace(text) == "" {
				return nil, enlistError("SSM type catalog record %q is missing %s", normalized, field)
			}
		}
	}
	return record, nil
}

func sparkplugShadowPayload(payload any, topic any, projection map[string]any) map[string]any {
	reported := map[string]any{"payload": payload}
	if topic != nil {
		reported["topic"] = topic
	}
	if len(projection) > 0 {
		reported["projection"] = projection
	}
	return map[string]any{"state": map[string]any{"reported": reported}}
}

func staticGroupShadowPayload(string) map[string]any {
	return sparkplugShadowPayload(map[string]any{"metrics": map[string]any{"redcon": 1}}, nil, nil)
}

func offlineNodeShadowPayload(groupID, edgeNodeID string) map[string]any {
	return sparkplugShadowPayload(
		map[string]any{"metrics": map[string]any{"redcon": 4}},
		map[string]any{"namespace": sparkplugNamespace, "groupId": groupID, "messageType": "NDEATH", "edgeNodeId": edgeNodeID},
		nil,
	)
}

func offlineDeviceShadowPayload(groupID, edgeNodeID, deviceID string) map[string]any {
	return sparkplugShadowPayload(
		map[string]any{"metrics": map[string]any{}},
		map[string]any{"namespace": sparkplugNamespace, "groupId": groupID, "messageType": "DDEATH", "edgeNodeId": edgeNodeID, "deviceId": deviceID},
		nil,
	)
}

type ThingRecord struct {
	ThingName     string
	ThingTypeName string
	Attributes    map[string]string
	Version       *int64
}

type SearchPage struct {
	ThingNames []string
	NextToken  *string
}

type ParameterRecord struct {
	Name  string
	Value string
}

type ParameterPage struct {
	Parameters []ParameterRecord
	NextToken  *string
}

type PrincipalPage struct {
	Principals []string
	NextToken  *string
}

type ThingGroupMembershipPage struct {
	ThingGroupNames []string
	NextToken       *string
}

type AWSClientAPI interface {
	DescribeThing(ctx context.Context, thingName string) (*ThingRecord, error)
	CreateThing(ctx context.Context, thingName, thingTypeName string, attributes map[string]string) error
	UpdateThingAttributes(ctx context.Context, thingName string, attributes map[string]string, expectedVersion *int64) error
	DeleteThing(ctx context.Context, thingName string) (bool, error)
	SearchIndex(ctx context.Context, query string, nextToken *string) (SearchPage, error)
	GetShadow(ctx context.Context, thingName, shadowName string) ([]byte, bool, error)
	UpdateShadow(ctx context.Context, thingName, shadowName string, payload []byte) error
	DeleteShadow(ctx context.Context, thingName, shadowName string) (bool, error)
	GetParametersByPath(ctx context.Context, path string, nextToken *string) (ParameterPage, error)
	ListThingPrincipals(ctx context.Context, thingName string, nextToken *string) (PrincipalPage, error)
	DetachThingPrincipal(ctx context.Context, thingName, principal string) error
	CreateThingGroup(ctx context.Context, thingGroupName string) error
	ListThingGroupsForThing(ctx context.Context, thingName string, nextToken *string) (ThingGroupMembershipPage, error)
	AddThingToThingGroup(ctx context.Context, thingName, thingGroupName string) error
	RemoveThingFromThingGroup(ctx context.Context, thingName, thingGroupName string) error
	EnsureSignalingChannel(ctx context.Context, channelName string) (bool, error)
}

type AWSClient struct {
	iot          *iot.Client
	iotData      *iotdataplane.Client
	kinesisVideo *kinesisvideo.Client
	ssm          *ssm.Client
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
		iot:          iotClient,
		iotData:      iotData,
		kinesisVideo: kinesisvideo.NewFromConfig(cfg),
		ssm:          ssm.NewFromConfig(cfg),
	}, nil
}

func (c *AWSClient) DescribeThing(ctx context.Context, thingName string) (*ThingRecord, error) {
	out, err := c.iot.DescribeThing(ctx, &iot.DescribeThingInput{ThingName: aws.String(thingName)})
	if err != nil {
		if errorIsNotFound(err) {
			return nil, nil
		}
		return nil, fmt.Errorf("describe AWS IoT thing: %w", err)
	}
	if out.ThingName == nil || out.ThingTypeName == nil {
		return nil, enlistError("Thing %q returned invalid thing record", thingName)
	}
	version := out.Version
	return &ThingRecord{ThingName: *out.ThingName, ThingTypeName: *out.ThingTypeName, Attributes: cloneStringMap(out.Attributes), Version: &version}, nil
}

func (c *AWSClient) CreateThing(ctx context.Context, thingName, thingTypeName string, attributes map[string]string) error {
	_, err := c.iot.CreateThing(ctx, &iot.CreateThingInput{
		ThingName:        aws.String(thingName),
		ThingTypeName:    aws.String(thingTypeName),
		AttributePayload: &iottypes.AttributePayload{Attributes: attributes},
	})
	return err
}

func (c *AWSClient) UpdateThingAttributes(ctx context.Context, thingName string, attributes map[string]string, expectedVersion *int64) error {
	_, err := c.iot.UpdateThing(ctx, &iot.UpdateThingInput{
		ThingName:        aws.String(thingName),
		AttributePayload: &iottypes.AttributePayload{Attributes: attributes, Merge: true},
		ExpectedVersion:  expectedVersion,
	})
	return err
}

func (c *AWSClient) DeleteThing(ctx context.Context, thingName string) (bool, error) {
	_, err := c.iot.DeleteThing(ctx, &iot.DeleteThingInput{ThingName: aws.String(thingName)})
	if err != nil {
		if errorIsNotFound(err) {
			return false, nil
		}
		return false, err
	}
	return true, nil
}

func (c *AWSClient) SearchIndex(ctx context.Context, query string, nextToken *string) (SearchPage, error) {
	out, err := c.iot.SearchIndex(ctx, &iot.SearchIndexInput{
		IndexName:   aws.String(thingIndexName),
		QueryString: aws.String(query),
		MaxResults:  aws.Int32(100),
		NextToken:   nextToken,
	})
	if err != nil {
		return SearchPage{}, err
	}
	var names []string
	for _, thing := range out.Things {
		if thing.ThingName != nil && strings.TrimSpace(*thing.ThingName) != "" {
			names = append(names, strings.TrimSpace(*thing.ThingName))
		}
	}
	return SearchPage{ThingNames: names, NextToken: blankPtrToNil(out.NextToken)}, nil
}

func (c *AWSClient) GetShadow(ctx context.Context, thingName, shadowName string) ([]byte, bool, error) {
	out, err := c.iotData.GetThingShadow(ctx, &iotdataplane.GetThingShadowInput{ThingName: aws.String(thingName), ShadowName: aws.String(shadowName)})
	if err != nil {
		if errorIsNotFound(err) {
			return nil, false, nil
		}
		return nil, false, err
	}
	return out.Payload, out.Payload != nil, nil
}

func (c *AWSClient) UpdateShadow(ctx context.Context, thingName, shadowName string, payload []byte) error {
	_, err := c.iotData.UpdateThingShadow(ctx, &iotdataplane.UpdateThingShadowInput{ThingName: aws.String(thingName), ShadowName: aws.String(shadowName), Payload: payload})
	return err
}

func (c *AWSClient) DeleteShadow(ctx context.Context, thingName, shadowName string) (bool, error) {
	_, err := c.iotData.DeleteThingShadow(ctx, &iotdataplane.DeleteThingShadowInput{ThingName: aws.String(thingName), ShadowName: aws.String(shadowName)})
	if err != nil {
		if errorIsNotFound(err) {
			return false, nil
		}
		return false, err
	}
	return true, nil
}

func (c *AWSClient) GetParametersByPath(ctx context.Context, path string, nextToken *string) (ParameterPage, error) {
	out, err := c.ssm.GetParametersByPath(ctx, &ssm.GetParametersByPathInput{Path: aws.String(path), Recursive: true, WithDecryption: false, NextToken: nextToken})
	if err != nil {
		return ParameterPage{}, err
	}
	var parameters []ParameterRecord
	for _, parameter := range out.Parameters {
		if parameter.Name != nil && parameter.Value != nil {
			parameters = append(parameters, ParameterRecord{Name: *parameter.Name, Value: *parameter.Value})
		}
	}
	return ParameterPage{Parameters: parameters, NextToken: blankPtrToNil(out.NextToken)}, nil
}

func (c *AWSClient) ListThingPrincipals(ctx context.Context, thingName string, nextToken *string) (PrincipalPage, error) {
	out, err := c.iot.ListThingPrincipals(ctx, &iot.ListThingPrincipalsInput{ThingName: aws.String(thingName), NextToken: nextToken})
	if err != nil {
		if errorIsNotFound(err) {
			return PrincipalPage{}, nil
		}
		return PrincipalPage{}, err
	}
	return PrincipalPage{Principals: out.Principals, NextToken: blankPtrToNil(out.NextToken)}, nil
}

func (c *AWSClient) DetachThingPrincipal(ctx context.Context, thingName, principal string) error {
	_, err := c.iot.DetachThingPrincipal(ctx, &iot.DetachThingPrincipalInput{ThingName: aws.String(thingName), Principal: aws.String(principal)})
	if err != nil && errorIsNotFound(err) {
		return nil
	}
	return err
}

func (c *AWSClient) CreateThingGroup(ctx context.Context, thingGroupName string) error {
	_, err := c.iot.CreateThingGroup(ctx, &iot.CreateThingGroupInput{ThingGroupName: aws.String(thingGroupName)})
	if err != nil && errorIsAlreadyExists(err) {
		return nil
	}
	return err
}

func (c *AWSClient) ListThingGroupsForThing(ctx context.Context, thingName string, nextToken *string) (ThingGroupMembershipPage, error) {
	out, err := c.iot.ListThingGroupsForThing(ctx, &iot.ListThingGroupsForThingInput{ThingName: aws.String(thingName), NextToken: nextToken})
	if err != nil {
		if errorIsNotFound(err) {
			return ThingGroupMembershipPage{}, nil
		}
		return ThingGroupMembershipPage{}, err
	}
	var names []string
	for _, group := range out.ThingGroups {
		if group.GroupName != nil && strings.TrimSpace(*group.GroupName) != "" {
			names = append(names, strings.TrimSpace(*group.GroupName))
		}
	}
	return ThingGroupMembershipPage{ThingGroupNames: names, NextToken: blankPtrToNil(out.NextToken)}, nil
}

func (c *AWSClient) AddThingToThingGroup(ctx context.Context, thingName, thingGroupName string) error {
	_, err := c.iot.AddThingToThingGroup(ctx, &iot.AddThingToThingGroupInput{ThingName: aws.String(thingName), ThingGroupName: aws.String(thingGroupName)})
	return err
}

func (c *AWSClient) RemoveThingFromThingGroup(ctx context.Context, thingName, thingGroupName string) error {
	_, err := c.iot.RemoveThingFromThingGroup(ctx, &iot.RemoveThingFromThingGroupInput{ThingName: aws.String(thingName), ThingGroupName: aws.String(thingGroupName)})
	if err != nil && errorIsNotFound(err) {
		return nil
	}
	return err
}

func (c *AWSClient) EnsureSignalingChannel(ctx context.Context, channelName string) (bool, error) {
	_, err := c.kinesisVideo.DescribeSignalingChannel(ctx, &kinesisvideo.DescribeSignalingChannelInput{ChannelName: aws.String(channelName)})
	if err == nil {
		return false, nil
	}
	if !errorIsNotFound(err) {
		return false, err
	}
	_, err = c.kinesisVideo.CreateSignalingChannel(ctx, &kinesisvideo.CreateSignalingChannelInput{
		ChannelName: aws.String(channelName),
		ChannelType: kvtypes.ChannelTypeSingleMaster,
		SingleMasterConfiguration: &kvtypes.SingleMasterConfiguration{
			MessageTtlSeconds: aws.Int32(60),
		},
	})
	if err != nil && errorIsAlreadyExists(err) {
		return false, nil
	}
	return err == nil, err
}

type ShortIDSource interface {
	NextShortID() string
}

type RandomShortIDs struct{}

func (RandomShortIDs) NextShortID() string {
	var b strings.Builder
	max := big.NewInt(int64(len(shortIDAlphabet)))
	for i := 0; i < shortIDLength; i++ {
		n, err := rand.Int(rand.Reader, max)
		if err != nil {
			b.WriteByte(shortIDAlphabet[0])
			continue
		}
		b.WriteByte(shortIDAlphabet[n.Int64()])
	}
	return b.String()
}

type EnlistResult struct {
	ThingName          string
	ThingTypeName      string
	Created            bool
	Attributes         map[string]string
	InitializedShadows []string
	AuxiliaryResources map[string]any
}

func (r EnlistResult) Payload() map[string]any {
	return map[string]any{
		"thingName":          r.ThingName,
		"thingTypeName":      r.ThingTypeName,
		"created":            r.Created,
		"attributes":         r.Attributes,
		"initializedShadows": r.InitializedShadows,
		"auxiliaryResources": r.AuxiliaryResources,
	}
}

type DischargeResult struct {
	ThingName          string
	ThingTypeName      *string
	Deleted            bool
	Attributes         map[string]string
	DeletedShadows     []string
	DetachedPrincipals []string
	AuxiliaryResources map[string]any
}

func missingDischargeResult(thingName string) DischargeResult {
	return DischargeResult{ThingName: thingName, Attributes: map[string]string{}, AuxiliaryResources: map[string]any{}}
}

func (r DischargeResult) Payload() map[string]any {
	return map[string]any{
		"thingName":          r.ThingName,
		"thingTypeName":      stringPtrValue(r.ThingTypeName),
		"deleted":            r.Deleted,
		"attributes":         r.Attributes,
		"deletedShadows":     r.DeletedShadows,
		"detachedPrincipals": r.DetachedPrincipals,
		"auxiliaryResources": r.AuxiliaryResources,
	}
}

type Service struct {
	aws AWSClientAPI
	ids ShortIDSource
}

func NewService(aws AWSClientAPI, ids ShortIDSource) *Service {
	return &Service{aws: aws, ids: ids}
}

func (s *Service) Handle(ctx context.Context, event map[string]any) (map[string]any, error) {
	action, err := requireTextFromValue(event, "action", "enlist event")
	if err != nil {
		return nil, err
	}
	switch action {
	case "enlistTown":
		townName, err := requireTextFromValue(event, "townName", "enlistTown")
		if err != nil {
			return nil, err
		}
		result, err := s.EnlistTown(ctx, townName)
		if err != nil {
			return nil, err
		}
		return result.Payload(), nil
	case "enlistRig":
		townID, err := requireTextFromValue(event, "townId", "enlistRig")
		if err != nil {
			return nil, err
		}
		rigType, err := requireTextFromValue(event, "rigType", "enlistRig")
		if err != nil {
			return nil, err
		}
		rigName, err := requireTextFromValue(event, "rigName", "enlistRig")
		if err != nil {
			return nil, err
		}
		result, err := s.EnlistRig(ctx, townID, rigType, rigName)
		if err != nil {
			return nil, err
		}
		return result.Payload(), nil
	case "enlistDevice":
		rigID, err := requireTextFromValue(event, "rigId", "enlistDevice")
		if err != nil {
			return nil, err
		}
		deviceType, err := requireTextFromValue(event, "deviceType", "enlistDevice")
		if err != nil {
			return nil, err
		}
		deviceName, _ := optionalTextFromValue(event, "deviceName")
		result, err := s.EnlistDevice(ctx, rigID, deviceType, deviceName)
		if err != nil {
			return nil, err
		}
		return result.Payload(), nil
	case "assignDevice":
		deviceID, err := requireTextFromValue(event, "deviceId", "assignDevice")
		if err != nil {
			return nil, err
		}
		rigID, err := requireTextFromValue(event, "rigId", "assignDevice")
		if err != nil {
			return nil, err
		}
		result, err := s.AssignDevice(ctx, deviceID, rigID)
		if err != nil {
			return nil, err
		}
		return result.Payload(), nil
	case "dischargeThing":
		thingID, err := requireTextFromValue(event, "thingId", "dischargeThing")
		if err != nil {
			return nil, err
		}
		result, err := s.DischargeThing(ctx, thingID)
		if err != nil {
			return nil, err
		}
		return result.Payload(), nil
	case "dischargeAll":
		return s.DischargeAll(ctx)
	default:
		return nil, enlistError("unsupported enlist action: %s", pyReprString(action))
	}
}

func (s *Service) describeThing(ctx context.Context, thingName string) (*ThingRecord, error) {
	thing, err := s.aws.DescribeThing(ctx, thingName)
	if err != nil {
		return nil, err
	}
	if thing == nil {
		return nil, enlistError("Thing %q is not registered", thingName)
	}
	return thing, nil
}

func (s *Service) allocateThingName(ctx context.Context, thingType string) (string, string, error) {
	prefix, err := normalizeSlugText("thing type", thingType)
	if err != nil {
		return "", "", err
	}
	for i := 0; i < 256; i++ {
		shortID := s.ids.NextShortID()
		thingName := prefix + "-" + shortID
		thing, err := s.aws.DescribeThing(ctx, thingName)
		if err != nil {
			return "", "", err
		}
		if thing == nil {
			return thingName, shortID, nil
		}
	}
	return "", "", enlistError("failed to allocate a unique thing name for type %q", thingType)
}

func (s *Service) searchThingNames(ctx context.Context, query string) ([]string, error) {
	seen := map[string]bool{}
	var names []string
	var next *string
	for {
		page, err := s.aws.SearchIndex(ctx, query, next)
		if err != nil {
			return nil, fmt.Errorf("search AWS IoT thing index for %q: %w", query, err)
		}
		for _, name := range page.ThingNames {
			if !seen[name] {
				seen[name] = true
				names = append(names, name)
			}
		}
		next = page.NextToken
		if next == nil {
			sort.Strings(names)
			return names, nil
		}
	}
}

func (s *Service) searchOne(ctx context.Context, query, missing, multiple string) (*ThingRecord, error) {
	names, err := s.searchThingNames(ctx, query)
	if err != nil {
		return nil, err
	}
	if len(names) == 0 {
		return nil, enlistError(missing)
	}
	if len(names) > 1 {
		return nil, enlistError(multiple)
	}
	return s.describeThing(ctx, names[0])
}

func (s *Service) findTown(ctx context.Context, townName string) (*ThingRecord, error) {
	thing, err := s.searchOne(ctx,
		fmt.Sprintf("thingTypeName:%s AND attributes.kind:%s AND attributes.name:%s", townThingType, kindTownType, townName),
		fmt.Sprintf("Town %q is not registered", townName),
		fmt.Sprintf("Town %q matched multiple things", townName))
	if err != nil {
		if strings.Contains(err.Error(), "is not registered") {
			return nil, nil
		}
		return nil, err
	}
	return thing, nil
}

func (s *Service) findRig(ctx context.Context, townID, rigType, rigName string) (*ThingRecord, error) {
	thing, err := s.searchOne(ctx,
		fmt.Sprintf("thingTypeName:%s AND attributes.kind:%s AND attributes.name:%s AND attributes.%s:%s", rigType, kindRigType, rigName, townIDAttribute, townID),
		fmt.Sprintf("Rig %q is not registered under town %q", rigName, townID),
		fmt.Sprintf("Rig %q matched multiple things under town %q", rigName, townID))
	if err != nil {
		if strings.Contains(err.Error(), "is not registered") {
			return nil, nil
		}
		return nil, err
	}
	return thing, nil
}

func (s *Service) findDevice(ctx context.Context, rigID, deviceType, deviceName string) (*ThingRecord, error) {
	thing, err := s.searchOne(ctx,
		fmt.Sprintf("thingTypeName:%s AND attributes.kind:%s AND attributes.name:%s AND attributes.%s:%s", deviceType, kindDeviceType, deviceName, rigIDAttribute, rigID),
		fmt.Sprintf("Device %q is not registered under rig %q", deviceName, rigID),
		fmt.Sprintf("Device %q matched multiple things under rig %q", deviceName, rigID))
	if err != nil {
		if strings.Contains(err.Error(), "is not registered") {
			return nil, nil
		}
		return nil, err
	}
	return thing, nil
}

func (s *Service) readParametersByPath(ctx context.Context, path string) ([]ParameterRecord, error) {
	normalized := normalizeCatalogPath(path)
	var parameters []ParameterRecord
	var next *string
	for {
		page, err := s.aws.GetParametersByPath(ctx, normalized, next)
		if err != nil {
			return nil, err
		}
		parameters = append(parameters, page.Parameters...)
		next = page.NextToken
		if next == nil {
			sort.Slice(parameters, func(i, j int) bool { return parameters[i].Name < parameters[j].Name })
			return parameters, nil
		}
	}
}

func (s *Service) typeRecord(ctx context.Context, path string) (map[string]any, error) {
	normalized := normalizeCatalogPath(path)
	parameters, err := s.readParametersByPath(ctx, normalized)
	if err != nil {
		return nil, err
	}
	return reconstructRecordFromParameters(normalized, parameters)
}

func (s *Service) rigTypeRecord(ctx context.Context, rigType string) (map[string]any, error) {
	return s.typeRecord(ctx, catalogPath("town", rigType))
}

func (s *Service) deviceTypeRecord(ctx context.Context, rigType, deviceType string) (map[string]any, error) {
	return s.typeRecord(ctx, catalogPath("town", rigType, deviceType))
}

func (s *Service) deviceRecordForRig(ctx context.Context, rig *ThingRecord, deviceType string) (map[string]any, error) {
	record, err := s.deviceTypeRecord(ctx, rig.ThingTypeName, deviceType)
	if err != nil {
		return nil, enlistError("Device type %s is not compatible with rig type %s; missing SSM type catalog record %s", pyReprString(deviceType), pyReprString(rig.ThingTypeName), pyReprString(catalogPath("town", rig.ThingTypeName, deviceType)))
	}
	return record, nil
}

func (s *Service) baseAttributes(record map[string]any, name, shortID string) (map[string]string, error) {
	context := recordContext(record)
	kind, err := requireText(record, "kind", context)
	if err != nil {
		return nil, err
	}
	typePath, err := requireText(record, "path", context)
	if err != nil {
		return nil, err
	}
	displayName, err := requireText(record, "displayName", context)
	if err != nil {
		return nil, err
	}
	caps, err := capabilities(record, context)
	if err != nil {
		return nil, err
	}
	capSet, err := encodeCapabilitiesSet(caps)
	if err != nil {
		return nil, err
	}
	attributes := map[string]string{"name": name, "shortId": shortID, "kind": kind, "typePath": typePath, "displayName": displayName, "capabilities": capSet}
	if _, ok := record["redconCommandLevels"]; ok {
		levels, err := listValue(record, "redconCommandLevels", context)
		if err != nil {
			return nil, err
		}
		attributes["redconCommandLevels"] = strings.Join(levels, ",")
	}
	return iotAttributes(attributes)
}

func (s *Service) updateThingAttributes(ctx context.Context, thing *ThingRecord, attributes map[string]string) error {
	return s.aws.UpdateThingAttributes(ctx, thing.ThingName, attributes, thing.Version)
}

func (s *Service) listThingGroupNames(ctx context.Context, thingName string) ([]string, error) {
	seen := map[string]bool{}
	var names []string
	var next *string
	for {
		page, err := s.aws.ListThingGroupsForThing(ctx, thingName, next)
		if err != nil {
			return nil, err
		}
		for _, name := range page.ThingGroupNames {
			if !seen[name] {
				seen[name] = true
				names = append(names, name)
			}
		}
		next = page.NextToken
		if next == nil {
			sort.Strings(names)
			return names, nil
		}
	}
}

func (s *Service) ensureRigTypeGroupMembership(ctx context.Context, thingName, rigType string) (string, error) {
	target, err := rigTypeGroupName(rigType)
	if err != nil {
		return "", err
	}
	if err := s.aws.CreateThingGroup(ctx, target); err != nil {
		return "", err
	}
	groups, err := s.listThingGroupNames(ctx, thingName)
	if err != nil {
		return "", err
	}
	for _, group := range groups {
		if strings.HasPrefix(group, rigTypeThingGroupPrefix) && group != target {
			if err := s.aws.RemoveThingFromThingGroup(ctx, thingName, group); err != nil {
				return "", err
			}
		}
	}
	if err := s.aws.AddThingToThingGroup(ctx, thingName, target); err != nil {
		return "", err
	}
	return target, nil
}

type shadowPayload struct {
	jsonValue any
	text      string
	isText    bool
}

func jsonShadow(value any) shadowPayload { return shadowPayload{jsonValue: value} }
func textShadow(value string) shadowPayload {
	return shadowPayload{text: value, isText: true}
}
func (p shadowPayload) bytes() ([]byte, error) {
	if p.isText {
		return []byte(p.text), nil
	}
	return json.Marshal(p.jsonValue)
}

func (s *Service) ensureShadow(ctx context.Context, thingName, shadowName string, payload shadowPayload) (bool, error) {
	if _, ok, err := s.aws.GetShadow(ctx, thingName, shadowName); err != nil {
		return false, err
	} else if ok {
		return false, nil
	}
	body, err := payload.bytes()
	if err != nil {
		return false, err
	}
	if err := s.aws.UpdateShadow(ctx, thingName, shadowName, body); err != nil {
		return false, err
	}
	return true, nil
}

func (s *Service) initializeTownShadows(ctx context.Context, thingName string) ([]string, error) {
	if ok, err := s.ensureShadow(ctx, thingName, "sparkplug", jsonShadow(staticGroupShadowPayload(thingName))); err != nil {
		return nil, err
	} else if ok {
		return []string{"sparkplug"}, nil
	}
	return []string{}, nil
}

func (s *Service) initializeRigShadows(ctx context.Context, thingName, townID, rigID string) ([]string, error) {
	if ok, err := s.ensureShadow(ctx, thingName, "sparkplug", jsonShadow(offlineNodeShadowPayload(townID, rigID))); err != nil {
		return nil, err
	} else if ok {
		return []string{"sparkplug"}, nil
	}
	return []string{}, nil
}

func (s *Service) initializeDeviceShadows(ctx context.Context, thingName string, record map[string]any, townID, rigID string) ([]string, error) {
	caps, err := capabilities(record, recordContext(record))
	if err != nil {
		return nil, err
	}
	var initialized []string
	for _, shadowName := range caps {
		var payload shadowPayload
		if shadowName == "sparkplug" {
			payload = jsonShadow(offlineDeviceShadowPayload(townID, rigID, thingName))
		} else {
			shadows, _ := record["shadows"].(map[string]any)
			shadowRecord, _ := shadows[shadowName].(map[string]any)
			defaultPayload, err := requireText(shadowRecord, "defaultPayload", fmt.Sprintf("shadow %q", shadowName))
			if err != nil {
				return nil, enlistError("type catalog record %q is missing shadow %q", recordContext(record), shadowName)
			}
			payload = textShadow(defaultPayload)
		}
		ok, err := s.ensureShadow(ctx, thingName, shadowName, payload)
		if err != nil {
			return nil, err
		}
		if ok {
			initialized = append(initialized, shadowName)
		}
	}
	return initialized, nil
}

func (s *Service) ensureAuxiliaryResources(ctx context.Context, thingName string, record map[string]any) (map[string]any, error) {
	resources := map[string]any{}
	if channel, ok, err := boardVideoChannelName(record, thingName); err != nil {
		return nil, err
	} else if ok {
		created, err := s.aws.EnsureSignalingChannel(ctx, channel)
		if err != nil {
			return nil, err
		}
		resources["boardVideo"] = map[string]any{"channelName": channel, "created": created}
	}
	return resources, nil
}

func thingResult(thing *ThingRecord, created bool, attributes map[string]string, initialized []string, resources map[string]any) EnlistResult {
	return EnlistResult{ThingName: thing.ThingName, ThingTypeName: thing.ThingTypeName, Created: created, Attributes: attributes, InitializedShadows: initialized, AuxiliaryResources: resources}
}

func (s *Service) EnlistTown(ctx context.Context, townName string) (EnlistResult, error) {
	normalizedTownName, err := normalizeSlugText("town name", townName)
	if err != nil {
		return EnlistResult{}, err
	}
	record, err := s.typeRecord(ctx, catalogPath("town"))
	if err != nil {
		return EnlistResult{}, err
	}
	existing, err := s.findTown(ctx, normalizedTownName)
	if err != nil {
		return EnlistResult{}, err
	}
	created := existing == nil
	var thing *ThingRecord
	if existing != nil {
		shortID, err := requireThingAttribute(existing.Attributes, "shortId", "town attributes")
		if err != nil {
			return EnlistResult{}, err
		}
		attributes, err := s.baseAttributes(record, normalizedTownName, shortID)
		if err != nil {
			return EnlistResult{}, err
		}
		if err := s.updateThingAttributes(ctx, existing, attributes); err != nil {
			return EnlistResult{}, err
		}
		thing, err = s.describeThing(ctx, existing.ThingName)
		if err != nil {
			return EnlistResult{}, err
		}
	} else {
		thingName, shortID, err := s.allocateThingName(ctx, townThingType)
		if err != nil {
			return EnlistResult{}, err
		}
		attributes, err := s.baseAttributes(record, normalizedTownName, shortID)
		if err != nil {
			return EnlistResult{}, err
		}
		if err := s.aws.CreateThing(ctx, thingName, townThingType, attributes); err != nil {
			return EnlistResult{}, err
		}
		thing, err = s.describeThing(ctx, thingName)
		if err != nil {
			return EnlistResult{}, err
		}
	}
	shortID, err := requireThingAttribute(thing.Attributes, "shortId", "town attributes")
	if err != nil {
		return EnlistResult{}, err
	}
	attributes, err := s.baseAttributes(record, normalizedTownName, shortID)
	if err != nil {
		return EnlistResult{}, err
	}
	initialized, err := s.initializeTownShadows(ctx, thing.ThingName)
	if err != nil {
		return EnlistResult{}, err
	}
	return thingResult(thing, created, attributes, initialized, map[string]any{}), nil
}

func (s *Service) EnlistRig(ctx context.Context, townID, rigType, rigName string) (EnlistResult, error) {
	normalizedTownID, err := normalizeSlugText("town id", townID)
	if err != nil {
		return EnlistResult{}, err
	}
	normalizedRigType, err := normalizeSlugText("rig type", rigType)
	if err != nil {
		return EnlistResult{}, err
	}
	normalizedRigName, err := normalizeSlugText("rig name", rigName)
	if err != nil {
		return EnlistResult{}, err
	}
	town, err := s.describeThing(ctx, normalizedTownID)
	if err != nil {
		return EnlistResult{}, err
	}
	if town.ThingTypeName != townThingType || town.Attributes["kind"] != kindTownType {
		return EnlistResult{}, enlistError("Thing %q is not a town", normalizedTownID)
	}
	record, err := s.rigTypeRecord(ctx, normalizedRigType)
	if err != nil {
		return EnlistResult{}, err
	}
	existing, err := s.findRig(ctx, normalizedTownID, normalizedRigType, normalizedRigName)
	if err != nil {
		return EnlistResult{}, err
	}
	created := existing == nil
	hostServices := []string{}
	if _, ok := record["hostServices"]; ok {
		hostServices, err = listValue(record, "hostServices", recordContext(record))
		if err != nil {
			return EnlistResult{}, err
		}
	}
	buildAttributes := func(shortID string) (map[string]string, error) {
		attributes, err := s.baseAttributes(record, normalizedRigName, shortID)
		if err != nil {
			return nil, err
		}
		attributes[townIDAttribute] = normalizedTownID
		attributes["rigType"] = normalizedRigType
		if len(hostServices) > 0 {
			attributes["hostServices"] = strings.Join(hostServices, ",")
		}
		return attributes, nil
	}
	var thing *ThingRecord
	if existing != nil {
		shortID, err := requireThingAttribute(existing.Attributes, "shortId", "rig attributes")
		if err != nil {
			return EnlistResult{}, err
		}
		attributes, err := buildAttributes(shortID)
		if err != nil {
			return EnlistResult{}, err
		}
		if err := s.updateThingAttributes(ctx, existing, attributes); err != nil {
			return EnlistResult{}, err
		}
		thing, err = s.describeThing(ctx, existing.ThingName)
		if err != nil {
			return EnlistResult{}, err
		}
	} else {
		thingName, shortID, err := s.allocateThingName(ctx, normalizedRigType)
		if err != nil {
			return EnlistResult{}, err
		}
		attributes, err := buildAttributes(shortID)
		if err != nil {
			return EnlistResult{}, err
		}
		if err := s.aws.CreateThing(ctx, thingName, normalizedRigType, attributes); err != nil {
			return EnlistResult{}, err
		}
		thing, err = s.describeThing(ctx, thingName)
		if err != nil {
			return EnlistResult{}, err
		}
	}
	shortID, err := requireThingAttribute(thing.Attributes, "shortId", "rig attributes")
	if err != nil {
		return EnlistResult{}, err
	}
	attributes, err := buildAttributes(shortID)
	if err != nil {
		return EnlistResult{}, err
	}
	initialized, err := s.initializeRigShadows(ctx, thing.ThingName, normalizedTownID, thing.ThingName)
	if err != nil {
		return EnlistResult{}, err
	}
	groupName, err := s.ensureRigTypeGroupMembership(ctx, thing.ThingName, normalizedRigType)
	if err != nil {
		return EnlistResult{}, err
	}
	return thingResult(thing, created, attributes, initialized, map[string]any{"thingGroupName": groupName}), nil
}

func (s *Service) EnlistDevice(ctx context.Context, rigID, deviceType, deviceName string) (EnlistResult, error) {
	normalizedRigID, err := normalizeSlugText("rig id", rigID)
	if err != nil {
		return EnlistResult{}, err
	}
	normalizedDeviceType, err := normalizeSlugText("device type", deviceType)
	if err != nil {
		return EnlistResult{}, err
	}
	rig, err := s.describeThing(ctx, normalizedRigID)
	if err != nil {
		return EnlistResult{}, err
	}
	if rig.Attributes["kind"] != kindRigType {
		return EnlistResult{}, enlistError("Thing %q is not a rig", normalizedRigID)
	}
	townID, err := requireThingAttribute(rig.Attributes, townIDAttribute, "rig attributes")
	if err != nil {
		return EnlistResult{}, err
	}
	town, err := s.describeThing(ctx, townID)
	if err != nil {
		return EnlistResult{}, err
	}
	if town.Attributes["kind"] != kindTownType {
		return EnlistResult{}, enlistError("Thing %q is not a town", townID)
	}
	record, err := s.deviceRecordForRig(ctx, rig, normalizedDeviceType)
	if err != nil {
		return EnlistResult{}, err
	}
	defaultName, err := requireText(record, "defaultName", recordContext(record))
	if err != nil {
		return EnlistResult{}, err
	}
	if deviceName == "" {
		deviceName = defaultName
	}
	normalizedDeviceName, err := normalizeSlugText("device name", deviceName)
	if err != nil {
		return EnlistResult{}, err
	}
	existing, err := s.findDevice(ctx, normalizedRigID, normalizedDeviceType, normalizedDeviceName)
	if err != nil {
		return EnlistResult{}, err
	}
	created := existing == nil
	buildAttributes := func(shortID string) (map[string]string, error) {
		attributes, err := s.baseAttributes(record, normalizedDeviceName, shortID)
		if err != nil {
			return nil, err
		}
		attributes[townIDAttribute] = townID
		attributes[rigIDAttribute] = normalizedRigID
		attributes["rigType"] = rig.ThingTypeName
		attributes["deviceType"] = normalizedDeviceType
		if web, _ := record["web"].(map[string]any); web != nil {
			if adapter, ok := web["adapter"].(string); ok {
				attributes["webAdapter"] = adapter
			}
		}
		return iotAttributes(attributes)
	}
	var thing *ThingRecord
	if existing != nil {
		shortID, err := requireThingAttribute(existing.Attributes, "shortId", "device attributes")
		if err != nil {
			return EnlistResult{}, err
		}
		attributes, err := buildAttributes(shortID)
		if err != nil {
			return EnlistResult{}, err
		}
		if err := s.updateThingAttributes(ctx, existing, attributes); err != nil {
			return EnlistResult{}, err
		}
		thing, err = s.describeThing(ctx, existing.ThingName)
		if err != nil {
			return EnlistResult{}, err
		}
	} else {
		thingName, shortID, err := s.allocateThingName(ctx, normalizedDeviceType)
		if err != nil {
			return EnlistResult{}, err
		}
		attributes, err := buildAttributes(shortID)
		if err != nil {
			return EnlistResult{}, err
		}
		if err := s.aws.CreateThing(ctx, thingName, normalizedDeviceType, attributes); err != nil {
			return EnlistResult{}, err
		}
		thing, err = s.describeThing(ctx, thingName)
		if err != nil {
			return EnlistResult{}, err
		}
	}
	shortID, err := requireThingAttribute(thing.Attributes, "shortId", "device attributes")
	if err != nil {
		return EnlistResult{}, err
	}
	attributes, err := buildAttributes(shortID)
	if err != nil {
		return EnlistResult{}, err
	}
	initialized, err := s.initializeDeviceShadows(ctx, thing.ThingName, record, townID, normalizedRigID)
	if err != nil {
		return EnlistResult{}, err
	}
	resources, err := s.ensureAuxiliaryResources(ctx, thing.ThingName, record)
	if err != nil {
		return EnlistResult{}, err
	}
	return thingResult(thing, created, attributes, initialized, resources), nil
}

func (s *Service) AssignDevice(ctx context.Context, deviceID, rigID string) (EnlistResult, error) {
	normalizedDeviceID, err := normalizeSlugText("device id", deviceID)
	if err != nil {
		return EnlistResult{}, err
	}
	normalizedRigID, err := normalizeSlugText("rig id", rigID)
	if err != nil {
		return EnlistResult{}, err
	}
	device, err := s.describeThing(ctx, normalizedDeviceID)
	if err != nil {
		return EnlistResult{}, err
	}
	rig, err := s.describeThing(ctx, normalizedRigID)
	if err != nil {
		return EnlistResult{}, err
	}
	if rig.Attributes["kind"] != kindRigType {
		return EnlistResult{}, enlistError("Thing %q is not a rig", normalizedRigID)
	}
	record, err := s.deviceRecordForRig(ctx, rig, device.ThingTypeName)
	if err != nil {
		return EnlistResult{}, err
	}
	townID, err := requireThingAttribute(rig.Attributes, townIDAttribute, "rig attributes")
	if err != nil {
		return EnlistResult{}, err
	}
	name, err := requireThingAttribute(device.Attributes, "name", "device attributes")
	if err != nil {
		return EnlistResult{}, err
	}
	shortID, err := requireThingAttribute(device.Attributes, "shortId", "device attributes")
	if err != nil {
		return EnlistResult{}, err
	}
	attributes, err := s.baseAttributes(record, name, shortID)
	if err != nil {
		return EnlistResult{}, err
	}
	attributes[townIDAttribute] = townID
	attributes[rigIDAttribute] = normalizedRigID
	attributes["rigType"] = rig.ThingTypeName
	attributes["deviceType"] = device.ThingTypeName
	if web, _ := record["web"].(map[string]any); web != nil {
		if adapter, ok := web["adapter"].(string); ok {
			attributes["webAdapter"] = adapter
		}
	}
	attributes, err = iotAttributes(attributes)
	if err != nil {
		return EnlistResult{}, err
	}
	if err := s.updateThingAttributes(ctx, device, attributes); err != nil {
		return EnlistResult{}, err
	}
	updated, err := s.describeThing(ctx, normalizedDeviceID)
	if err != nil {
		return EnlistResult{}, err
	}
	resources, err := s.ensureAuxiliaryResources(ctx, updated.ThingName, record)
	if err != nil {
		return EnlistResult{}, err
	}
	return thingResult(updated, false, attributes, []string{}, resources), nil
}

func (s *Service) detachThingPrincipals(ctx context.Context, thingName string) ([]string, error) {
	var detached []string
	var next *string
	for {
		page, err := s.aws.ListThingPrincipals(ctx, thingName, next)
		if err != nil {
			return nil, err
		}
		for _, principal := range page.Principals {
			if strings.TrimSpace(principal) == "" {
				continue
			}
			if err := s.aws.DetachThingPrincipal(ctx, thingName, principal); err != nil {
				return nil, err
			}
			detached = append(detached, principal)
		}
		next = page.NextToken
		if next == nil {
			return detached, nil
		}
	}
}

func (s *Service) DischargeThing(ctx context.Context, thingID string) (DischargeResult, error) {
	normalizedThingID, err := normalizeSlugText("thing id", thingID)
	if err != nil {
		return DischargeResult{}, err
	}
	thing, err := s.aws.DescribeThing(ctx, normalizedThingID)
	if err != nil {
		return DischargeResult{}, err
	}
	if thing == nil {
		return missingDischargeResult(normalizedThingID), nil
	}
	capAttribute, err := requireThingAttribute(thing.Attributes, "capabilities", fmt.Sprintf("thing %q attributes", thing.ThingName))
	if err != nil {
		return DischargeResult{}, err
	}
	caps, err := parseCapabilitiesSet(capAttribute, thing.ThingName)
	if err != nil {
		return DischargeResult{}, err
	}
	var deletedShadows []string
	for _, shadowName := range caps {
		deleted, err := s.aws.DeleteShadow(ctx, thing.ThingName, shadowName)
		if err != nil {
			return DischargeResult{}, err
		}
		if deleted {
			deletedShadows = append(deletedShadows, shadowName)
		}
	}
	detached, err := s.detachThingPrincipals(ctx, thing.ThingName)
	if err != nil {
		return DischargeResult{}, err
	}
	deleted, err := s.aws.DeleteThing(ctx, thing.ThingName)
	if err != nil {
		return DischargeResult{}, err
	}
	thingType := thing.ThingTypeName
	return DischargeResult{ThingName: thing.ThingName, ThingTypeName: &thingType, Deleted: deleted, Attributes: thing.Attributes, DeletedShadows: deletedShadows, DetachedPrincipals: detached, AuxiliaryResources: map[string]any{}}, nil
}

func (s *Service) DischargeAll(ctx context.Context) (map[string]any, error) {
	var results []DischargeResult
	for _, kind := range []string{kindDeviceType, kindRigType, kindTownType} {
		names, err := s.searchThingNames(ctx, "attributes.kind:"+kind)
		if err != nil {
			return nil, err
		}
		for _, name := range names {
			result, err := s.DischargeThing(ctx, name)
			if err != nil {
				return nil, err
			}
			results = append(results, result)
		}
	}
	deletedCount := 0
	payloads := make([]any, 0, len(results))
	for _, result := range results {
		if result.Deleted {
			deletedCount++
		}
		payloads = append(payloads, result.Payload())
	}
	return map[string]any{"deletedThings": payloads, "deletedThingCount": deletedCount}, nil
}

type CfnStatus string

const (
	CfnSuccess CfnStatus = "SUCCESS"
	CfnFailed  CfnStatus = "FAILED"
)

type CfnResponder interface {
	Send(ctx context.Context, event map[string]any, status CfnStatus, data map[string]any, reason *string, physicalResourceID string) error
}

type HTTPCfnResponder struct {
	Client *http.Client
}

func (r HTTPCfnResponder) Send(ctx context.Context, event map[string]any, status CfnStatus, data map[string]any, reason *string, physicalResourceID string) error {
	responseURL, err := requireTextFromValue(event, "ResponseURL", "CloudFormation event")
	if err != nil {
		return err
	}
	reasonText := "See CloudWatch log stream: txing-enlist-lambda"
	if reason != nil {
		reasonText = *reason
	}
	body := map[string]any{
		"Status":             string(status),
		"Reason":             reasonText,
		"PhysicalResourceId": physicalResourceID,
		"StackId":            mustText(event, "StackId"),
		"RequestId":          mustText(event, "RequestId"),
		"LogicalResourceId":  mustText(event, "LogicalResourceId"),
		"NoEcho":             false,
		"Data":               data,
	}
	encoded, err := json.Marshal(body)
	if err != nil {
		return err
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPut, responseURL, bytes.NewReader(encoded))
	if err != nil {
		return err
	}
	req.Header.Set("content-type", "")
	req.Header.Set("content-length", fmt.Sprint(len(encoded)))
	client := r.Client
	if client == nil {
		client = http.DefaultClient
	}
	resp, err := client.Do(req)
	if err != nil {
		return fmt.Errorf("send CloudFormation custom resource response: %w", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return fmt.Errorf("CloudFormation custom resource response failed: %s", resp.Status)
	}
	return nil
}

func mustText(event map[string]any, key string) string {
	value, _ := requireTextFromValue(event, key, "CloudFormation event")
	return value
}

func isCfnCustomResourceEvent(event map[string]any) bool {
	requestType, _ := event["RequestType"].(string)
	_, responseOK := event["ResponseURL"].(string)
	_, propertiesOK := event["ResourceProperties"].(map[string]any)
	return (requestType == "Create" || requestType == "Update" || requestType == "Delete") && responseOK && propertiesOK
}

func handleCfnCustomResource(ctx context.Context, event map[string]any, service *Service, responder CfnResponder) map[string]any {
	properties, _ := event["ResourceProperties"].(map[string]any)
	physicalResourceID, _ := event["PhysicalResourceId"].(string)
	if physicalResourceID == "" {
		physicalResourceID, _ = properties["PhysicalResourceId"].(string)
	}
	if physicalResourceID == "" {
		physicalResourceID = cfnDischargePhysicalID
	}
	data, err := handleCfnCustomResourceInner(ctx, event, service)
	if err == nil {
		if sendErr := responder.Send(ctx, event, CfnSuccess, data, nil, physicalResourceID); sendErr != nil {
			return map[string]any{"ok": false, "errorType": errorType(sendErr), "message": sendErr.Error()}
		}
		data["ok"] = true
		return data
	}
	reason := err.Error()
	_ = responder.Send(ctx, event, CfnFailed, map[string]any{}, &reason, physicalResourceID)
	return map[string]any{"ok": false, "errorType": errorType(err), "message": err.Error()}
}

func handleCfnCustomResourceInner(ctx context.Context, event map[string]any, service *Service) (map[string]any, error) {
	properties, ok := event["ResourceProperties"].(map[string]any)
	if !ok {
		return nil, enlistError("CloudFormation event is missing ResourceProperties")
	}
	if cleanupType, _ := properties["CleanupType"].(string); cleanupType != "TxingDischargeThings" {
		value, ok := properties["CleanupType"]
		return nil, enlistError("Unsupported CleanupType: %s", pyReprValue(value, ok))
	}
	if requestType, _ := event["RequestType"].(string); requestType == "Delete" {
		return service.DischargeAll(ctx)
	}
	return map[string]any{"skipped": true}, nil
}

func HandleLambdaEvent(ctx context.Context, event map[string]any, awsClient AWSClientAPI, responder CfnResponder) map[string]any {
	return HandleLambdaEventWithService(ctx, event, NewService(awsClient, RandomShortIDs{}), responder)
}

func HandleLambdaEventWithService(ctx context.Context, event map[string]any, service *Service, responder CfnResponder) map[string]any {
	if isCfnCustomResourceEvent(event) {
		return handleCfnCustomResource(ctx, event, service, responder)
	}
	result, err := service.Handle(ctx, event)
	if err != nil {
		return map[string]any{"ok": false, "errorType": errorType(err), "message": err.Error(), "processedAt": utcNowISO()}
	}
	result["ok"] = true
	result["processedAt"] = utcNowISO()
	return result
}

func blankPtrToNil(value *string) *string {
	if value == nil || strings.TrimSpace(*value) == "" {
		return nil
	}
	trimmed := strings.TrimSpace(*value)
	return &trimmed
}

func cloneStringMap(input map[string]string) map[string]string {
	out := make(map[string]string, len(input))
	for key, value := range input {
		out[key] = value
	}
	return out
}

func stringPtrValue(value *string) any {
	if value == nil {
		return nil
	}
	return *value
}
