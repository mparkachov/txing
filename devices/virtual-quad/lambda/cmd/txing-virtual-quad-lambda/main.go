package main

import (
	"context"
	"errors"
	"fmt"
	"log"
	"os"
	"time"

	"github.com/aws/aws-lambda-go/lambda"
	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/service/iot"
	"github.com/aws/aws-sdk-go-v2/service/iotdataplane"
	"txing.dev/virtual-quad-lambda/internal/controller"
	"txing.dev/virtual-quad-lambda/internal/qualification"
	"txing.dev/virtual-quad-lambda/internal/version"
)

func main() {
	log.Printf("service=txing-virtual-quad-lambda version=%s cold_start=true", version.Version)
	if os.Getenv("TXING_VIRTUAL_QUAD_QUALIFICATION") == "true" {
		lambda.Start(qualification.Handle)
		return
	}
	ctx, cancel := context.WithTimeout(context.Background(), 8*time.Second)
	handler, err := initialize(ctx)
	cancel()
	if err != nil {
		log.Fatalf("initialize virtual quad controller: %v", err)
	}
	lambda.Start(handler.Handle)
}

func initialize(ctx context.Context) (controller.LambdaHandler, error) {
	var empty controller.LambdaHandler
	cfg, err := config.LoadDefaultConfig(ctx, config.WithRetryMaxAttempts(2))
	if err != nil {
		return empty, err
	}
	if cfg.Region != "eu-central-1" || os.Getenv("LAMBDA_TASK_ROOT") == "" {
		return empty, errors.New("virtual quad requires the Frankfurt Lambda runtime")
	}
	things := iot.NewFromConfig(cfg)
	endpoint, err := things.DescribeEndpoint(ctx, &iot.DescribeEndpointInput{EndpointType: aws.String("iot:Data-ATS")})
	if err != nil {
		return empty, fmt.Errorf("resolve IoT data endpoint: %w", err)
	}
	address := aws.ToString(endpoint.EndpointAddress)
	if address == "" {
		return empty, errors.New("IoT data endpoint is empty")
	}
	shadows := iotdataplane.NewFromConfig(cfg, func(options *iotdataplane.Options) {
		options.BaseEndpoint = aws.String("https://" + address)
	})
	return controller.NewLambdaHandler(cfg, address, controller.NewAWSRegistry(things, shadows), shadows), nil
}
