package controller

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"strings"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/service/ec2"
	"github.com/aws/aws-sdk-go-v2/service/ecs"
	ecstypes "github.com/aws/aws-sdk-go-v2/service/ecs/types"
	"github.com/aws/aws-sdk-go-v2/service/iot"
	"github.com/aws/aws-sdk-go-v2/service/iotdataplane"
	iotdatatypes "github.com/aws/aws-sdk-go-v2/service/iotdataplane/types"
	"github.com/aws/smithy-go"
	"github.com/mparkachov/txing/devices/tbot/cloud/agentstatus"
)

const (
	ManagerTag  = "txing:managed-by"
	ThingTag    = "txing:thing"
	IdentityTag = "txing:agent-id"
	Manager     = "tbot-companion"
	maxPages    = 100
)

type Settings struct {
	Cluster, Definition, SecurityGroup, Function, Platform string
	Subnets                                                []string
}

func (s Settings) Validate() error {
	if s.Cluster == "" || s.Definition == "" || s.SecurityGroup == "" || s.Function == "" || len(s.Subnets) == 0 {
		return errors.New("cluster, pinned task definition, subnets, security group, and controller function are required")
	}
	for _, subnet := range s.Subnets {
		if subnet == "" {
			return errors.New("empty subnet ID")
		}
	}
	if s.Platform != "1.4.0" && s.Platform != "LATEST" {
		return errors.New("Fargate platform must be 1.4.0 or LATEST")
	}
	return nil
}

type AWSCloud struct {
	IoT      *iot.Client
	Data     *iotdataplane.Client
	ECS      *ecs.Client
	EC2      *ec2.Client
	Settings Settings
}

func NewAWS(ctx context.Context, settings Settings) (*AWSCloud, error) {
	if err := settings.Validate(); err != nil {
		return nil, err
	}
	cfg, err := config.LoadDefaultConfig(ctx, config.WithRetryMaxAttempts(3), config.WithHTTPClient(&http.Client{Timeout: 8 * time.Second}))
	if err != nil {
		return nil, err
	}
	control := iot.NewFromConfig(cfg)
	endpoint, err := control.DescribeEndpoint(ctx, &iot.DescribeEndpointInput{EndpointType: aws.String("iot:Data-ATS")})
	if err != nil {
		return nil, fmt.Errorf("discover IoT shadow endpoint: %w", err)
	}
	if aws.ToString(endpoint.EndpointAddress) == "" {
		return nil, errors.New("IoT returned an empty endpoint")
	}
	return &AWSCloud{IoT: control, Data: iotdataplane.NewFromConfig(cfg, func(o *iotdataplane.Options) { o.BaseEndpoint = aws.String("https://" + *endpoint.EndpointAddress) }),
		ECS: ecs.NewFromConfig(cfg), EC2: ec2.NewFromConfig(cfg), Settings: settings}, nil
}

func notFound(err error) bool {
	var api smithy.APIError
	return errors.As(err, &api) && api.ErrorCode() == "ResourceNotFoundException"
}

func (c *AWSCloud) ThingType(ctx context.Context, thing string) (string, error) {
	out, err := c.IoT.DescribeThing(ctx, &iot.DescribeThingInput{ThingName: aws.String(thing)})
	if notFound(err) {
		return "", ErrNotFound
	}
	if err != nil {
		return "", err
	}
	return aws.ToString(out.ThingTypeName), nil
}

func (c *AWSCloud) Things(ctx context.Context) ([]string, error) {
	var names []string
	var token *string
	for page := 0; page < maxPages; page++ {
		out, err := c.IoT.SearchIndex(ctx, &iot.SearchIndexInput{IndexName: aws.String("AWS_Things"), QueryString: aws.String("thingTypeName:tbot"), MaxResults: aws.Int32(100), NextToken: token})
		if err != nil {
			return nil, err
		}
		for _, thing := range out.Things {
			if name := aws.ToString(thing.ThingName); strings.HasPrefix(name, "tbot-") {
				names = append(names, name)
			}
		}
		if aws.ToString(out.NextToken) == "" {
			return names, nil
		}
		if token != nil && *token == *out.NextToken {
			return nil, errors.New("IoT index repeated its pagination token")
		}
		token = out.NextToken
	}
	return nil, errors.New("TBot enumeration exceeded 100 pages; split the controller deployment before increasing fleet size")
}

func (c *AWSCloud) Lifecycle(ctx context.Context, thing string) (Lifecycle, error) {
	out, err := c.Data.GetThingShadow(ctx, &iotdataplane.GetThingShadowInput{ThingName: aws.String(thing), ShadowName: aws.String("sparkplug")})
	if notFound(err) {
		return Lifecycle{}, ErrNotFound
	}
	if err != nil {
		return Lifecycle{}, err
	}
	var document struct {
		State struct {
			Reported Lifecycle `json:"reported"`
		} `json:"state"`
	}
	err = json.Unmarshal(out.Payload, &document)
	return document.State.Reported, err
}

