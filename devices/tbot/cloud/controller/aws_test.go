package controller

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/credentials"
	"github.com/aws/aws-sdk-go-v2/service/ec2"
	"github.com/aws/aws-sdk-go-v2/service/ecs"
	"github.com/aws/aws-sdk-go-v2/service/iot"
	"github.com/aws/aws-sdk-go-v2/service/iotdataplane"
	"github.com/mparkachov/txing/devices/tbot/cloud/agentstatus"
)

func testAWS(t *testing.T, handle http.HandlerFunc) *AWSCloud {
	t.Helper()
	server := httptest.NewServer(handle)
	t.Cleanup(server.Close)
	cfg := aws.Config{Region: "eu-central-1", Credentials: credentials.NewStaticCredentialsProvider("test", "test", ""), HTTPClient: server.Client(), RetryMaxAttempts: 1}
	return &AWSCloud{
		IoT:      iot.NewFromConfig(cfg, func(o *iot.Options) { o.BaseEndpoint = aws.String(server.URL) }),
		Data:     iotdataplane.NewFromConfig(cfg, func(o *iotdataplane.Options) { o.BaseEndpoint = aws.String(server.URL) }),
		ECS:      ecs.NewFromConfig(cfg, func(o *ecs.Options) { o.BaseEndpoint = aws.String(server.URL) }),
		EC2:      ec2.NewFromConfig(cfg, func(o *ec2.Options) { o.BaseEndpoint = aws.String(server.URL) }),
		Settings: Settings{Cluster: "cluster", Definition: "definition:1", SecurityGroup: "sg-1", Subnets: []string{"subnet-1", "subnet-2"}, Platform: "1.4.0", Function: "controller"},
	}
}

func taskResponse(id string) string {
	return fmt.Sprintf(`{"taskArn":"arn:task/one","lastStatus":"RUNNING","desiredStatus":"RUNNING","tags":[{"key":"txing:managed-by","value":"tbot-companion"},{"key":"txing:thing","value":"tbot-test"},{"key":"txing:agent-id","value":%q}],"attachments":[{"type":"ElasticNetworkInterface","details":[{"name":"networkInterfaceId","value":"eni-1"}]}]}`, id)
}

func TestAWSRunTaskContractAndConflictRecovery(t *testing.T) {
	id := "launch-token"
	calls := 0
	cloud := testAWS(t, func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/x-amz-json-1.1")
		var body map[string]json.RawMessage
		if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
			t.Error(err)
		}
		switch {
		case strings.HasSuffix(r.Header.Get("X-Amz-Target"), "RunTask"):
			calls++
			var token, definition string
			_ = json.Unmarshal(body["clientToken"], &token)
			_ = json.Unmarshal(body["taskDefinition"], &definition)
			if token != id || definition != "definition:1" {
				t.Error("request lost token or pinned definition", token, definition)
			}
			var network struct {
				VPC struct {
					PublicIP string   `json:"assignPublicIp"`
					Subnets  []string `json:"subnets"`
				} `json:"awsvpcConfiguration"`
			}
			_ = json.Unmarshal(body["networkConfiguration"], &network)
			if network.VPC.PublicIP != "ENABLED" || len(network.VPC.Subnets) != 2 {
				t.Error("task did not request dual-stack public networking")
			}
			var overrides struct {
				Containers []struct {
					Name        string                         `json:"name"`
					Environment []struct{ Name, Value string } `json:"environment"`
				} `json:"containerOverrides"`
			}
			_ = json.Unmarshal(body["overrides"], &overrides)
			if len(overrides.Containers) != 1 || overrides.Containers[0].Name != "tbot-companion" {
				t.Error("wrong container override")
			} else {
				env := map[string]string{}
				for _, entry := range overrides.Containers[0].Environment {
					env[entry.Name] = entry.Value
				}
				if env["TXING_THING_ID"] != thing || env["TXING_AGENT_TASK_ID"] != id || env["TXING_AGENT_CONTROLLER_FUNCTION"] != "controller" {
					t.Error("missing runtime identity", env)
				}
			}
			if calls == 1 {
				fmt.Fprintf(w, `{"tasks":[%s]}`, taskResponse(id))
			} else {
				w.WriteHeader(400)
				fmt.Fprint(w, `{"__type":"ConflictException","message":"original request had a different revision","resourceIds":["arn:task/one"]}`)
			}
		case strings.HasSuffix(r.Header.Get("X-Amz-Target"), "DescribeTasks"):
			if string(body["include"]) != `["TAGS"]` {
				t.Error("task describe did not include fencing tags")
			}
			fmt.Fprintf(w, `{"tasks":[%s]}`, taskResponse(id))
		default:
			t.Error("unexpected request", r.Header.Get("X-Amz-Target"))
			w.WriteHeader(500)
		}
	})
	for i := 0; i < 2; i++ {
		task, err := cloud.Run(context.Background(), thing, id)
		if err != nil {
			t.Fatal(err)
		}
		if task.ID != id || task.Thing != thing || task.ENI != "eni-1" || !task.Running() {
			t.Fatal("wrong task identity", task)
		}
	}
}

