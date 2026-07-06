package macdaemon

import (
	"bufio"
	"context"
	"encoding/json"
	"net"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/mparkachov/txing/devices/mac/daemon/internal/macconfig"
	"github.com/mparkachov/txing/devices/mac/daemon/internal/rigadapter"
)

// testBroker speaks the rig IPC frame protocol (newline-delimited JSON
// over a Unix socket) like the txing-sparkplug-manager broker: it
// records publishes and delivers retained topics on subscribe.
type testBroker struct {
	listener net.Listener

	mu        sync.Mutex
	retained  map[string][]byte
	conns     []net.Conn
	published []rigadapter.Frame
	notify    chan rigadapter.Frame
}

func newTestBroker(t *testing.T) (*testBroker, string) {
	t.Helper()
	// Unix socket paths are limited to ~104 bytes on macOS; t.TempDir()
	// paths exceed that, so create a short-lived directory under /tmp.
	socketDir, err := os.MkdirTemp("/tmp", "txing-mac-test")
	if err != nil {
		t.Fatalf("mkdtemp: %v", err)
	}
	t.Cleanup(func() { _ = os.RemoveAll(socketDir) })
	socketPath := filepath.Join(socketDir, "rig-ipc.sock")
	listener, err := net.Listen("unix", socketPath)
	if err != nil {
		t.Fatalf("listen: %v", err)
	}
	broker := &testBroker{
		listener: listener,
		retained: map[string][]byte{},
		notify:   make(chan rigadapter.Frame, 64),
	}
	go broker.acceptLoop()
	t.Cleanup(func() { _ = listener.Close() })
	return broker, socketPath
}

func (b *testBroker) acceptLoop() {
	for {
		conn, err := b.listener.Accept()
		if err != nil {
			return
		}
		b.mu.Lock()
		b.conns = append(b.conns, conn)
		b.mu.Unlock()
		go b.handle(conn)
	}
}

func (b *testBroker) handle(conn net.Conn) {
	scanner := bufio.NewScanner(conn)
	scanner.Buffer(make([]byte, 0, 64*1024), 4*1024*1024)
	encoder := json.NewEncoder(conn)
	for scanner.Scan() {
		var frame rigadapter.Frame
		if err := json.Unmarshal(scanner.Bytes(), &frame); err != nil {
			return
		}
		switch frame.Type {
		case "subscribe":
			b.mu.Lock()
			for topic, payload := range b.retained {
				if topicMatchesFilter(frame.Topic, topic) {
					_ = encoder.Encode(rigadapter.Frame{Type: "publish", Topic: topic, Payload: payload})
				}
			}
			b.mu.Unlock()
		case "publish", "publish-retained":
			b.mu.Lock()
			if frame.Type == "publish-retained" {
				b.retained[frame.Topic] = frame.Payload
			}
			b.published = append(b.published, frame)
			b.mu.Unlock()
			b.notify <- frame
		}
	}
}

func (b *testBroker) setRetained(topic string, payload []byte) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.retained[topic] = payload
}

func (b *testBroker) sendToClients(topic string, payload []byte) {
	b.mu.Lock()
	conns := append([]net.Conn(nil), b.conns...)
	b.mu.Unlock()
	frame := rigadapter.Frame{Type: "publish", Topic: topic, Payload: payload}
	for _, conn := range conns {
		encoder := json.NewEncoder(conn)
		_ = encoder.Encode(frame)
	}
}

func (b *testBroker) waitForFrame(t *testing.T, match func(rigadapter.Frame) bool) rigadapter.Frame {
	t.Helper()
	deadline := time.After(5 * time.Second)
	for {
		select {
		case frame := <-b.notify:
			if match(frame) {
				return frame
			}
		case <-deadline:
			t.Fatal("timed out waiting for IPC frame")
		}
	}
}

func topicMatchesFilter(filter string, topic string) bool {
	if filter == topic {
		return true
	}
	filterParts := strings.Split(filter, "/")
	topicParts := strings.Split(topic, "/")
	for index, filterPart := range filterParts {
		if filterPart == "#" {
			return index == len(filterParts)-1
		}
		if index >= len(topicParts) {
			return false
		}
		if filterPart != "+" && filterPart != topicParts[index] {
			return false
		}
	}
	return len(filterParts) == len(topicParts)
}

