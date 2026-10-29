package witness

import (
	"context"
	"encoding/json"
	"errors"
	"reflect"
	"testing"
	"time"
)

const testWatchImage = "arn:aws:lambda:eu-central-1:123456789012:microvm-image:agent-test"

type fakeWatch struct {
	things            []string
	shadows           map[string][][]byte
	readErrors        map[string]bool
	pages             map[string][]WatchMicrovm
	next              map[string]string
	pageErrors        map[string]bool
	vms               map[string]WatchMicrovm
	stopErrors        map[string]bool
	stops, operations []string
}

func (f *fakeWatch) AgentThings(context.Context) ([]string, error) { return f.things, nil }
func (f *fakeWatch) AgentShadow(_ context.Context, thing string) ([]byte, bool, error) {
	if f.readErrors[thing] {
		return nil, false, errors.New("read failed")
	}
	sequence := f.shadows[thing]
	if len(sequence) == 0 {
		return nil, false, nil
	}
	if len(sequence) > 1 {
		f.shadows[thing] = sequence[1:]
	}
	return sequence[0], true, nil
}
func (f *fakeWatch) MicrovmPage(_ context.Context, image, token string) ([]WatchMicrovm, string, error) {
	f.operations = append(f.operations, "page:"+token)
	if image != testWatchImage || f.pageErrors[token] {
		return nil, "", errors.New("page failed")
	}
	return f.pages[token], f.next[token], nil
}
func (f *fakeWatch) Microvm(_ context.Context, id string) (WatchMicrovm, error) {
	vm, ok := f.vms[id]
	if !ok {
		return vm, errors.New("VM missing")
	}
	return vm, nil
}
func (f *fakeWatch) TerminateMicrovm(_ context.Context, id string) error {
	f.operations = append(f.operations, "stop:"+id)
	f.stops = append(f.stops, id)
	if f.stopErrors[id] {
		return errors.New("stop failed")
	}
	return nil
}
func watchBody(state, id string, stop, deadline int64) []byte {
	phase := "stopping"
	if state == "running" {
		phase = "running"
	}
	if state == "starting" {
		phase = "reserved"
	}
	body, _ := json.Marshal(map[string]any{"version": 1, "state": map[string]any{"reported": map[string]any{
		"lifecycle": map[string]any{"state": state}, "run": map[string]any{"id": "run-1", "microvmId": id},
		"activation": map[string]any{"id": "activation-1", "startedAt": int64(100), "deadline": deadline},
		"controller": map[string]any{"active": true, "runPhase": phase, "runActivationId": "activation-1", "stopRequestedAt": stop},
	}}})
	return body
}
func watchFixture() (*fakeWatch, AgentWatcher) {
	vm := WatchMicrovm{ID: "vm-1", Image: testWatchImage, State: "RUNNING", StartedAt: time.Unix(100, 0)}
	f := &fakeWatch{things: []string{"tbot-test"}, shadows: map[string][][]byte{"tbot-test": {watchBody("stopping", "vm-1", 200, 3100)}},
		pages: map[string][]WatchMicrovm{"": {vm}}, next: map[string]string{}, pageErrors: map[string]bool{},
		vms: map[string]WatchMicrovm{"vm-1": vm}, readErrors: map[string]bool{}, stopErrors: map[string]bool{}}
	return f, AgentWatcher{AWS: f, Image: testWatchImage, Now: func() time.Time { return time.Unix(320, 0) }}
}

