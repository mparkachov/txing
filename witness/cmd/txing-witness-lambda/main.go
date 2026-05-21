package main

import (
	"context"
	"encoding/json"
	"log"

	"github.com/aws/aws-lambda-go/lambda"

	"txing.dev/witness/internal/witness"
)

func main() {
	ctx := context.Background()
	awsClient, err := witness.NewAWSClient(ctx)
	if err != nil {
		log.Fatalf("initialize AWS witness client: %v", err)
	}
	lambda.StartWithOptions(func(ctx context.Context, event json.RawMessage) (map[string]any, error) {
		var payload map[string]any
		if err := json.Unmarshal(event, &payload); err != nil {
			return nil, err
		}
		return witness.HandleLambdaEvent(ctx, payload, awsClient)
	})
}
