package companion

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/url"
	"regexp"
	"strings"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/service/iot"
	"github.com/aws/aws-sdk-go-v2/service/iotdataplane"
	"github.com/aws/aws-sdk-go-v2/service/lambda"
	lambdatypes "github.com/aws/aws-sdk-go-v2/service/lambda/types"
	"github.com/mparkachov/txing/devices/tbot/cloud/agentstatus"
	"github.com/mparkachov/txing/devices/tbot/cloud/controller"
)

type AWSCloud struct {
	thing, function string
	shadow          *controller.AWSCloud
	invoke          *lambda.Client
}

func NewCloud(ctx context.Context, cfg aws.Config, thing, function string) (*AWSCloud, error) {
	if err := ValidateIdentity(thing, "00000000000000000000000000000000"); err != nil {
		return nil, err
	}
	endpoint, err := iot.NewFromConfig(cfg).DescribeEndpoint(ctx, &iot.DescribeEndpointInput{EndpointType: aws.String("iot:Data-ATS")})
	if err != nil {
		return nil, errors.New("IoT endpoint discovery failed")
	}
	if aws.ToString(endpoint.EndpointAddress) == "" {
		return nil, errors.New("empty IoT endpoint")
	}
	return &AWSCloud{thing, function, &controller.AWSCloud{Data: iotdataplane.NewFromConfig(cfg, func(o *iotdataplane.Options) { o.BaseEndpoint = aws.String("https://" + *endpoint.EndpointAddress) })}, lambda.NewFromConfig(cfg)}, nil
}
func (c *AWSCloud) Lifecycle(ctx context.Context) (controller.Lifecycle, error) {
	return c.shadow.Lifecycle(ctx, c.thing)
}
func (c *AWSCloud) Store() agentstatus.Store { return c.shadow.Store(c.thing) }
func (c *AWSCloud) Readiness(ctx context.Context, r controller.Readiness) error {
	payload, err := json.Marshal(controller.Event{Kind: "readiness", Thing: c.thing, Readiness: &r})
	if err != nil {
		return err
	}
	result, err := c.invoke.Invoke(ctx, &lambda.InvokeInput{FunctionName: aws.String(c.function), InvocationType: lambdatypes.InvocationTypeRequestResponse, Payload: payload})
	if err != nil {
		return errors.New("controller invocation transport failed")
	}
	if result.FunctionError != nil {
		var fault struct {
			ErrorMessage string `json:"errorMessage"`
		}
		_ = json.Unmarshal(result.Payload, &fault)
		if fault.ErrorMessage == agentstatus.ErrStaleTask.Error() {
			return agentstatus.ErrStaleTask
		}
		if fault.ErrorMessage == agentstatus.ErrVersionConflict.Error() {
			return agentstatus.ErrVersionConflict
		}
		return errors.New("controller rejected readiness; refresh authoritative state")
	}
	return nil
}

var thingPattern = regexp.MustCompile(`^tbot-[A-Za-z0-9_-]+$`)
var idPattern = regexp.MustCompile(`^[a-f0-9]{32}$`)

func ValidateIdentity(thing, id string) error {
	if !thingPattern.MatchString(thing) || len(thing) > 100 || !idPattern.MatchString(id) {
		return errors.New("assigned TBot Thing and 32-hex launch identity are required")
	}
	return nil
}

// TaskARN uses the Fargate-injected endpoint only; credentials never come from it.
func TaskARN(ctx context.Context, metadata string, client *http.Client) (string, error) {
	u, err := url.Parse(metadata)
	if err != nil || u.Scheme != "http" || u.Host != "169.254.170.2" || u.RawQuery != "" || u.User != nil {
		return "", errors.New("Fargate task metadata v4 endpoint is required")
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, strings.TrimSuffix(metadata, "/")+"/task", nil)
	if err != nil {
		return "", err
	}
	response, err := client.Do(req)
	if err != nil {
		return "", errors.New("task metadata request failed")
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		return "", errors.New("task metadata unavailable")
	}
	var task struct {
		ARN string `json:"TaskARN"`
	}
	if err = json.NewDecoder(io.LimitReader(response.Body, 1<<20)).Decode(&task); err != nil {
		return "", errors.New("invalid task metadata")
	}
	if !strings.HasPrefix(task.ARN, "arn:") || !strings.Contains(task.ARN, ":ecs:") || !strings.Contains(task.ARN, ":task/") {
		return "", errors.New("task metadata missing ECS task ARN")
	}
	return task.ARN, nil
}
func MetadataHTTPClient() *http.Client {
	return &http.Client{Timeout: 4 * time.Second, CheckRedirect: func(*http.Request, []*http.Request) error { return errors.New("metadata redirects forbidden") }}
}
