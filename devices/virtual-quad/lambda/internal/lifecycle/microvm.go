package lifecycle

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/service/lambdamicrovms"
	"github.com/aws/aws-sdk-go-v2/service/lambdamicrovms/types"
	"github.com/aws/smithy-go"
)

var ErrLaunchRejected = errors.New("MicroVM launch was rejected")
var errRetryVMState = errors.New("MicroVM state is temporarily unavailable")

type MicroVM struct {
	ID, ImageARN, ImageVersion string
	State                      types.MicrovmState
	StartedAt                  time.Time
}

type MicroVMs interface {
	Run(context.Context, Launch) (string, error)
	Get(context.Context, string) (MicroVM, error)
	Terminate(context.Context, string) error
	Inventory(context.Context, string) ([]MicroVM, error)
}

type MicroVMClient interface {
	RunMicrovm(context.Context, *lambdamicrovms.RunMicrovmInput, ...func(*lambdamicrovms.Options)) (*lambdamicrovms.RunMicrovmOutput, error)
	GetMicrovm(context.Context, *lambdamicrovms.GetMicrovmInput, ...func(*lambdamicrovms.Options)) (*lambdamicrovms.GetMicrovmOutput, error)
	TerminateMicrovm(context.Context, *lambdamicrovms.TerminateMicrovmInput, ...func(*lambdamicrovms.Options)) (*lambdamicrovms.TerminateMicrovmOutput, error)
	ListMicrovms(context.Context, *lambdamicrovms.ListMicrovmsInput, ...func(*lambdamicrovms.Options)) (*lambdamicrovms.ListMicrovmsOutput, error)
}

type AWSMicroVMs struct{ client MicroVMClient }

func NewAWSMicroVMs(client MicroVMClient) AWSMicroVMs { return AWSMicroVMs{client: client} }

func (p AWSMicroVMs) Run(ctx context.Context, launch Launch) (string, error) {
	input := &lambdamicrovms.RunMicrovmInput{
		ImageIdentifier: aws.String(launch.ImageARN),
		ClientToken:     aws.String(launch.ClientToken), ExecutionRoleArn: aws.String(launch.ExecutionRoleARN),
		IngressNetworkConnectors: []string{launch.IngressConnector}, EgressNetworkConnectors: []string{launch.EgressConnector},
		MaximumDurationInSeconds: aws.Int32(launch.MaximumDurationInSeconds), RunHookPayload: aws.String(launch.RunHookPayload),
		Logging: &types.LoggingMemberCloudWatch{Value: types.CloudWatchLogging{LogGroup: aws.String(launch.LogGroup)}},
	}
	if launch.ImageVersion != "" {
		input.ImageVersion = aws.String(launch.ImageVersion)
	}
	result, err := p.client.RunMicrovm(ctx, input, func(options *lambdamicrovms.Options) {
		// The ledger owns retries and can distinguish the first service
		// rejection from one received after an ambiguous attempt.
		options.Retryer = aws.NopRetryer{}
	})
	if err != nil {
		var apiError smithy.APIError
		if errors.As(err, &apiError) {
			switch apiError.ErrorCode() {
			case "AccessDeniedException", "ResourceNotFoundException", "ServiceQuotaExceededException", "ValidationException":
				return "", fmt.Errorf("%w: %s", ErrLaunchRejected, apiError.ErrorCode())
			}
		}
		return "", platformError("RunMicrovm", err)
	}
	id := aws.ToString(result.MicrovmId)
	if id == "" {
		return "", errors.New("RunMicrovm did not return an identity")
	}
	return id, nil
}

func (p AWSMicroVMs) Get(ctx context.Context, id string) (MicroVM, error) {
	result, err := p.client.GetMicrovm(ctx, &lambdamicrovms.GetMicrovmInput{MicrovmIdentifier: aws.String(id)})
	if err != nil {
		return MicroVM{}, stateError("GetMicrovm", err)
	}
	return MicroVM{
		ID: aws.ToString(result.MicrovmId), ImageARN: aws.ToString(result.ImageArn),
		ImageVersion: aws.ToString(result.ImageVersion), State: result.State, StartedAt: aws.ToTime(result.StartedAt),
	}, nil
}

func (p AWSMicroVMs) Terminate(ctx context.Context, id string) error {
	_, err := p.client.TerminateMicrovm(ctx, &lambdamicrovms.TerminateMicrovmInput{MicrovmIdentifier: aws.String(id)})
	return stateError("TerminateMicrovm", err)
}

func stateError(operation string, err error) error {
	var apiError smithy.APIError
	if errors.As(err, &apiError) {
		switch apiError.ErrorCode() {
		case "ConflictException", "ResourceNotFoundException", "InternalServerException", "ThrottlingException":
			return fmt.Errorf("%w: %s: %s", errRetryVMState, operation, apiError.ErrorCode())
		}
	}
	return platformError(operation, err)
}

func (p AWSMicroVMs) Inventory(ctx context.Context, image string) ([]MicroVM, error) {
	if image == "" {
		return nil, ErrInvalidRequest
	}
	var inventory []MicroVM
	request := &lambdamicrovms.ListMicrovmsInput{ImageIdentifier: aws.String(image), MaxResults: aws.Int32(50)}
	tokens := map[string]bool{}
	for {
		result, err := p.client.ListMicrovms(ctx, request)
		if err != nil {
			return nil, platformError("ListMicrovms", err)
		}
		for _, item := range result.Items {
			if aws.ToString(item.ImageArn) != image || aws.ToString(item.MicrovmId) == "" {
				return nil, errors.New("ListMicrovms returned an item outside the requested image or without an identity")
			}
			inventory = append(inventory, MicroVM{
				ID: aws.ToString(item.MicrovmId), ImageARN: image,
				ImageVersion: aws.ToString(item.ImageVersion), State: item.State, StartedAt: aws.ToTime(item.StartedAt),
			})
		}
		next := aws.ToString(result.NextToken)
		if next == "" {
			return inventory, nil
		}
		if tokens[next] || len(tokens) >= 999 {
			return nil, errors.New("ListMicrovms pagination did not finish")
		}
		tokens[next] = true
		request.NextToken = result.NextToken
	}
}

func platformError(operation string, err error) error {
	if err == nil {
		return nil
	}
	var apiError smithy.APIError
	if errors.As(err, &apiError) {
		// Service error messages can echo input parameters from a request.
		return fmt.Errorf("%s: %s", operation, apiError.ErrorCode())
	}
	return fmt.Errorf("%s: %w", operation, err)
}
