package action

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func writeWorkerScript(t *testing.T, body string) (string, string) {
	t.Helper()
	dir := t.TempDir()
	script := filepath.Join(dir, "fake-worker.sh")
	content := "#!/bin/sh\n" + body + "\n"
	if err := os.WriteFile(script, []byte(content), 0o755); err != nil {
		t.Fatalf("write script: %v", err)
	}
	return script, dir
}

func supervisorFor(t *testing.T, script string, dir string, events chan VideoWorkerEvent) *WorkerSupervisor {
	t.Helper()
	config := Config{
		KVSMasterCommand: script,
		BridgeSocketPath: filepath.Join(dir, "bridge.sock"),
	}
	supervisor := NewWorkerSupervisor(config, events, func(string, string) {})
	supervisor.restartBaseDelay = 5 * time.Millisecond
	return supervisor
}

func TestWorkerSupervisorTerminatesWorkerOnStop(t *testing.T) {
	script, dir := writeWorkerScript(t, `trap 'exit 0' TERM
while :; do sleep 0.05; done`)
	events := make(chan VideoWorkerEvent, 8)
	supervisor := supervisorFor(t, script, dir, events)

	supervisor.Start()
	time.Sleep(100 * time.Millisecond)

	stopped := make(chan struct{})
	go func() {
		supervisor.Stop()
		close(stopped)
	}()
	select {
	case <-stopped:
	case <-time.After(3 * time.Second):
		t.Fatal("Stop must SIGTERM the worker and return promptly")
	}

	select {
	case event := <-events:
		t.Fatalf("supervised stop must not report a worker error, got %+v", event)
	default:
	}
}

func TestWorkerSupervisorRestartsAndReportsUnexpectedExit(t *testing.T) {
	script, dir := writeWorkerScript(t, "exit 3")
	events := make(chan VideoWorkerEvent, 8)
	supervisor := supervisorFor(t, script, dir, events)

	supervisor.Start()
	defer supervisor.Stop()

	deadline := time.After(5 * time.Second)
	var received []VideoWorkerEvent
	for len(received) < 2 {
		select {
		case event := <-events:
			received = append(received, event)
		case <-deadline:
			t.Fatalf("expected at least two worker error events (restart), got %d", len(received))
		}
	}
	for _, event := range received {
		if event.Kind != VideoWorkerError {
			t.Fatalf("unexpected event kind: %+v", event)
		}
		if !strings.Contains(event.Detail, "exited unexpectedly") {
			t.Fatalf("error detail must explain the unexpected exit: %+v", event)
		}
	}
}

func TestWorkerSupervisorWritesWorkerLog(t *testing.T) {
	script, dir := writeWorkerScript(t, `echo "worker line"
exit 0`)
	events := make(chan VideoWorkerEvent, 8)
	supervisor := supervisorFor(t, script, dir, events)

	supervisor.Start()
	select {
	case <-events:
	case <-time.After(5 * time.Second):
		t.Fatal("expected the clean-but-unexpected exit to be reported")
	}
	supervisor.Stop()

	logBytes, err := os.ReadFile(filepath.Join(dir, "txing-unit-kvs-master.log"))
	if err != nil {
		t.Fatalf("worker log must exist: %v", err)
	}
	if !strings.Contains(string(logBytes), "worker line") {
		t.Fatalf("worker output must land in the log file: %q", string(logBytes))
	}
}
