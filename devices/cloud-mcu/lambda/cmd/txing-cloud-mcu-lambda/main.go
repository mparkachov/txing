package main

import (
	"context"
	"encoding/json"
	"log"

	"github.com/aws/aws-lambda-go/lambda"

	"txing.dev/cloud-mcu-lambda/internal/cloudmcu"
	"txing.dev/cloud-mcu-lambda/internal/lambdalog"
	"txing.dev/cloud-mcu-lambda/internal/version"
)

func main() {
	lambdalog.PrintColdStart("txing-cloud-mcu-lambda", version.Version)

	ctx := context.Background()
	awsClient, err := cloudmcu.NewAWSClient(ctx)
	if err != nil {
		log.Fatalf("initialize AWS cloud client: %v", err)
	}
	lambda.StartWithOptions(func(ctx context.Context, event json.RawMessage) (map[string]any, error) {
		var payload map[string]any
		if err := json.Unmarshal(event, &payload); err != nil {
			return nil, err
		}
		return cloudmcu.HandleMcuLambdaEvent(ctx, payload, awsClient)
	})
}