type shadowStore struct {
	data  *iotdataplane.Client
	thing string
}

func (c *AWSCloud) Store(thing string) agentstatus.Store { return &shadowStore{c.Data, thing} }

func (s *shadowStore) Read(ctx context.Context) (agentstatus.Reported, int64, error) {
	out, err := s.data.GetThingShadow(ctx, &iotdataplane.GetThingShadowInput{ThingName: aws.String(s.thing), ShadowName: aws.String("agent")})
	if notFound(err) {
		return agentstatus.Reported{}, 0, fmt.Errorf("provision the agent shadow by re-enlisting %s: %w", s.thing, ErrNotFound)
	}
	if err != nil {
		return agentstatus.Reported{}, 0, err
	}
	var document struct {
		State struct {
			Reported agentstatus.Reported `json:"reported"`
		} `json:"state"`
		Version int64 `json:"version"`
	}
	if err := json.Unmarshal(out.Payload, &document); err != nil {
		return agentstatus.Reported{}, 0, err
	}
	if document.Version < 1 {
		return agentstatus.Reported{}, 0, errors.New("agent shadow is missing its version")
	}
	return document.State.Reported, document.Version, nil
}

func (s *shadowStore) Write(ctx context.Context, state agentstatus.Reported, version int64) error {
	payload, err := json.Marshal(struct {
		State struct {
			Reported agentstatus.Reported `json:"reported"`
		} `json:"state"`
		Version int64 `json:"version"`
	}{State: struct {
		Reported agentstatus.Reported `json:"reported"`
	}{state}, Version: version})
	if err != nil {
		return err
	}
	_, err = s.data.UpdateThingShadow(ctx, &iotdataplane.UpdateThingShadowInput{ThingName: aws.String(s.thing), ShadowName: aws.String("agent"), Payload: payload})
	var conflict *iotdatatypes.ConflictException
	if errors.As(err, &conflict) {
		return agentstatus.ErrVersionConflict
	}
	return err
}

func taskModel(t ecstypes.Task) (Task, bool) {
	tags := make(map[string]string)
	for _, tag := range t.Tags {
		tags[aws.ToString(tag.Key)] = aws.ToString(tag.Value)
	}
	if tags[ManagerTag] != Manager {
		return Task{}, false
	}
	result := Task{ARN: aws.ToString(t.TaskArn), Thing: tags[ThingTag], ID: tags[IdentityTag], Status: aws.ToString(t.LastStatus), DesiredStatus: aws.ToString(t.DesiredStatus), Reason: aws.ToString(t.StoppedReason)}
	for _, attachment := range t.Attachments {
		if aws.ToString(attachment.Type) == "ElasticNetworkInterface" {
			for _, detail := range attachment.Details {
				if aws.ToString(detail.Name) == "networkInterfaceId" {
					result.ENI = aws.ToString(detail.Value)
				}
			}
		}
	}
	return result, true
}

func (c *AWSCloud) describe(ctx context.Context, arns []string) ([]Task, error) {
	var result []Task
	for len(arns) > 0 {
		count := min(100, len(arns))
		out, err := c.ECS.DescribeTasks(ctx, &ecs.DescribeTasksInput{Cluster: aws.String(c.Settings.Cluster), Tasks: arns[:count], Include: []ecstypes.TaskField{ecstypes.TaskFieldTags}})
		if err != nil {
			return nil, err
		}
		for _, failure := range out.Failures {
			if aws.ToString(failure.Reason) != "MISSING" {
				return nil, fmt.Errorf("DescribeTasks %s: %s", aws.ToString(failure.Arn), aws.ToString(failure.Reason))
			}
		}
		for _, task := range out.Tasks {
			if t, managed := taskModel(task); managed {
				result = append(result, t)
			}
		}
		arns = arns[count:]
	}
	return result, nil
}

func (c *AWSCloud) Tasks(ctx context.Context) ([]Task, error) {
	var arns []string
	// RUNNING is desired status, so this includes pending/provisioning tasks.
	// Recent STOPPED tasks resolve a lost RunTask response without reusing its
	// idempotency token forever after the task exited.
	for _, status := range []ecstypes.DesiredStatus{ecstypes.DesiredStatusRunning, ecstypes.DesiredStatusStopped} {
		var token *string
		for page := 0; page < maxPages; page++ {
			out, err := c.ECS.ListTasks(ctx, &ecs.ListTasksInput{Cluster: aws.String(c.Settings.Cluster), DesiredStatus: status, MaxResults: aws.Int32(100), NextToken: token})
			if err != nil {
				return nil, err
			}
			arns = append(arns, out.TaskArns...)
			if aws.ToString(out.NextToken) == "" {
				break
			}
			if (token != nil && *token == *out.NextToken) || page == maxPages-1 {
				return nil, errors.New("ECS pagination did not complete within its bound")
			}
			token = out.NextToken
		}
	}
	// A task can change desired status between the two list calls; describe it
	// once so one ARN cannot be mistaken for two different companion tasks.
	seen := make(map[string]bool)
	unique := arns[:0]
	for _, arn := range arns {
		if !seen[arn] {
			seen[arn] = true
			unique = append(unique, arn)
		}
	}
	return c.describe(ctx, unique)
}