func TestAWSShadowVersionAndMissingShadow(t *testing.T) {
	mode := "read"
	cloud := testAWS(t, func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Query().Get("name") != "agent" || r.URL.Path != "/things/tbot-test/shadow" {
			t.Error("wrong shadow path", r.URL.String())
		}
		w.Header().Set("Content-Type", "application/json")
		switch mode {
		case "read":
			fmt.Fprint(w, `{"state":{"reported":{"task":{"status":"stopped"},"mavlink":"disconnected","video":"disconnected"}},"version":42}`)
		case "write", "conflict":
			var document struct {
				State struct {
					Reported agentstatus.Reported `json:"reported"`
				} `json:"state"`
				Version int64 `json:"version"`
			}
			if err := json.NewDecoder(r.Body).Decode(&document); err != nil {
				t.Error(err)
			}
			if document.Version != 42 || document.State.Reported.Task.Status != "stopped" {
				t.Error("write was not version conditional", document)
			}
			if mode == "conflict" {
				w.Header().Set("X-Amzn-Errortype", "ConflictException")
				w.WriteHeader(409)
				fmt.Fprint(w, `{"message":"version conflict"}`)
			} else {
				fmt.Fprint(w, `{}`)
			}
		case "missing":
			w.Header().Set("X-Amzn-Errortype", "ResourceNotFoundException")
			w.WriteHeader(404)
			fmt.Fprint(w, `{"message":"missing"}`)
		}
	})
	store := cloud.Store(thing)
	state, version, err := store.Read(context.Background())
	if err != nil || version != 42 || state.Task.Status != "stopped" {
		t.Fatal(state, version, err)
	}
	mode = "write"
	if err := store.Write(context.Background(), agentstatus.Stopped(), 42); err != nil {
		t.Fatal(err)
	}
	mode = "conflict"
	if err := store.Write(context.Background(), agentstatus.Stopped(), 42); !errors.Is(err, agentstatus.ErrVersionConflict) {
		t.Fatal(err)
	}
	mode = "missing"
	if _, _, err := store.Read(context.Background()); !errors.Is(err, ErrNotFound) {
		t.Fatal(err)
	}
}

