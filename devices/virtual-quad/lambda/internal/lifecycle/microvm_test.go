package lifecycle

import (
	"context"
	"errors"
	"reflect"
	"strings"
	"testing"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/service/lambdamicrovms"
	"github.com/aws/aws-sdk-go-v2/service/lambdamicrovms/types"
)

type fakeMicroVMClient struct {
	MicroVMClient
	run     *lambdamicrovms.RunMicrovmInput
	retryer aws.Retryer
	runErr  error
	list    func(*lambdamicrovms.ListMicrovmsInput) (*lambdamicrovms.ListMicrovmsOutput, error)
}

func (f *fakeMicroVMClient) RunMicrovm(_ context.Context, input *lambdamicrovms.RunMicrovmInput, options ...func(*lambdamicrovms.Options)) (*lambdamicrovms.RunMicrovmOutput, error) {
	f.run = input
	var configured lambdamicrovms.Options
	for _, apply := range options {
		apply(&configured)
	}
	f.retryer = configured.Retryer
	if f.runErr != nil {
		return nil, f.runErr
	}
	return &lambdamicrovms.RunMicrovmOutput{MicrovmId: aws.String("microvm-test")}, nil
}

func (f *fakeMicroVMClient) ListMicrovms(_ context.Context, input *lambdamicrovms.ListMicrovmsInput, _ ...func(*lambdamicrovms.Options)) (*lambdamicrovms.ListMicrovmsOutput, error) {
	return f.list(input)
}

func TestAWSMicroVMRunUsesExactStoredInputs(t *testing.T) {
	client := &fakeMicroVMClient{}
	platform := NewAWSMicroVMs(client)
	config := testConfig()
	launch := Launch{LaunchConfig: config, ClientToken: "session-id", MaximumDurationInSeconds: 810, RunHookPayload: `{"sessionId":"session-id"}`}
	id, err := platform.Run(t.Context(), launch)
	if err != nil || id != "microvm-test" {
		t.Fatalf("Run failed: %v", err)
	}
	logging := client.run.Logging.(*types.LoggingMemberCloudWatch).Value
	if aws.ToString(client.run.ImageIdentifier) != config.ImageARN || aws.ToString(client.run.ImageVersion) != config.ImageVersion ||
		aws.ToString(client.run.ExecutionRoleArn) != config.ExecutionRoleARN || aws.ToString(logging.LogGroup) != config.LogGroup ||
		aws.ToString(client.run.ClientToken) != launch.ClientToken || aws.ToInt32(client.run.MaximumDurationInSeconds) != launch.MaximumDurationInSeconds ||
		aws.ToString(client.run.RunHookPayload) != launch.RunHookPayload || client.run.IdlePolicy != nil ||
		!reflect.DeepEqual(client.run.IngressNetworkConnectors, []string{config.IngressConnector}) ||
		!reflect.DeepEqual(client.run.EgressNetworkConnectors, []string{config.EgressConnector}) {
		t.Fatal("AWS Run request differed from the persisted launch")
	}
	if _, ok := client.retryer.(aws.NopRetryer); !ok {
		t.Fatal("AWS SDK could retry independently of the ledger")
	}
	client.runErr = &types.ValidationException{Message: aws.String("echoed private launch data")}
	if _, err := platform.Run(t.Context(), launch); !errors.Is(err, ErrLaunchRejected) || strings.Contains(err.Error(), "private") {
		t.Fatalf("definitive launch error classification or redaction failed: %v", err)
	}
	client.runErr = &types.ConflictException{}
	if _, err := platform.Run(t.Context(), launch); err == nil || errors.Is(err, ErrLaunchRejected) {
		t.Fatalf("conflict was not treated as an ambiguous dispatch: %v", err)
	}
}

func TestAWSMicroVMInventoryRejectsUnscopedAndIncompletePages(t *testing.T) {
	client := &fakeMicroVMClient{}
	platform := NewAWSMicroVMs(client)
	var tokens []string
	client.list = func(input *lambdamicrovms.ListMicrovmsInput) (*lambdamicrovms.ListMicrovmsOutput, error) {
		if aws.ToString(input.ImageIdentifier) != "image" {
			t.Fatal("inventory request was not scoped to its image")
		}
		token := aws.ToString(input.NextToken)
		tokens = append(tokens, token)
		output := &lambdamicrovms.ListMicrovmsOutput{}
		if token == "" {
			output.NextToken = aws.String("page-two")
		} else {
			output.Items = []types.MicrovmItem{{ImageArn: aws.String("image"), MicrovmId: aws.String("microvm-two")}}
		}
		return output, nil
	}
	if got, err := platform.Inventory(t.Context(), "image"); err != nil || len(got) != 1 || got[0].ID != "microvm-two" ||
		!reflect.DeepEqual(tokens, []string{"", "page-two"}) {
		t.Fatalf("failed to complete paginated inventory: %v", err)
	}
	client.list = func(*lambdamicrovms.ListMicrovmsInput) (*lambdamicrovms.ListMicrovmsOutput, error) {
		return &lambdamicrovms.ListMicrovmsOutput{NextToken: aws.String("page-loop")}, nil
	}
	if _, err := platform.Inventory(t.Context(), "image"); err == nil {
		t.Fatal("incomplete inventory returned success")
	}
	client.list = func(*lambdamicrovms.ListMicrovmsInput) (*lambdamicrovms.ListMicrovmsOutput, error) {
		return &lambdamicrovms.ListMicrovmsOutput{Items: []types.MicrovmItem{{ImageArn: aws.String("unrelated"), MicrovmId: aws.String("other")}}}, nil
	}
	if _, err := platform.Inventory(t.Context(), "image"); err == nil {
		t.Fatal("inventory accepted a VM from another image")
	}
}

func TestMicroVMStateErrorsAllowBoundedStopRetry(t *testing.T) {
	for _, serviceErr := range []error{
		&types.ConflictException{},
		&types.ResourceNotFoundException{},
		&types.InternalServerException{},
		&types.ThrottlingException{},
	} {
		if err := stateError("TerminateMicrovm", serviceErr); !errors.Is(err, errRetryVMState) {
			t.Errorf("state error %T did not allow retry: %v", serviceErr, err)
		}
	}
	if err := stateError("TerminateMicrovm", &types.AccessDeniedException{}); errors.Is(err, errRetryVMState) {
		t.Fatalf("permission error allowed retry: %v", err)
	}
}