func (c *AWSCloud) Run(ctx context.Context, thing, id string) (Task, error) {
	out, err := c.ECS.RunTask(ctx, &ecs.RunTaskInput{Cluster: aws.String(c.Settings.Cluster), TaskDefinition: aws.String(c.Settings.Definition), Count: aws.Int32(1), ClientToken: aws.String(id), StartedBy: aws.String(id), Group: aws.String("tbot:" + thing), LaunchType: ecstypes.LaunchTypeFargate, PlatformVersion: aws.String(c.Settings.Platform),
		NetworkConfiguration: &ecstypes.NetworkConfiguration{AwsvpcConfiguration: &ecstypes.AwsVpcConfiguration{Subnets: c.Settings.Subnets, SecurityGroups: []string{c.Settings.SecurityGroup}, AssignPublicIp: ecstypes.AssignPublicIpEnabled}},
		Tags:                 []ecstypes.Tag{{Key: aws.String(ManagerTag), Value: aws.String(Manager)}, {Key: aws.String(ThingTag), Value: aws.String(thing)}, {Key: aws.String(IdentityTag), Value: aws.String(id)}},
		Overrides: &ecstypes.TaskOverride{ContainerOverrides: []ecstypes.ContainerOverride{{Name: aws.String("tbot-companion"), Environment: []ecstypes.KeyValuePair{
			{Name: aws.String("TXING_THING_ID"), Value: aws.String(thing)}, {Name: aws.String("TXING_AGENT_TASK_ID"), Value: aws.String(id)}, {Name: aws.String("TXING_AGENT_CONTROLLER_FUNCTION"), Value: aws.String(c.Settings.Function)},
		}}}},
	})
	if err != nil {
		// A deployment may change the pinned task definition between ambiguous
		// attempts. Resolve ECS's original task instead of inventing a new token.
		var conflict *ecstypes.ConflictException
		if errors.As(err, &conflict) && len(conflict.ResourceIds) > 0 {
			tasks, e := c.describe(ctx, conflict.ResourceIds)
			if e != nil {
				return Task{}, e
			}
			for _, task := range tasks {
				if task.ID == id && task.Thing == thing {
					return task, nil
				}
			}
		}
		var api smithy.APIError
		if errors.As(err, &api) && api.ErrorFault() == smithy.FaultClient && api.ErrorCode() != "ThrottlingException" && api.ErrorCode() != "ConflictException" {
			return Task{}, fmt.Errorf("%w: %v", ErrStartRejected, err)
		}
		return Task{}, err
	}
	if len(out.Failures) > 0 {
		return Task{}, fmt.Errorf("%w: %s: %s", ErrStartRejected, aws.ToString(out.Failures[0].Reason), aws.ToString(out.Failures[0].Detail))
	}
	if len(out.Tasks) != 1 {
		return Task{}, errors.New("RunTask did not return exactly one task")
	}
	task, managed := taskModel(out.Tasks[0])
	if !managed || task.ID != id || task.Thing != thing {
		return Task{}, errors.New("RunTask returned a task without the expected identity tags")
	}
	return task, nil
}

func (c *AWSCloud) Stop(ctx context.Context, task Task, reason string) error {
	_, err := c.ECS.StopTask(ctx, &ecs.StopTaskInput{Cluster: aws.String(c.Settings.Cluster), Task: aws.String(task.ARN), Reason: aws.String(reason)})
	return err
}

func (c *AWSCloud) Addresses(ctx context.Context, task Task) (string, string, error) {
	if task.ENI == "" {
		return "", "", errors.New("running task has no ENI attachment yet")
	}
	out, err := c.EC2.DescribeNetworkInterfaces(ctx, &ec2.DescribeNetworkInterfacesInput{NetworkInterfaceIds: []string{task.ENI}})
	if err != nil {
		return "", "", err
	}
	if len(out.NetworkInterfaces) != 1 {
		return "", "", errors.New("task ENI not found")
	}
	eni := out.NetworkInterfaces[0]
	ipv4, ipv6 := "", ""
	if eni.Association != nil {
		ipv4 = aws.ToString(eni.Association.PublicIp)
	}
	if len(eni.Ipv6Addresses) > 0 {
		ipv6 = aws.ToString(eni.Ipv6Addresses[0].Ipv6Address)
	}
	if ipv4 == "" || ipv6 == "" {
		return "", "", errors.New("task ENI lacks public IPv4 or IPv6; check dualStackIPv6 and AssignPublicIp")
	}
	return ipv4, ipv6, nil
}