func TestAWSPaginationAndManagedTaskFiltering(t *testing.T) {
	searches := 0
	lists := 0
	cloud := testAWS(t, func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		if strings.Contains(r.URL.Path, "/indices/") {
			searches++
			if searches == 1 {
				fmt.Fprint(w, `{"things":[{"thingName":"tbot-test"}],"nextToken":"next"}`)
			} else {
				fmt.Fprint(w, `{"things":[{"thingName":"tbot-other"}]}`)
			}
			return
		}
		switch {
		case strings.HasSuffix(r.Header.Get("X-Amz-Target"), "ListTasks"):
			lists++
			if lists == 1 {
				fmt.Fprint(w, `{"taskArns":["one"],"nextToken":"page-two"}`)
			} else if lists == 2 {
				fmt.Fprint(w, `{"taskArns":["two"]}`)
			} else {
				fmt.Fprint(w, `{"taskArns":["one","stopped"]}`)
			}
		case strings.HasSuffix(r.Header.Get("X-Amz-Target"), "DescribeTasks"):
			var request struct {
				Tasks []string `json:"tasks"`
			}
			if err := json.NewDecoder(r.Body).Decode(&request); err != nil {
				t.Error(err)
			}
			seen := map[string]bool{}
			for _, arn := range request.Tasks {
				if seen[arn] {
					t.Error("status transition duplicated an ARN", request.Tasks)
				}
				seen[arn] = true
			}
			fmt.Fprintf(w, `{"tasks":[%s,{"taskArn":"unrelated","lastStatus":"RUNNING","tags":[]}],"failures":[{"arn":"vanished","reason":"MISSING"}]}`, taskResponse("identity"))
		default:
			t.Error("unexpected request", r.URL, r.Header)
			w.WriteHeader(500)
		}
	})
	names, err := cloud.Things(context.Background())
	if err != nil || len(names) != 2 || searches != 2 {
		t.Fatal(names, err)
	}
	tasks, err := cloud.Tasks(context.Background())
	if err != nil || len(tasks) != 1 || lists != 3 {
		t.Fatal(tasks, err)
	}
}

func TestAWSPublicAddressesAndDefinitiveStartFailure(t *testing.T) {
	mode := "address"
	cloud := testAWS(t, func(w http.ResponseWriter, r *http.Request) {
		if mode == "failure" {
			w.Header().Set("Content-Type", "application/x-amz-json-1.1")
			fmt.Fprint(w, `{"failures":[{"reason":"RESOURCE:ENI","detail":"insufficient addresses"}]}`)
			return
		}
		if err := r.ParseForm(); err != nil {
			t.Error(err)
		}
		if r.Form.Get("Action") != "DescribeNetworkInterfaces" || r.Form.Get("NetworkInterfaceId.1") != "eni-1" {
			t.Error("incorrect EC2 lookup", r.Form)
		}
		w.Header().Set("Content-Type", "text/xml")
		fmt.Fprint(w, `<DescribeNetworkInterfacesResponse xmlns="http://ec2.amazonaws.com/doc/2016-11-15/"><networkInterfaceSet><item><networkInterfaceId>eni-1</networkInterfaceId><association><publicIp>203.0.113.10</publicIp></association><ipv6AddressesSet><item><ipv6Address>2001:db8::10</ipv6Address></item></ipv6AddressesSet></item></networkInterfaceSet></DescribeNetworkInterfacesResponse>`)
	})
	ipv4, ipv6, err := cloud.Addresses(context.Background(), Task{ENI: "eni-1"})
	if err != nil || ipv4 != "203.0.113.10" || ipv6 != "2001:db8::10" {
		t.Fatal(ipv4, ipv6, err)
	}
	mode = "failure"
	if _, err := cloud.Run(context.Background(), thing, "token"); !errors.Is(err, ErrStartRejected) {
		t.Fatal(err)
	}
}

func TestAWSRepeatedPaginationTokenIsBounded(t *testing.T) {
	for _, which := range []string{"iot", "ecs"} {
		t.Run(which, func(t *testing.T) {
			calls := 0
			cloud := testAWS(t, func(w http.ResponseWriter, r *http.Request) {
				calls++
				w.Header().Set("Content-Type", "application/json")
				fmt.Fprint(w, `{"nextToken":"same"}`)
			})
			var err error
			if which == "iot" {
				_, err = cloud.Things(context.Background())
			} else {
				_, err = cloud.Tasks(context.Background())
			}
			if err == nil || calls != 2 {
				t.Fatal("pagination failed to stop", calls, err)
			}
		})
	}
}
