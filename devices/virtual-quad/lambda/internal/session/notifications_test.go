package session

import (
	"context"
	"net/url"
	"strings"
	"testing"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/credentials"
)

func TestSignedMQTTURL(t *testing.T) {
	cfg := aws.Config{Region: "eu-central-1", Credentials: credentials.NewStaticCredentialsProvider("test-key", "test-secret", "test-token")}
	raw, err := signedMQTTURL(context.Background(), cfg, "example.iot.eu-central-1.amazonaws.com", time.Unix(1700000000, 0))
	if err != nil {
		t.Fatal(err)
	}
	u, err := url.Parse(raw)
	if err != nil {
		t.Fatal(err)
	}
	q := u.Query()
	if u.Scheme != "wss" || u.Path != "/mqtt" || q.Get("X-Amz-Security-Token") != "test-token" ||
		q.Get("X-Amz-Signature") == "" || !strings.Contains(q.Get("X-Amz-Credential"), "/eu-central-1/iotdevicegateway/") {
		t.Fatalf("invalid signed MQTT URL: %#v", u)
	}
	withoutToken := aws.Config{Region: cfg.Region, Credentials: credentials.NewStaticCredentialsProvider("test-key", "test-secret", "")}
	other, err := signedMQTTURL(context.Background(), withoutToken, "example.iot.eu-central-1.amazonaws.com", time.Unix(1700000000, 0))
	if err != nil {
		t.Fatal(err)
	}
	otherURL, err := url.Parse(other)
	if err != nil {
		t.Fatal(err)
	}
	if q.Get("X-Amz-Signature") != otherURL.Query().Get("X-Amz-Signature") {
		t.Fatal("IoT session token was included in the signature")
	}
}
