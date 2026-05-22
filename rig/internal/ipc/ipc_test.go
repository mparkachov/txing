package ipc

import (
	"context"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestTopicMatchesMQTTWildcards(t *testing.T) {
	cases := []struct {
		filter string
		topic  string
		match  bool
	}{
		{"dev/txing/rig/v2/#", "dev/txing/rig/v2/inventory", true},
		{"dev/txing/rig/v2/capability/command/+", "dev/txing/rig/v2/capability/command/unit-1", true},
		{"dev/txing/rig/v2/capability/command/+", "dev/txing/rig/v2/capability/command/unit-1/extra", false},
		{"a/b", "a/b", true},
		{"a/b", "a/c", false},
	}
	for _, tc := range cases {
		if got := topicMatches(tc.filter, tc.topic); got != tc.match {
			t.Fatalf("topicMatches(%q, %q) = %t, want %t", tc.filter, tc.topic, got, tc.match)
		}
	}
}

func TestBrokerFansOutAndReplaysRetainedMessages(t *testing.T) {
	dir := shortSocketTempDir(t)
	socketPath := filepath.Join(dir, "ipc.sock")
	broker := NewBroker(socketPath)
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	errs := make(chan error, 1)
	go func() {
		errs <- broker.Serve(ctx)
	}()
	waitForDial(t, socketPath)

	publisher, err := Dial(context.Background(), socketPath)
	if err != nil {
		t.Fatal(err)
	}
	defer publisher.Close()
	if err := publisher.PublishRetained("dev/txing/rig/v2/inventory", []byte("inventory")); err != nil {
		t.Fatal(err)
	}

	subscriber, err := Dial(context.Background(), socketPath)
	if err != nil {
		t.Fatal(err)
	}
	defer subscriber.Close()
	if err := subscriber.Subscribe("dev/txing/rig/v2/#"); err != nil {
		t.Fatal(err)
	}
	message, err := subscriber.Receive()
	if err != nil {
		t.Fatal(err)
	}
	if message.Topic != "dev/txing/rig/v2/inventory" || string(message.Payload) != "inventory" {
		t.Fatalf("retained message = %#v", message)
	}

	if err := publisher.Publish("dev/txing/rig/v2/capability/state/unit-1/dev.txing.rig.BleConnectivity", []byte("state")); err != nil {
		t.Fatal(err)
	}
	message, err = subscriber.Receive()
	if err != nil {
		t.Fatal(err)
	}
	if string(message.Payload) != "state" {
		t.Fatalf("message = %#v", message)
	}

	cancel()
	select {
	case err := <-errs:
		if err != nil {
			t.Fatal(err)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("broker did not stop")
	}
}

func shortSocketTempDir(t *testing.T) string {
	t.Helper()
	for _, root := range []string{"/tmp", os.TempDir()} {
		if root == "" {
			continue
		}
		if stat, err := os.Stat(root); err != nil || !stat.IsDir() {
			continue
		}
		dir, err := os.MkdirTemp(root, "txing-ipc-test.")
		if err != nil {
			continue
		}
		t.Cleanup(func() {
			_ = os.RemoveAll(dir)
		})
		return dir
	}
	return t.TempDir()
}

func waitForDial(t *testing.T, socketPath string) {
	t.Helper()
	deadline := time.Now().Add(2 * time.Second)
	for time.Now().Before(deadline) {
		ctx, cancel := context.WithTimeout(context.Background(), 100*time.Millisecond)
		client, err := Dial(ctx, socketPath)
		cancel()
		if err == nil {
			_ = client.Close()
			return
		}
		time.Sleep(20 * time.Millisecond)
	}
	t.Fatal("broker did not start")
}
