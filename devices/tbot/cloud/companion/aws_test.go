package companion

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/service/lambda"
	"github.com/mparkachov/txing/devices/tbot/cloud/agentstatus"
	"github.com/mparkachov/txing/devices/tbot/cloud/controller"
)

type roundTripper func(*http.Request) (*http.Response, error)

func (fn roundTripper) RoundTrip(r *http.Request) (*http.Response, error) { return fn(r) }
func TestMetadataAndIdentityValidation(t *testing.T) {
	for _, thing := range []string{"unit-test", "tbot-../other", "tbot-test/other", "tbot-+", "tbot-"} {
		if ValidateIdentity(thing, testID) == nil {
			t.Fatal("invalid assigned Thing accepted", thing)
		}
	}
	if ValidateIdentity(testThing, "not-a-token") == nil {
		t.Fatal("invalid launch ID accepted")
	}
	if ValidateIdentity(testThing, testID) != nil {
		t.Fatal("valid identity rejected")
	}
	for _, endpoint := range []string{"https://169.254.170.2/v4/token", "http://example.org/v4/token", "http://169.254.170.2/v4/token?other=1"} {
		if _, err := TaskARN(context.Background(), endpoint, &http.Client{}); err == nil {
			t.Fatal("untrusted metadata endpoint accepted")
		}
	}
	client := &http.Client{Transport: roundTripper(func(req *http.Request) (*http.Response, error) {
		if req.URL.String() != "http://169.254.170.2/v4/token/task" {
			t.Fatal("wrong task metadata path", req.URL)
		}
		return &http.Response{StatusCode: 200, Body: io.NopCloser(strings.NewReader(`{"TaskARN":"arn:aws:ecs:eu-central-1:123456789012:task/cluster/id"}`)), Header: make(http.Header)}, nil
	})}
	if arn, err := TaskARN(context.Background(), "http://169.254.170.2/v4/token", client); err != nil || !strings.Contains(arn, ":task/") {
		t.Fatal("task identity discovery failed", err)
	}
}
func TestReadinessAWSRequestAndLambdaErrors(t *testing.T) {
	for _, message := range []string{"", agentstatus.ErrStaleTask.Error(), agentstatus.ErrVersionConflict.Error(), "task still starting"} {
		t.Run(message, func(t *testing.T) {
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, req *http.Request) {
				if req.Header.Get("X-Amz-Invocation-Type") != "RequestResponse" || !strings.Contains(req.URL.Path, "tbot-companion/invocations") {
					t.Error("invalid readiness invocation")
				}
				var event controller.Event
				if err := json.NewDecoder(req.Body).Decode(&event); err != nil {
					t.Error(err)
				}
				if event.Kind != "readiness" || event.Thing != testThing || event.Readiness == nil || event.Readiness.ShadowVersion != 42 || event.Readiness.ID != testID || event.Readiness.UDPListening {
					t.Errorf("incorrect readiness payload: %+v", event)
				}
				if message != "" {
					w.Header().Set("X-Amz-Function-Error", "Unhandled")
					_ = json.NewEncoder(w).Encode(map[string]string{"errorMessage": message})
				} else {
					w.Write([]byte("null"))
				}
			}))
			defer server.Close()
			cfg := aws.Config{Region: "eu-central-1", Credentials: aws.CredentialsProviderFunc(func(context.Context) (aws.Credentials, error) {
				return aws.Credentials{AccessKeyID: "test", SecretAccessKey: "test-secret"}, nil
			}), HTTPClient: server.Client()}
			cloud := AWSCloud{thing: testThing, function: "tbot-companion", invoke: lambda.NewFromConfig(cfg, func(o *lambda.Options) { o.BaseEndpoint = aws.String(server.URL) })}
			err := cloud.Readiness(context.Background(), controller.Readiness{ID: testID, TaskARN: "task-arn", ShadowVersion: 42, MAVLink: "connected", Video: "disconnected"})
			switch message {
			case "":
				if err != nil {
					t.Fatal(err)
				}
			case agentstatus.ErrStaleTask.Error():
				if err != agentstatus.ErrStaleTask {
					t.Fatal("lost fencing error", err)
				}
			case agentstatus.ErrVersionConflict.Error():
				if err != agentstatus.ErrVersionConflict {
					t.Fatal("lost conflict error", err)
				}
			default:
				if err == nil {
					t.Fatal("ignored Lambda FunctionError")
				}
			}
		})
	}
}
