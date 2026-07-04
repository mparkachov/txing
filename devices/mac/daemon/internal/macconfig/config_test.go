package macconfig

import (
	"os"
	"path/filepath"
	"testing"
	"time"
)

func writeConfig(t *testing.T, content string) string {
	t.Helper()
	dir := t.TempDir()
	if err := os.WriteFile(filepath.Join(dir, "daemon.env"), []byte(content), 0o600); err != nil {
		t.Fatalf("write daemon.env: %v", err)
	}
	return dir
}

func TestLoadReadsEnvFileWithDefaults(t *testing.T) {
	dir := writeConfig(t, `
# comment
TXING_THING_ID=mac-ab12cd
TXING_RIG_IPC_SOCKET="/tmp/txing-rig/rig-ipc.sock"
`)
	cfg, err := Load(dir)
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if cfg.ThingID != "mac-ab12cd" {
		t.Fatalf("thing id: %q", cfg.ThingID)
	}
	if cfg.IPCSocket != "/tmp/txing-rig/rig-ipc.sock" {
		t.Fatalf("ipc socket: %q", cfg.IPCSocket)
	}
	if cfg.InitialRedcon != 4 {
		t.Fatalf("initial redcon default: %d", cfg.InitialRedcon)
	}
	if cfg.StateInterval != 30*time.Second || cfg.HeartbeatInterval != 10*time.Second {
		t.Fatalf("interval defaults: %v %v", cfg.StateInterval, cfg.HeartbeatInterval)
	}
}

func TestProcessEnvironmentTakesPrecedenceOverFile(t *testing.T) {
	dir := writeConfig(t, `
TXING_THING_ID=mac-from-file
TXING_MAC_INITIAL_REDCON=4
`)
	t.Setenv("TXING_THING_ID", "mac-from-env")
	t.Setenv("TXING_MAC_INITIAL_REDCON", "3")
	cfg, err := Load(dir)
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if cfg.ThingID != "mac-from-env" {
		t.Fatalf("process env must win: %q", cfg.ThingID)
	}
	if cfg.InitialRedcon != 3 {
		t.Fatalf("initial redcon from env: %d", cfg.InitialRedcon)
	}
}

func TestLoadSupportsExportPrefixAndIntervals(t *testing.T) {
	dir := writeConfig(t, `
export TXING_THING_ID=mac-ab12cd
export TXING_MAC_STATE_INTERVAL_SECONDS=45
export TXING_MAC_HEARTBEAT_INTERVAL_MS=2500
`)
	cfg, err := Load(dir)
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if cfg.StateInterval != 45*time.Second || cfg.HeartbeatInterval != 2500*time.Millisecond {
		t.Fatalf("intervals: %v %v", cfg.StateInterval, cfg.HeartbeatInterval)
	}
}

func TestLoadRejectsMissingOrInvalidThingID(t *testing.T) {
	if _, err := Load(writeConfig(t, "TXING_MAC_INITIAL_REDCON=4\n")); err == nil {
		t.Fatal("missing thing id must fail")
	}
	if _, err := Load(writeConfig(t, "TXING_THING_ID=bad/thing\n")); err == nil {
		t.Fatal("thing id with separators must fail")
	}
	if _, err := Load(writeConfig(t, "TXING_THING_ID=mac-a\nTXING_MAC_INITIAL_REDCON=5\n")); err == nil {
		t.Fatal("invalid initial redcon must fail")
	}
}
