package lambdalog

import (
	"bytes"
	"encoding/json"
	"testing"
	"time"
)

func TestWriteColdStartUsesStructuredLambdaLogFields(t *testing.T) {
	var output bytes.Buffer
	now := time.Date(2026, 5, 25, 12, 0, 0, 123456789, time.UTC)

	if err := WriteColdStart(&output, "txing-cloud-rig-lambda", "1.2.3", now); err != nil {
		t.Fatalf("write cold start log: %v", err)
	}

	var payload map[string]interface{}
	if err := json.Unmarshal(output.Bytes(), &payload); err != nil {
		t.Fatalf("decode cold start log: %v", err)
	}
	if payload["timestamp"] != "2026-05-25T12:00:00.123456789Z" {
		t.Fatalf("unexpected timestamp: %#v", payload["timestamp"])
	}
	if payload["level"] != "info" {
		t.Fatalf("unexpected level: %#v", payload["level"])
	}
	if payload["message"] != "lambda cold start" {
		t.Fatalf("unexpected message: %#v", payload["message"])
	}
	if payload["service"] != "txing-cloud-rig-lambda" {
		t.Fatalf("unexpected service: %#v", payload["service"])
	}
	if payload["version"] != "1.2.3" {
		t.Fatalf("unexpected version: %#v", payload["version"])
	}
	if payload["cold_start"] != true {
		t.Fatalf("unexpected cold_start: %#v", payload["cold_start"])
	}
}
