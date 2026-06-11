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
	lambdalog.PrintColdStart("txing-cloud-rig-lambda", version.Version)

	ctx := context.Background()
	awsClient, err := cloudmcu.NewAWSClient(ctx)
	if err != nil {
		log.Fatalf("initialize AWS cloud client: %v", err)
	}
	lambda.StartWithOptions(func(ctx context.Context, rawEvent json.RawMessage) (map[string]any, error) {
		var event map[string]any
		if len(rawEvent) > 0 {
			if err := json.Unmarshal(rawEvent, &event); err != nil {
				return nil, err
			}
		}
		if event == nil {
			event = map[string]any{}
		}
		return cloudmcu.HandleRigLambdaEvent(ctx, event, awsClient)
	})
}
