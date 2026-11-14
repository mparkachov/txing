package main

import (
	"context"
	"errors"
	"fmt"
	"log"
	"net/url"
	"os"
	"strings"
	"time"

	"github.com/aws/aws-lambda-go/lambda"
	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/aws/arn"
	"github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/service/dynamodb"
	"github.com/aws/aws-sdk-go-v2/service/iot"
	"github.com/aws/aws-sdk-go-v2/service/iotdataplane"
	lambdaservice "github.com/aws/aws-sdk-go-v2/service/lambda"
	"github.com/aws/aws-sdk-go-v2/service/lambdamicrovms"
	"txing.dev/virtual-quad-lambda/internal/controller"
	"txing.dev/virtual-quad-lambda/internal/lifecycle"
	"txing.dev/virtual-quad-lambda/internal/version"
)

func main() {
	log.Printf("service=txing-virtual-quad-lambda version=%s cold_start=true", version.Version)
	ctx, cancel := context.WithTimeout(context.Background(), 8*time.Second)
	handler, err := initialize(ctx)
	cancel()
	if err != nil {
		log.Fatalf("initialize virtual quad controller: %v", err)
	}
	lambda.Start(handler.Handle)
}

func initialize(ctx context.Context) (controller.Handler, error) {
	var empty controller.Handler
	cfg, err := config.LoadDefaultConfig(ctx, config.WithRetryMaxAttempts(2))
	if err != nil {
		return empty, err
	}
	table := os.Getenv("VIRTUAL_QUAD_SESSION_TABLE")
	function := os.Getenv("AWS_LAMBDA_FUNCTION_NAME")
	launch := lifecycle.LaunchConfig{
		ImageARN:         os.Getenv("VIRTUAL_QUAD_IMAGE_ARN"),
		ExecutionRoleARN: os.Getenv("VIRTUAL_QUAD_WORKER_ROLE_ARN"), LogGroup: os.Getenv("VIRTUAL_QUAD_WORKER_LOG_GROUP"),
	}
	image, err := arn.Parse(launch.ImageARN)
	if err != nil || image.Service != "lambda" || image.Region != cfg.Region || cfg.Region != "eu-central-1" ||
		!strings.HasPrefix(image.Resource, "microvm-image:") ||
		launch.ExecutionRoleARN == "" || launch.LogGroup == "" || function == "" || table == "" {
		return empty, errors.New("missing or invalid virtual quad controller configuration")
	}
	connector := fmt.Sprintf("arn:%s:lambda:%s:aws:network-connector:aws-network-connector:", image.Partition, cfg.Region)
	launch.IngressConnector, launch.EgressConnector = connector+"NO_INGRESS", connector+"INTERNET_EGRESS"
	launch.ControllerURL, err = loadWorkerURL(ctx, lambdaservice.NewFromConfig(cfg), function, cfg.Region)
	if err != nil {
		return empty, err
	}
	things := iot.NewFromConfig(cfg)
	endpoint, err := things.DescribeEndpoint(ctx, &iot.DescribeEndpointInput{EndpointType: aws.String("iot:Data-ATS")})
	if err != nil {
		return empty, fmt.Errorf("resolve IoT data endpoint: %w", err)
	}
	if aws.ToString(endpoint.EndpointAddress) == "" {
		return empty, errors.New("IoT data endpoint is empty")
	}
	shadows := iotdataplane.NewFromConfig(cfg, func(options *iotdataplane.Options) {
		options.BaseEndpoint = aws.String("https://" + aws.ToString(endpoint.EndpointAddress))
	})
	store := lifecycle.NewDynamoStore(dynamodb.NewFromConfig(cfg), table)
	ledger := lifecycle.NewLedger(store)
	reconciler := lifecycle.NewReconciler(ledger, lifecycle.NewAWSMicroVMs(lambdamicrovms.NewFromConfig(cfg)), launch)
	return controller.NewHandler(ledger, reconciler, controller.NewAWSRegistry(things, shadows), store,
		controller.NewAWSReporter(ledger, shadows), launch.ExecutionRoleARN)
}

func loadWorkerURL(ctx context.Context, client *lambdaservice.Client, function, region string) (string, error) {
	result, err := client.GetFunctionUrlConfig(ctx, &lambdaservice.GetFunctionUrlConfigInput{FunctionName: aws.String(function)})
	if err != nil {
		return "", fmt.Errorf("load virtual quad worker URL: %w", err)
	}
	endpoint, err := url.Parse(aws.ToString(result.FunctionUrl))
	if err != nil || string(result.AuthType) != "AWS_IAM" || endpoint.Scheme != "https" ||
		!strings.HasSuffix(endpoint.Host, ".lambda-url."+region+".on.aws") ||
		(endpoint.Path != "" && endpoint.Path != "/") || endpoint.User != nil || endpoint.RawQuery != "" || endpoint.Fragment != "" {
		return "", errors.New("virtual quad worker URL must be the IAM-authenticated function endpoint")
	}
	return endpoint.String(), nil
}
