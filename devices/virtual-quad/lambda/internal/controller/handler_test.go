package controller

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"errors"
	"net/http"
	"testing"
	"time"

	"github.com/aws/aws-sdk-go-v2/service/lambdamicrovms/types"
	"google.golang.org/protobuf/encoding/protowire"
	"txing.dev/virtual-quad-lambda/internal/lifecycle"
)

const commandTopic = "spBv1.0/town-test/DCMD/cloud-test/virtual-quad-test"

const officeStart = "COgHEgwKBnJlZGNvbiADUAESPwoVdmlydHVhbFF1YWQucmVxdWVzdElkIAx6JDAwMDAwMDAwLTAwMDAtNDAwMC04MDAwLTAwMDAwMDAwMDAwMRIyChx2aXJ0dWFsUXVhZC50ZXJtaW5hbFJldmlzaW9uIAx6EDkwMDcxOTkyNTQ3NDA5OTEYGQ=="
const officeStop = "COgHEgwKBnJlZGNvbiADUAQSPwoVdmlydHVhbFF1YWQucmVxdWVzdElkIAx6JDAwMDAwMDAwLTAwMDAtNDAwMC04MDAwLTAwMDAwMDAwMDAwMhInChV2aXJ0dWFsUXVhZC5zZXNzaW9uSWQgDHoMU0VTU0lPTl9URVNUGBk="
const startID = "00000000-0000-4000-8000-000000000001"
const stopID = "00000000-0000-4000-8000-000000000002"
const workerRole = "arn:aws:iam::123456789012:role/test/quad-worker"
const workerPrincipal = "arn:aws:sts::123456789012:assumed-role/quad-worker/test"

var testAssignment = lifecycle.Assignment{DeviceID: "virtual-quad-test", TownID: "town-test", RigID: "cloud-test"}

func TestOfficeCommandEncoding(t *testing.T) {
	start, err := decodeCommand(commandTopic, officeStart)
	if err != nil || start.Assignment != testAssignment || start.REDCON != 1 ||
		start.Request.ID != startID || start.Request.Sequence != 25 || start.TerminalRevision != 9007199254740991 {
		t.Fatalf("Office Start did not preserve its command metadata: %#v %v", start, err)
	}
	stop, err := decodeCommand(commandTopic, officeStop)
	if err != nil || stop.REDCON != 4 || stop.SessionID != "SESSION_TEST" || stop.Request.ID != stopID {
		t.Fatalf("Office Stop did not preserve its session target: %#v %v", stop, err)
	}
	for _, payload := range []string{
		encodeTestCommand(1, startID, sessionMetric, "SESSION_TEST"),
		encodeTestCommand(4, stopID, revisionMetric, "1"),
		encodeTestCommand(1, startID, revisionMetric, "01"),
		encodeTestCommand(1, startID, requestMetric, startID),
		"not a packet",
	} {
		if _, err := decodeCommand(commandTopic, payload); !errors.Is(err, lifecycle.ErrInvalidRequest) {
			t.Fatalf("invalid command accepted: %v", err)
		}
	}
}

func encodeTestCommand(redcon uint64, request, targetName, targetValue string) string {
	appendMetric := func(packet []byte, name string, datatype uint64, value []byte) []byte {
		metric := protowire.AppendString(protowire.AppendTag(nil, 1, protowire.BytesType), name)
		metric = protowire.AppendVarint(protowire.AppendTag(metric, 4, protowire.VarintType), datatype)
		metric = append(metric, value...)
		return protowire.AppendBytes(protowire.AppendTag(packet, 2, protowire.BytesType), metric)
	}
	text := func(value string) []byte {
		return protowire.AppendString(protowire.AppendTag(nil, 15, protowire.BytesType), value)
	}
	packet := appendMetric(nil, "redcon", typeInt32, protowire.AppendVarint(protowire.AppendTag(nil, 10, protowire.VarintType), redcon))
	packet = appendMetric(packet, requestMetric, typeString, text(request))
	packet = appendMetric(packet, targetName, typeString, text(targetValue))
	packet = protowire.AppendVarint(protowire.AppendTag(packet, 3, protowire.VarintType), 25)
	return base64.StdEncoding.EncodeToString(packet)
}

type testStore struct{ raw []byte }

func (s *testStore) Load(context.Context, string) (lifecycle.Record, error) {
	var record lifecycle.Record
	if s.raw == nil {
		return record, nil
	}
	err := json.Unmarshal(s.raw, &record)
	return record, err
}

func (s *testStore) CompareAndSwap(ctx context.Context, version uint64, replacement lifecycle.Record) (bool, error) {
	current, err := s.Load(ctx, replacement.DeviceID)
	if err != nil || current.Version != version {
		return false, err
	}
	s.raw, err = json.Marshal(replacement)
	return err == nil, err
}

func (s *testStore) Records(ctx context.Context) ([]lifecycle.Record, error) {
	record, err := s.Load(ctx, testAssignment.DeviceID)
	return []lifecycle.Record{record}, err
}

type testRegistry struct {
	awake bool
	err   error
}

func (r testRegistry) Assignment(context.Context, string) (lifecycle.Assignment, bool, error) {
	return testAssignment, r.awake, r.err
}

type testPlatform struct {
	vm       lifecycle.MicroVM
	launches int
	stops    int
}

func (p *testPlatform) Run(_ context.Context, launch lifecycle.Launch) (string, error) {
	p.launches++
	p.vm = lifecycle.MicroVM{ID: "microvm-test", ImageARN: launch.ImageARN, ImageVersion: "8.0", State: types.MicrovmStateRunning}
	return p.vm.ID, nil
}

