package main

import (
	"context"
	"encoding/json"
	"log"
	"os"

	"github.com/aws/aws-lambda-go/lambda"

	"txing.dev/witness/internal/lambdalog"
	"txing.dev/witness/internal/version"
	"txing.dev/witness/internal/witness"
)

func main() {
	lambdalog.PrintColdStart("txing-witness-lambda", version.Version)

	ctx := context.Background()
	awsClient, err := witness.NewAWSClient(ctx)
	if err != nil {
		log.Fatalf("initialize AWS witness client: %v", err)
	}
	watcher := witness.AgentWatcher{AWS: awsClient, Projection: awsClient, Image: os.Getenv("TXING_AGENT_WATCH_IMAGE")}
	lambda.StartWithOptions(func(ctx context.Context, event json.RawMessage) (map[string]any, error) {
		var payload map[string]any
		if err := json.Unmarshal(event, &payload); err != nil {
			return nil, err
		}
		return watcher.Handle(ctx, payload)
	})
}
