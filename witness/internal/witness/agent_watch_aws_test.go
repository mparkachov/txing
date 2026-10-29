package witness

import (
	"context"
	"fmt"
	"net/http"
	"net/http/httptest"
	"reflect"
	"sync"
	"testing"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/credentials"
	"github.com/aws/aws-sdk-go-v2/service/iot"
	"github.com/aws/aws-sdk-go-v2/service/iotdataplane"
	"github.com/aws/aws-sdk-go-v2/service/lambdamicrovms"
)

func TestAgentWatchSDKRequests(t *testing.T) {
	var mutex sync.Mutex
	var operations []string
	terminal := false
	server := httptest.NewServer(http.HandlerFunc(func(rw http.ResponseWriter, r *http.Request) {
		mutex.Lock()
		defer mutex.Unlock()
		rw.Header().Set("Content-Type", "application/json")
		if r.Header.Get("Authorization") == "" {
			t.Error("SDK request was unsigned")
		}
		switch {
		case r.URL.Path == "/things":
			if r.URL.Query().Get("thingTypeName") != "" || r.URL.Query().Get("attributeName") != "" {
				t.Error("watch inventory hid assignments after type/capability removal")
			}
			fmt.Fprint(rw, `{"things":[{"thingName":"tbot-test"}]}`)
		case r.URL.Path == "/things/tbot-test/shadow":
			if r.Method != "GET" || r.URL.Query().Get("name") != "agent" {
				t.Error("watch tried a non-agent read or a write")
			}
			rw.Write(watchBody("stopping", "vm-1", 200, 3100))
		case r.URL.Path == "/2025-09-09/microvms":
			if r.Method != "GET" || r.URL.Query().Get("imageIdentifier") != testWatchImage {
				t.Error("bad image inventory request")
			}
			if r.URL.Query().Get("nextToken") == "" {
				operations = append(operations, "page1")
				state := "RUNNING"
				if terminal {
					state = "TERMINATED"
				}
				fmt.Fprintf(rw, `{"items":[{"microvmId":"vm-1","imageArn":%q,"state":%q,"startedAt":100}],"nextToken":"page2"}`, testWatchImage, state)
			} else {
				operations = append(operations, "page2")
				fmt.Fprint(rw, `{"items":[]}`)
			}
		case r.URL.Path == "/2025-09-09/microvms/vm-1" && r.Method == "GET":
			state := "RUNNING"
			if terminal {
				state = "TERMINATED"
			}
			fmt.Fprintf(rw, `{"microvmId":"vm-1","imageArn":%q,"state":%q,"startedAt":100}`, testWatchImage, state)
		case r.URL.Path == "/2025-09-09/microvms/vm-1" && r.Method == "DELETE":
			operations = append(operations, "terminate")
			fmt.Fprint(rw, `{"microvmId":"vm-1","state":"TERMINATING"}`)
		default:
			t.Errorf("unexpected API request: %s %s", r.Method, r.URL)
			http.Error(rw, "unexpected", 400)
		}
	}))
	defer server.Close()
	cfg := aws.Config{Region: "eu-central-1", Credentials: credentials.NewStaticCredentialsProvider("test-key", "test-secret", ""), HTTPClient: server.Client(), RetryMaxAttempts: 1}
	c := &AWSClient{
		iot:      iot.NewFromConfig(cfg, func(o *iot.Options) { o.BaseEndpoint = aws.String(server.URL) }),
		iotData:  iotdataplane.NewFromConfig(cfg, func(o *iotdataplane.Options) { o.BaseEndpoint = aws.String(server.URL) }),
		microvms: lambdamicrovms.NewFromConfig(cfg, func(o *lambdamicrovms.Options) { o.BaseEndpoint = aws.String(server.URL) }),
	}
	w := AgentWatcher{AWS: c, Image: testWatchImage, Now: func() time.Time { return time.Unix(320, 0) }}
	result, err := w.Sweep(context.Background())
	if err != nil || result.Requested != 1 || !result.Incomplete || !reflect.DeepEqual(operations, []string{"page1", "terminate", "page2"}) {
		t.Fatalf("%+v %v %v", result, err, operations)
	}
	mutex.Lock()
	terminal = true
	operations = nil
	mutex.Unlock()
	result, err = w.Sweep(context.Background())
	if err != nil || result.Requested != 0 || result.Incomplete {
		t.Fatalf("terminal inventory: %+v %v", result, err)
	}
}
