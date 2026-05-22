package awsx

import (
	"bytes"
	"context"
	"crypto/tls"
	"crypto/x509"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/service/cloudwatchlogs"
	"github.com/aws/aws-sdk-go-v2/service/cloudwatchlogs/types"
	"github.com/mparkachov/txing/rig/internal/rigconfig"
)

type IoTCredentialProvider struct {
	Config rigconfig.Config
	Client *http.Client
}

type credentialProviderResponse struct {
	Credentials struct {
		AccessKeyID     string    `json:"accessKeyId"`
		SecretAccessKey string    `json:"secretAccessKey"`
		SessionToken    string    `json:"sessionToken"`
		Expiration      time.Time `json:"expiration"`
	} `json:"credentials"`
}

func NewIoTCredentialProvider(cfg rigconfig.Config) (*IoTCredentialProvider, error) {
	cert, err := tls.LoadX509KeyPair(cfg.CertificateFile, cfg.PrivateKeyFile)
	if err != nil {
		return nil, err
	}
	rootCA, err := os.ReadFile(cfg.RootCAFile)
	if err != nil {
		return nil, err
	}
	pool := x509.NewCertPool()
	if !pool.AppendCertsFromPEM(rootCA) {
		return nil, fmt.Errorf("parse root CA file %s", cfg.RootCAFile)
	}
	return &IoTCredentialProvider{
		Config: cfg,
		Client: &http.Client{
			Timeout: 20 * time.Second,
			Transport: &http.Transport{
				TLSClientConfig: &tls.Config{
					MinVersion:   tls.VersionTLS12,
					Certificates: []tls.Certificate{cert},
					RootCAs:      pool,
				},
			},
		},
	}, nil
}

func (p *IoTCredentialProvider) Retrieve(ctx context.Context) (aws.Credentials, error) {
	url := fmt.Sprintf("https://%s/role-aliases/%s/credentials", p.Config.IoTCredentialEndpoint, p.Config.IoTRoleAlias)
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return aws.Credentials{}, err
	}
	req.Header.Set("x-amzn-iot-thingname", p.Config.RigID)
	response, err := p.Client.Do(req)
	if err != nil {
		return aws.Credentials{}, err
	}
	defer response.Body.Close()
	body, err := io.ReadAll(io.LimitReader(response.Body, 1<<20))
	if err != nil {
		return aws.Credentials{}, err
	}
	if response.StatusCode < 200 || response.StatusCode >= 300 {
		return aws.Credentials{}, fmt.Errorf("IoT credential provider returned %s: %s", response.Status, string(bytes.TrimSpace(body)))
	}
	var parsed credentialProviderResponse
	if err := json.Unmarshal(body, &parsed); err != nil {
		return aws.Credentials{}, err
	}
	return aws.Credentials{
		AccessKeyID:     parsed.Credentials.AccessKeyID,
		SecretAccessKey: parsed.Credentials.SecretAccessKey,
		SessionToken:    parsed.Credentials.SessionToken,
		Source:          "txing-iot-role-alias",
		CanExpire:       true,
		Expires:         parsed.Credentials.Expiration,
	}, nil
}

func LoadConfig(ctx context.Context, cfg rigconfig.Config) (aws.Config, error) {
	provider, err := NewIoTCredentialProvider(cfg)
	if err != nil {
		return aws.Config{}, err
	}
	return config.LoadDefaultConfig(ctx,
		config.WithRegion(cfg.AWSRegion),
		config.WithCredentialsProvider(aws.NewCredentialsCache(provider)),
	)
}

type CloudWatchLogger struct {
	client        *cloudwatchlogs.Client
	groupName     string
	streamName    string
	retentionDays int32
	sequenceToken *string
	enabled       bool
}

func NewCloudWatchLogger(client *cloudwatchlogs.Client, groupName string, streamName string, retentionDays int32) *CloudWatchLogger {
	return &CloudWatchLogger{
		client:        client,
		groupName:     groupName,
		streamName:    streamName,
		retentionDays: retentionDays,
		enabled:       client != nil && groupName != "" && streamName != "",
	}
}

func (l *CloudWatchLogger) Ensure(ctx context.Context) {
	if !l.enabled {
		return
	}
	_, _ = l.client.CreateLogGroup(ctx, &cloudwatchlogs.CreateLogGroupInput{LogGroupName: &l.groupName})
	_, _ = l.client.PutRetentionPolicy(ctx, &cloudwatchlogs.PutRetentionPolicyInput{
		LogGroupName:    &l.groupName,
		RetentionInDays: aws.Int32(l.retentionDays),
	})
	_, _ = l.client.CreateLogStream(ctx, &cloudwatchlogs.CreateLogStreamInput{
		LogGroupName:  &l.groupName,
		LogStreamName: &l.streamName,
	})
}

func (l *CloudWatchLogger) Print(ctx context.Context, level string, message string) {
	line := fmt.Sprintf("%s level=%s %s", time.Now().UTC().Format(time.RFC3339Nano), level, message)
	fmt.Fprintln(os.Stderr, line)
	if !l.enabled {
		return
	}
	event := types.InputLogEvent{
		Message:   &line,
		Timestamp: aws.Int64(time.Now().UnixMilli()),
	}
	input := &cloudwatchlogs.PutLogEventsInput{
		LogGroupName:  &l.groupName,
		LogStreamName: &l.streamName,
		LogEvents:     []types.InputLogEvent{event},
		SequenceToken: l.sequenceToken,
	}
	output, err := l.client.PutLogEvents(ctx, input)
	if err != nil {
		fmt.Fprintf(os.Stderr, "warning: CloudWatch log publish failed: %v\n", err)
		return
	}
	l.sequenceToken = output.NextSequenceToken
}
