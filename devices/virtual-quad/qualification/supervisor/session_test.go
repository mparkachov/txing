package main

import (
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
)

func testAssignment(now time.Time) sessionAssignment {
	return sessionAssignment{
		DeviceID: "virtual-quad-test", TownID: "town-test", RigID: "cloud-test",
		SessionID: "session-1", Token: "token-1",
		URL:                "https://test123.lambda-url.eu-central-1.on.aws/",
		ShutdownDeadlineMS: now.Add(runLimit).UnixMilli(),
	}
}

func TestSessionAssignmentChecksControllerAndDeadline(t *testing.T) {
	now := time.Now()
	assignment := testAssignment(now)
	if !assignment.valid(now) {
		t.Fatal("rejected valid assignment")
	}
	for _, endpoint := range []string{
		"http://test123.lambda-url.eu-central-1.on.aws/",
		"https://user@test123.lambda-url.eu-central-1.on.aws/",
		"https://test123.lambda-url.eu-central-1.on.aws:443/",
		"https://test123.lambda-url.us-east-1.on.aws/",
		"https://test123.lambda-url.eu-central-1.on.aws.evil.example/",
		"https://test123.lambda-url.eu-central-1.on.aws/path",
		"https://test123.lambda-url.eu-central-1.on.aws/?",
	} {
		assignment.URL = endpoint
		if assignment.valid(now) {
			t.Errorf("accepted unsafe controller endpoint %q", endpoint)
		}
	}
	assignment = testAssignment(now)
	for _, cutoff := range []time.Time{now, now.Add(runLimit + 3*time.Second)} {
		assignment.ShutdownDeadlineMS = cutoff.UnixMilli()
		if assignment.valid(now) {
			t.Errorf("accepted deadline %s", cutoff)
		}
	}
}

type sessionTransport func(*http.Request) (*http.Response, error)

func (transport sessionTransport) RoundTrip(req *http.Request) (*http.Response, error) {
	return transport(req)
}

func TestSignedWorkerRequestBindsClaimAndCutoff(t *testing.T) {
	assignment := testAssignment(time.Now())
	client := newSessionClient(assignment, "vm-test", aws.Credentials{
		AccessKeyID: "fakeKey", SecretAccessKey: "fakeSecret", SessionToken: "fakeToken",
	})
	statusCode := http.StatusOK
	cutoff := assignment.ShutdownDeadlineMS
	attempts := 0
	client.http.Transport = sessionTransport(func(req *http.Request) (*http.Response, error) {
		attempts++
		if req.Method != http.MethodPost || req.URL.String() != assignment.URL ||
			!strings.Contains(req.Header.Get("Authorization"), "/eu-central-1/lambda/aws4_request") ||
			len(req.Header.Get("X-Amz-Content-Sha256")) != 64 ||
			req.Header.Get("X-Amz-Security-Token") != "fakeToken" {
			t.Fatal("request missed the IAM signature or controller endpoint")
		}
		var body struct {
			Action   string        `json:"action"`
			DeviceID string        `json:"deviceId"`
			Worker   sessionWorker `json:"worker"`
		}
		if err := json.NewDecoder(req.Body).Decode(&body); err != nil || body.Action != "claim" ||
			body.DeviceID != assignment.DeviceID || body.Worker != client.worker {
			t.Fatalf("claim request did not bind the worker to its assignment: %v", err)
		}
		data := fmt.Sprintf(`{"granted":true,"shutdownDeadlineMs":%d}`, cutoff)
		return &http.Response{StatusCode: statusCode, Body: io.NopCloser(strings.NewReader(data))}, nil
	})
	if status := client.claim(t.Context()); status != http.StatusOK || attempts != 1 {
		t.Fatalf("valid claim returned %d after %d calls", status, attempts)
	}
	statusCode = http.StatusForbidden
	if status := client.claim(t.Context()); status != http.StatusForbidden || attempts != 2 {
		t.Fatalf("denied claim returned %d after %d calls", status, attempts)
	}
	statusCode = http.StatusOK
	cutoff++
	if status := client.claim(t.Context()); status != http.StatusServiceUnavailable {
		t.Fatalf("accepted changed cutoff with status %d", status)
	}
}

func TestHealthDoesNotRefreshStaleEvidence(t *testing.T) {
	path := filepath.Join(t.TempDir(), "health.json")
	now := time.Now()
	for _, observed := range []time.Time{now.Add(-time.Second), now.Add(-3 * time.Second), now.Add(time.Second)} {
		data := fmt.Sprintf(`{"observedAtMs":%d,"heartbeat":true,"navigation":true,"mavlink":true,"video":true}`, observed.UnixMilli())
		if err := os.WriteFile(path, []byte(data), 0600); err != nil {
			t.Fatal(err)
		}
		got := readSessionHealth(path, now, 7)
		want := sessionHealth{Sequence: 7, ObservedAtMS: now.UnixMilli()}
		if observed.Equal(now.Add(-time.Second)) {
			want = sessionHealth{7, observed.UnixMilli(), true, true, true, true}
		}
		if got != want {
			t.Errorf("health at %s = %+v, want %+v", observed, got, want)
		}
	}
}