func (p *testPlatform) Get(context.Context, string) (lifecycle.MicroVM, error) {
	observed := p.vm
	if p.vm.State == types.MicrovmStateTerminating {
		p.vm.State = types.MicrovmStateTerminated
	}
	return observed, nil
}

func (p *testPlatform) Terminate(context.Context, string) error {
	p.stops++
	p.vm.State = types.MicrovmStateTerminating
	return nil
}

func (p *testPlatform) Inventory(context.Context, string) ([]lifecycle.MicroVM, error) {
	return []lifecycle.MicroVM{p.vm}, nil
}

type testReporter struct{ receipts []lifecycle.Receipt }

func (p *testReporter) Publish(_ context.Context, _ lifecycle.Assignment, receipt *lifecycle.Receipt) error {
	if receipt != nil {
		p.receipts = append(p.receipts, *receipt)
	}
	return nil
}

func TestHandlerRoutesCommandsAndWorkerGrant(t *testing.T) {
	store, platform, reports := &testStore{}, &testPlatform{}, &testReporter{}
	ledger := lifecycle.NewLedger(store)
	launch := lifecycle.LaunchConfig{
		ImageARN: "image", ExecutionRoleARN: workerRole,
		IngressConnector: "NO_INGRESS", EgressConnector: "INTERNET_EGRESS", LogGroup: "logs", ControllerURL: "https://example.test/",
	}
	handler, err := NewHandler(ledger, lifecycle.NewReconciler(ledger, platform, launch), testRegistry{awake: true}, store, reports, workerRole)
	if err != nil {
		t.Fatal(err)
	}
	dispatch := func(input event) (any, error) {
		raw, err := json.Marshal(input)
		if err != nil {
			t.Fatal(err)
		}
		return handler.Handle(t.Context(), raw)
	}
	start := event{Topic: commandTopic, PayloadBase64: encodeTestCommand(1, startID, revisionMetric, "0")}
	for i := 0; i < 2; i++ {
		result, err := dispatch(start)
		if err != nil || result.(lifecycle.Receipt).Status != lifecycle.Accepted {
			t.Fatalf("Start delivery %d: %#v %v", i+1, result, err)
		}
	}
	if platform.launches != 1 || reports.receipts[0].RequestID != startID || reports.receipts[0].Sequence != 25 {
		t.Fatal("duplicate delivery launched twice or lost the correlation metadata")
	}
	record, err := store.Load(t.Context(), testAssignment.DeviceID)
	if err != nil || record.Session == nil {
		t.Fatalf("missing session after Start: %v", err)
	}
	worker := lifecycle.Worker{SessionID: record.Session.ID, VMID: platform.vm.ID, Token: record.Session.WorkerToken}
	workerCall := func(caller, action string, health lifecycle.Health) functionURLResponse {
		meta := &functionURLContext{}
		meta.Authorizer.IAM.UserARN = caller
		meta.HTTP.Method, meta.HTTP.Path = http.MethodPost, "/"
		body, _ := json.Marshal(workerRequest{Action: action, DeviceID: testAssignment.DeviceID, Worker: worker, Health: health})
		result, err := dispatch(event{RequestContext: meta, Body: string(body)})
		if err != nil {
			t.Fatal(err)
		}
		return result.(functionURLResponse)
	}
	if result := workerCall("arn:aws:sts::123456789012:assumed-role/other/test", "claim", lifecycle.Health{}); result.StatusCode != http.StatusForbidden {
		t.Fatal("unrelated IAM role could claim the worker")
	}
	if result := workerCall(workerPrincipal, "repair", lifecycle.Health{}); result.StatusCode != http.StatusBadRequest {
		t.Fatal("a worker request reached the Scheduler repair path")
	}
	if result := workerCall(workerPrincipal, "claim", lifecycle.Health{}); result.StatusCode != http.StatusOK {
		t.Fatalf("expected role could not claim the worker: %d", result.StatusCode)
	}
	full := lifecycle.Health{Sequence: 1, ObservedAtMS: time.Now().UnixMilli(), Heartbeat: true, Navigation: true, Mavlink: true, Video: true}
	if result := workerCall(workerPrincipal, "health", full); result.StatusCode != http.StatusOK {
		t.Fatalf("health report did not reach the claimed session: %d", result.StatusCode)
	}
	stop := event{Topic: commandTopic, PayloadBase64: encodeTestCommand(4, stopID, sessionMetric, record.Session.ID)}
	handler.registry = testRegistry{err: errors.New("rig projection temporarily unavailable")}
	if result, err := dispatch(stop); err != nil || result.(lifecycle.Receipt).Status != lifecycle.Accepted || platform.stops != 1 {
		t.Fatalf("Stop did not reach the assigned VM: %#v %v", result, err)
	}
	ended, err := store.Load(t.Context(), testAssignment.DeviceID)
	if err != nil || ended.Session != nil || ended.Last == nil || ended.Last.Stop.Status != lifecycle.Succeeded {
		t.Fatalf("Stop did not record confirmed termination before repair: %v", err)
	}
	if result := workerCall(workerPrincipal, "grant", lifecycle.Health{}); result.StatusCode != http.StatusForbidden {
		t.Fatal("worker retained its grant after Stop")
	}
	handler.registry = testRegistry{awake: true}
	if _, err := dispatch(event{Action: "repair"}); err != nil {
		t.Fatal(err)
	}
	repaired, err := store.Load(t.Context(), testAssignment.DeviceID)
	if err != nil || repaired.TerminalRevision != ended.TerminalRevision {
		t.Fatalf("repair changed an already confirmed Stop: %v", err)
	}
}
