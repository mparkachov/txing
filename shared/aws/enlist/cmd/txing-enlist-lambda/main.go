package main

import (
	"context"
	"encoding/json"
	"log"

	"github.com/aws/aws-lambda-go/lambda"

	"txing.dev/enlist/internal/enlist"
)

func main() {
	ctx := context.Background()
	awsClient, err := enlist.NewAWSClient(ctx)
	if err != nil {
		log.Fatalf("initialize AWS enlist client: %v", err)
	}
	responder := enlist.HTTPCfnResponder{}
	lambda.StartWithOptions(func(ctx context.Context, event json.RawMessage) (map[string]any, error) {
		var payload map[string]any
		if err := json.Unmarshal(event, &payload); err != nil {
			return nil, err
		}
		return enlist.HandleLambdaEvent(ctx, payload, awsClient, responder), nil
	})
}
