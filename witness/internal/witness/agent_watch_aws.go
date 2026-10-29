package witness

import (
	"context"
	"fmt"
	"net/http"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/service/iot"
	"github.com/aws/aws-sdk-go-v2/service/iotdataplane"
	"github.com/aws/aws-sdk-go-v2/service/lambdamicrovms"
)

func (c *AWSClient) AgentThings(ctx context.Context) ([]string, error) {
	var things []string
	var token *string
	seen := map[string]bool{}
	for page := 0; page < 1000; page++ {
		// Read assignments across the registry, including devices whose agent
		// capability was removed. Filtering by current type/capability would
		// hide those assignments and could misclassify their VMs as orphans.
		out, err := c.iot.ListThings(ctx, &iot.ListThingsInput{NextToken: token})
		if err != nil {
			return nil, fmt.Errorf("list watch things: %w", err)
		}
		for _, thing := range out.Things {
			if thing.ThingName == nil || *thing.ThingName == "" {
				return nil, fmt.Errorf("watch thing has no identity")
			}
			things = append(things, *thing.ThingName)
		}
		if out.NextToken == nil || *out.NextToken == "" {
			return things, nil
		}
		if seen[*out.NextToken] {
			return nil, fmt.Errorf("watch thing pagination repeated a token")
		}
		seen[*out.NextToken] = true
		token = out.NextToken
	}
	return nil, fmt.Errorf("watch thing pagination exceeded its limit")
}

func (c *AWSClient) AgentShadow(ctx context.Context, thing string) ([]byte, bool, error) {
	out, err := c.iotData.GetThingShadow(ctx, &iotdataplane.GetThingShadowInput{
		ThingName: aws.String(thing), ShadowName: aws.String("agent"),
	})
	if err != nil {
		if errorIsNotFound(err) {
			return nil, false, nil
		}
		return nil, false, fmt.Errorf("read agent watch shadow: %w", err)
	}
	return out.Payload, true, nil
}

func (c *AWSClient) MicrovmPage(ctx context.Context, image, token string) ([]WatchMicrovm, string, error) {
	request := &lambdamicrovms.ListMicrovmsInput{ImageIdentifier: aws.String(image), MaxResults: aws.Int32(50)}
	if token != "" {
		request.NextToken = aws.String(token)
	}
	out, err := c.microvms.ListMicrovms(ctx, request)
	if err != nil {
		return nil, "", err
	}
	items := make([]WatchMicrovm, 0, len(out.Items))
	for _, item := range out.Items {
		items = append(items, WatchMicrovm{ID: aws.ToString(item.MicrovmId), Image: aws.ToString(item.ImageArn),
			State: string(item.State), StartedAt: aws.ToTime(item.StartedAt)})
	}
	return items, aws.ToString(out.NextToken), nil
}

func (c *AWSClient) Microvm(ctx context.Context, id string) (WatchMicrovm, error) {
	out, err := c.microvms.GetMicrovm(ctx, &lambdamicrovms.GetMicrovmInput{MicrovmIdentifier: aws.String(id)})
	if err != nil {
		return WatchMicrovm{}, err
	}
	return WatchMicrovm{ID: aws.ToString(out.MicrovmId), Image: aws.ToString(out.ImageArn),
		State: string(out.State), StartedAt: aws.ToTime(out.StartedAt)}, nil
}

func (c *AWSClient) TerminateMicrovm(ctx context.Context, id string) error {
	_, err := c.microvms.TerminateMicrovm(ctx, &lambdamicrovms.TerminateMicrovmInput{MicrovmIdentifier: aws.String(id)})
	return err
}

// Construct the watch client without contacting its service: Sparkplug keeps
// its current AWS configuration and does not depend on a MicroVM API request.
func (c *AWSClient) ConfigureAgentWatch(cfg aws.Config) {
	c.microvms = lambdamicrovms.NewFromConfig(cfg, func(o *lambdamicrovms.Options) {
		o.RetryMaxAttempts = 2
		o.HTTPClient = &watchHTTPClient
	})
}

var watchHTTPClient = http.Client{Timeout: 2 * time.Second}
