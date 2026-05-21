package main

import (
	"context"
	"encoding/json"
	"log"

	"github.com/aws/aws-lambda-go/lambda"

	"txing.dev/cloud-mcu-lambda/internal/cloudmcu"
)

func main() {
	ctx := context.Background()
	awsClient, err := cloudmcu.NewAWSClient(ctx)
	if err != nil {
		log.Fatalf("initialize AWS cloud client: %v", err)
	}
	lambda.StartWithOptions(func(ctx context.Context, _ json.RawMessage) (map[string]any, error) {
		return cloudmcu.HandleRigLambdaEvent(ctx, awsClient)
	})
}
