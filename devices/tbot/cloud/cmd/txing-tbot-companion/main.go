package main

import (
	"context"
	"errors"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"strings"
	"syscall"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/credentials/endpointcreds"
	"github.com/mparkachov/txing/devices/tbot/cloud/agentstatus"
	"github.com/mparkachov/txing/devices/tbot/cloud/companion"
)

func run(ctx context.Context) error {
	thing, id, function := os.Getenv("TXING_THING_ID"), os.Getenv("TXING_AGENT_TASK_ID"), os.Getenv("TXING_AGENT_CONTROLLER_FUNCTION")
	if err := companion.ValidateIdentity(thing, id); err != nil {
		return err
	}
	if function == "" || os.Getenv("AWS_CONTAINER_CREDENTIALS_RELATIVE_URI") == "" {
		return errors.New("controller function and Fargate task role are required")
	}
	relative := os.Getenv("AWS_CONTAINER_CREDENTIALS_RELATIVE_URI")
	if !strings.HasPrefix(relative, "/v2/credentials/") || strings.ContainsAny(relative, "?#") {
		return errors.New("invalid Fargate task credential endpoint")
	}
	provider := endpointcreds.New("http://169.254.170.2"+relative, func(o *endpointcreds.Options) { o.HTTPClient = &http.Client{Timeout: 4 * time.Second} })
	cfg, err := config.LoadDefaultConfig(ctx, config.WithCredentialsProvider(provider), config.WithSharedConfigFiles([]string{}), config.WithSharedCredentialsFiles([]string{}), config.WithRetryMaxAttempts(3), config.WithHTTPClient(&http.Client{Timeout: 4 * time.Second}), config.WithCredentialsCacheOptions(func(o *aws.CredentialsCacheOptions) { o.ExpiryWindow = 5 * time.Minute }))
	if err != nil {
		return errors.New("task AWS configuration failed")
	}
	if cfg.Region == "" {
		return errors.New("AWS Region is required")
	}
	init, cc := context.WithTimeout(ctx, 8*time.Second)
	arn, err := companion.TaskARN(init, os.Getenv("ECS_CONTAINER_METADATA_URI_V4"), companion.MetadataHTTPClient())
	cc()
	if err != nil {
		return err
	}
	init, cc = context.WithTimeout(ctx, 8*time.Second)
	cloud, err := companion.NewCloud(init, cfg, thing, function)
	cc()
	if err != nil {
		return err
	}
	path := os.Getenv("TXING_KVS_VIEWER_PATH")
	if path == "" {
		path = "/usr/local/bin/txing-tbot-kvs-viewer"
	}
	ca := os.Getenv("TXING_KVS_SYSTEM_CA_CERT_PATH")
	if ca == "" {
		ca = "/etc/ssl/certs/Starfield_Services_Root_Certificate_Authority_-_G2.pem"
	}
	// The SDK cache subtracts its early-refresh window from Expires. Native
	// viewers need the actual task-role expiry to survive transient refresh errors.
	runtime := companion.New(thing, id, arn, cloud, &companion.ProcessFactory{Path: path, Thing: thing, ID: id, Region: cfg.Region, CA: ca, Credentials: provider})
	bridge, err := companion.ListenUDPBridge(14550)
	if err != nil {
		return err
	}
	defer bridge.Close()
	runtime.Bridge = bridge
	return runtime.Run(ctx)
}
func main() {
	ctx, cc := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer cc()
	if err := run(ctx); err != nil && !errors.Is(err, context.Canceled) && !errors.Is(err, agentstatus.ErrStaleTask) {
		slog.Error("companion stopped", "error", err)
		os.Exit(1)
	}
}