func TestAgentWatchGraceAndExpiry(t *testing.T) {
	for _, tc := range []struct {
		name, state         string
		now, stop, deadline int64
		want                int
	}{
		{"before grace", "stopping", 319, 200, 3100, 0}, {"at grace", "stopping", 320, 200, 3100, 1},
		{"running", "running", 320, 0, 3100, 0}, {"starting", "starting", 320, 0, 3100, 0},
		{"expired before grace", "running", 3219, 0, 3100, 0}, {"expired without controller", "running", 3220, 0, 3100, 1},
		{"clock reversal", "stopping", 199, 200, 3100, 0}, {"missing stop time", "stopping", 320, 0, 3100, 0},
		{"error", "error", 320, 200, 3100, 1}, {"stopped", "stopped", 320, 200, 3100, 1},
	} {
		t.Run(tc.name, func(t *testing.T) {
			f, w := watchFixture()
			w.Now = func() time.Time { return time.Unix(tc.now, 0) }
			f.shadows["tbot-test"] = [][]byte{watchBody(tc.state, "vm-1", tc.stop, tc.deadline)}
			result, err := w.Sweep(context.Background())
			if err != nil || result.Requested != tc.want || len(f.stops) != tc.want {
				t.Fatalf("result=%+v err=%v stops=%v", result, err, f.stops)
			}
			if tc.want > 0 && !result.Incomplete {
				t.Fatal("termination request claimed terminal confirmation")
			}
		})
	}
}

func TestAgentWatchRechecksAndScopes(t *testing.T) {
	for _, tc := range []struct {
		name   string
		change func(*fakeWatch)
	}{
		{"recovered", func(f *fakeWatch) {
			f.shadows["tbot-test"] = append(f.shadows["tbot-test"], watchBody("running", "vm-1", 0, 3100))
		}},
		{"new assignment", func(f *fakeWatch) {
			f.shadows["tbot-test"] = append(f.shadows["tbot-test"], watchBody("stopping", "vm-2", 100, 3100))
		}},
		{"other image", func(f *fakeWatch) { vm := f.vms["vm-1"]; vm.Image = "other"; f.vms["vm-1"] = vm }},
		{"other VM", func(f *fakeWatch) { vm := f.vms["vm-1"]; vm.ID = "vm-2"; f.vms["vm-1"] = vm }},
		{"already terminal", func(f *fakeWatch) { vm := f.vms["vm-1"]; vm.State = "TERMINATED"; f.vms["vm-1"] = vm }},
		{"duplicate claim", func(f *fakeWatch) {
			f.things = append(f.things, "other")
			f.shadows["other"] = [][]byte{watchBody("running", "vm-1", 0, 3100)}
		}},
	} {
		t.Run(tc.name, func(t *testing.T) {
			f, w := watchFixture()
			tc.change(f)
			w.Sweep(context.Background())
			if len(f.stops) > 0 {
				t.Fatal(f.stops)
			}
		})
	}
}

func TestAgentWatchOrphansAndPartialReads(t *testing.T) {
	f, w := watchFixture()
	f.shadows = map[string][][]byte{}
	result, err := w.Sweep(context.Background())
	if err != nil || result.Requested != 1 {
		t.Fatalf("%+v %v", result, err)
	}
	f, w = watchFixture()
	f.shadows = map[string][][]byte{}
	vm := f.vms["vm-1"]
	vm.StartedAt = time.Unix(250, 0)
	f.vms["vm-1"] = vm
	result, err = w.Sweep(context.Background())
	if err != nil || result.Requested != 0 {
		t.Fatalf("young orphan: %+v %v", result, err)
	}
	f, w = watchFixture()
	f.readErrors["tbot-test"] = true
	result, err = w.Sweep(context.Background())
	if err == nil || result.Requested != 0 || !result.Incomplete {
		t.Fatalf("unreadable: %+v %v", result, err)
	}
	f, w = watchFixture()
	f.things = append(f.things, "unreadable")
	f.readErrors["unreadable"] = true
	result, err = w.Sweep(context.Background())
	if err == nil || result.Requested != 1 {
		t.Fatalf("known off blocked: %+v %v", result, err)
	}
	f, w = watchFixture()
	f.shadows["tbot-test"] = [][]byte{[]byte(`{"version":2}`)}
	result, err = w.Sweep(context.Background())
	if err == nil || result.Requested != 0 {
		t.Fatalf("malformed: %+v %v", result, err)
	}
	// An inventory candidate adopted after the first read is protected.
	f, w = watchFixture()
	f.shadows["tbot-test"] = [][]byte{watchBody("starting", "", 0, 3100), watchBody("running", "vm-1", 0, 3100)}
	result, err = w.Sweep(context.Background())
	if err != nil || result.Requested != 0 {
		t.Fatalf("adopted: %+v %v", result, err)
	}
	// A current replacement does not protect an old unidentified instance.
	f, w = watchFixture()
	f.shadows["tbot-test"] = [][]byte{watchBody("running", "vm-2", 0, 3100)}
	result, err = w.Sweep(context.Background())
	if err != nil || !reflect.DeepEqual(f.stops, []string{"vm-1"}) {
		t.Fatalf("superseded orphan: %+v %v stops=%v", result, err, f.stops)
	}
}

