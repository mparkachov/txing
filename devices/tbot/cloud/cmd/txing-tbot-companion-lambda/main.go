package main

import (
	"context"
	"encoding/json"
	"log/slog"
	"os"
	"strings"
	"time"

	"github.com/aws/aws-lambda-go/lambda"
	"github.com/mparkachov/txing/devices/tbot/cloud/controller"
)

func main() {
	log := slog.New(slog.NewJSONHandler(os.Stdout, nil))
	// Initialize lazily inside invocation context: discovery/config failures then
	// produce actionable invocation logs instead of an endless init retry loop.
	var instance *controller.Controller
	lambda.Start(func(ctx context.Context, payload json.RawMessage) error {
		ctx, cancel := context.WithTimeout(ctx, 50*time.Second)
		defer cancel()
		event, err := controller.DecodeEvent(payload)
		if err != nil {
			return err
		}
		if instance == nil {
			cloud, err := controller.NewAWS(ctx, controller.Settings{Cluster: os.Getenv("TBOT_COMPANION_CLUSTER"), Definition: os.Getenv("TBOT_COMPANION_TASK_DEFINITION"), Subnets: strings.Split(os.Getenv("TBOT_COMPANION_SUBNETS"), ","), SecurityGroup: os.Getenv("TBOT_COMPANION_SECURITY_GROUP"), Function: os.Getenv("AWS_LAMBDA_FUNCTION_NAME"), Platform: os.Getenv("TBOT_COMPANION_PLATFORM_VERSION")})
			if err != nil {
				log.ErrorContext(ctx, "controller initialization failed", "error", err)
				return err
			}
			instance = controller.New(cloud, log)
		}
		err = instance.Handle(ctx, event)
		if err != nil {
			log.ErrorContext(ctx, "controller invocation failed", "kind", event.Kind, "thing", event.Thing, "error", err)
		}
		return err
	})
}