func TestRunSessionBirthsFromRetainedInventoryAndHandlesCommand(t *testing.T) {
	broker, socketPath := newTestBroker(t)

	inventory := macInventory(macDevice("mac-ab12cd"))
	inventoryPayload, err := json.Marshal(inventory)
	if err != nil {
		t.Fatalf("marshal inventory: %v", err)
	}
	broker.setRetained(rigadapter.InventoryTopic, inventoryPayload)

	cfg := macconfig.Config{
		ThingID:           "mac-ab12cd",
		IPCSocket:         socketPath,
		InitialRedcon:     4,
		StateInterval:     time.Hour,
		HeartbeatInterval: time.Hour,
	}
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	done := make(chan error, 1)
	go func() {
		done <- Run(ctx, cfg, nil, func(string, string) {})
	}()

	// Retained inventory must birth the device: a retained state with
	// power=false and transportRedcon=4 appears without any command.
	stateTopic := rigadapter.CapabilityStateTopicPrefix + "/mac-ab12cd/" + AdapterID
	stateFrame := broker.waitForFrame(t, func(frame rigadapter.Frame) bool {
		return frame.Topic == stateTopic
	})
	if stateFrame.Type != "publish-retained" {
		t.Fatalf("state must be retained, got %s", stateFrame.Type)
	}
	var state rigadapter.CapabilityState
	if err := json.Unmarshal(stateFrame.Payload, &state); err != nil {
		t.Fatalf("decode state: %v", err)
	}
	if state.Capabilities[PowerCapability] || state.Capabilities[SparkplugCapability] != true {
		t.Fatalf("unexpected initial state: %+v", state)
	}

	// A REDCON 3 command over the wire yields accepted, updated
	// retained state with power=true, and succeeded.
	commandTopic := rigadapter.CapabilityCommandTopicPrefix + "/mac-ab12cd"
	commandPayload, err := json.Marshal(command("mac-ab12cd", 3))
	if err != nil {
		t.Fatalf("marshal command: %v", err)
	}
	broker.sendToClients(commandTopic, commandPayload)

	resultTopic := rigadapter.CapabilityCommandResultTopicPrefix + "/mac-ab12cd/" + AdapterID
	var statuses []string
	sawPoweredState := false
	for len(statuses) < 2 {
		frame := broker.waitForFrame(t, func(frame rigadapter.Frame) bool {
			return frame.Topic == resultTopic || frame.Topic == stateTopic
		})
		if frame.Topic == stateTopic {
			var updated rigadapter.CapabilityState
			if err := json.Unmarshal(frame.Payload, &updated); err != nil {
				t.Fatalf("decode updated state: %v", err)
			}
			if updated.Capabilities[PowerCapability] {
				sawPoweredState = true
			}
			continue
		}
		var result rigadapter.CapabilityCommandResult
		if err := json.Unmarshal(frame.Payload, &result); err != nil {
			t.Fatalf("decode result: %v", err)
		}
		statuses = append(statuses, result.Status)
	}
	if statuses[0] != rigadapter.CommandAccepted || statuses[1] != rigadapter.CommandSucceeded {
		t.Fatalf("unexpected result order: %v", statuses)
	}
	if !sawPoweredState {
		t.Fatal("command must publish a powered retained state")
	}

	cancel()
	// Shutdown must publish an offline state (sparkplug=false) so the
	// rig projects DDEATH immediately instead of waiting for the TTL.
	offlineFrame := broker.waitForFrame(t, func(frame rigadapter.Frame) bool {
		if frame.Topic != stateTopic {
			return false
		}
		var offline rigadapter.CapabilityState
		if err := json.Unmarshal(frame.Payload, &offline); err != nil {
			return false
		}
		return !offline.Capabilities[SparkplugCapability]
	})
	if offlineFrame.Type != "publish-retained" {
		t.Fatalf("offline state must be retained, got %s", offlineFrame.Type)
	}
	select {
	case err := <-done:
		if err != nil {
			t.Fatalf("Run returned error: %v", err)
		}
	case <-time.After(5 * time.Second):
		t.Fatal("Run did not stop after context cancel")
	}
}