func TestAgentWatchPagesAndRetry(t *testing.T) {
	f, w := watchFixture()
	vm := f.vms["vm-1"]
	vm.ID = "vm-2"
	f.vms[vm.ID] = vm
	f.next[""] = "page2"
	f.pages["page2"] = []WatchMicrovm{vm}
	f.stopErrors["vm-1"] = true
	result, err := w.Sweep(context.Background())
	if err == nil || !result.Incomplete || !reflect.DeepEqual(f.stops, []string{"vm-1", "vm-2"}) ||
		!reflect.DeepEqual(f.operations, []string{"page:", "stop:vm-1", "page:page2", "stop:vm-2"}) {
		t.Fatalf("%+v %v %v", result, err, f.operations)
	}
	f, w = watchFixture()
	f.next[""] = "page2"
	f.pageErrors["page2"] = true
	result, err = w.Sweep(context.Background())
	if err == nil || result.Requested != 1 {
		t.Fatalf("later page erased progress: %+v %v", result, err)
	}
	f, w = watchFixture()
	f.next[""] = "A"
	f.next["A"] = "B"
	f.next["B"] = "A"
	result, err = w.Sweep(context.Background())
	if err == nil || result.Requested != 1 {
		t.Fatalf("token cycle: %+v %v", result, err)
	}
	f, w = watchFixture()
	f.pageErrors[""] = true
	result, err = w.Sweep(context.Background())
	if err == nil || result.Requested != 1 {
		t.Fatalf("inventory failure hid a known off assignment: %+v %v", result, err)
	}
	f, w = watchFixture()
	f.pages[""] = nil
	result, err = w.Sweep(context.Background())
	if err != nil || result.Requested != 1 {
		t.Fatalf("inventory omission hid a known off assignment: %+v %v", result, err)
	}
}

func TestAgentWatchProjectionIsolation(t *testing.T) {
	f, w := watchFixture()
	f.readErrors["tbot-test"] = true
	projection := &fakeAWS{}
	w.Projection = projection
	payload := encodePayload(ptr(int64(1710000000000)), ptr(int64(1)), encodeMetric("redcon", ptr(int64(1)), nil, nil, nil, nil, false))
	result, err := w.Handle(context.Background(), map[string]any{"mqttTopic": "spBv1.0/town/DBIRTH/rig/tbot-test", "payloadBase64": payload, "observedAt": int64(1)})
	if err != nil || result["status"] != "ok" || result["watchStatus"] != "incomplete" || len(projection.updates) == 0 {
		t.Fatalf("projection was blocked: %v %v", result, err)
	}
	w.Image = ""
	result, err = w.Handle(context.Background(), map[string]any{"source": AgentWatchSource})
	if err != nil || result["status"] != "watch-disabled" {
		t.Fatalf("%v %v", result, err)
	}
}

func TestAgentWatchAfterUnchangedProjection(t *testing.T) {
	f, w := watchFixture()
	w.Projection = &fakeAWS{shadow: map[string]any{"state": map[string]any{"reported": map[string]any{"payload": map[string]any{"metrics": map[string]any{"redcon": float64(1)}}}}}}
	payload := encodePayload(ptr(int64(1710000000000)), ptr(int64(1)), encodeMetric("redcon", ptr(int64(1)), nil, nil, nil, nil, false))
	result, err := w.Handle(context.Background(), map[string]any{"mqttTopic": "spBv1.0/town/DDATA/rig/tbot-test", "payloadBase64": payload, "observedAt": int64(1)})
	if err != nil || result["status"] != "ok" || len(f.stops) != 1 {
		t.Fatalf("unchanged projection skipped watch: %v %v %v", result, err, f.stops)
	}
}
