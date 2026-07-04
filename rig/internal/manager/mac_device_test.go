package manager

import (
	"fmt"
	"testing"

	"github.com/mparkachov/txing/rig/internal/protocol"
)

// These tests drive the real manager convergence with the exact wire
// payloads txing-mac-daemon publishes (see devices/mac/daemon
// internal/rigadapter golden tests). They pin the mac watch-layer
// contract: birth at REDCON 4, convergence to 3 on simulated power,
// capping below 2 until board-owned evidence exists, and death when
// the daemon stops publishing.

func macInventory() protocol.InventoryDevice {
	return protocol.InventoryDevice{
		ThingName:           "mac-ab12cd",
		ThingType:           "mac",
		Capabilities:        []string{"sparkplug", "power", "board", "mcp", "video"},
		RedconCommandLevels: []uint8{4, 3, 2, 1},
		RedconRules: map[uint8][]string{
			4: {"sparkplug"},
			3: {"sparkplug", "power"},
			2: {"sparkplug", "power", "board", "mcp"},
			1: {"sparkplug", "power", "board", "mcp", "video"},
		},
	}
}

func macDaemonStateJSON(redcon uint8, observedAtMS uint64, seq uint64) []byte {
	power := "false"
	if redcon < 4 {
		power = "true"
	}
	return []byte(fmt.Sprintf(
		`{"schemaVersion":"2.0","adapterId":"dev.txing.mac.Daemon","thingName":"mac-ab12cd","capabilities":{"power":%s,"sparkplug":true},"metrics":{"transportRedcon":{"datatype":"Int32","value":%d}},"observedAtMs":%d,"seq":%d}`,
		power, redcon, observedAtMS, seq,
	))
}

func observeMacDaemonState(t *testing.T, state *DeviceRuntimeState, redcon uint8, observedAtMS uint64, seq uint64) {
	t.Helper()
	decoded, err := protocol.DecodeCapabilityState(macDaemonStateJSON(redcon, observedAtMS, seq))
	if err != nil {
		t.Fatalf("decode mac daemon state: %v", err)
	}
	if err := state.ObserveState(decoded); err != nil {
		t.Fatalf("observe mac daemon state: %v", err)
	}
}

func TestMacDeviceBirthsAtRedcon4AndConvergesTo3(t *testing.T) {
	state := NewDeviceRuntimeState(macInventory())
	now := uint64(1_776_000_000_000)

	observeMacDaemonState(t, state, 4, now, 0)
	publication, err := state.DecidePublication(now)
	if err != nil {
		t.Fatalf("DecidePublication: %v", err)
	}
	if publication.Kind != PublicationBirth || publication.Redcon != 4 {
		t.Fatalf("want DBIRTH redcon 4, got kind=%d redcon=%d", publication.Kind, publication.Redcon)
	}

	observeMacDaemonState(t, state, 3, now+1000, 1)
	publication, err = state.DecidePublication(now + 1000)
	if err != nil {
		t.Fatalf("DecidePublication: %v", err)
	}
	if publication.Kind != PublicationData || publication.Redcon != 3 {
		t.Fatalf("want DDATA redcon 3, got kind=%d redcon=%d", publication.Kind, publication.Redcon)
	}
}

func TestMacDeviceTarget1CapsAt3WithoutBoardEvidence(t *testing.T) {
	state := NewDeviceRuntimeState(macInventory())
	now := uint64(1_776_000_000_000)

	observeMacDaemonState(t, state, 4, now, 0)
	if _, err := state.DecidePublication(now); err != nil {
		t.Fatalf("DecidePublication: %v", err)
	}

	// The daemon accepted a REDCON 1 command: transportRedcon=1 and
	// simulated power on, but no board/mcp/video evidence exists yet.
	observeMacDaemonState(t, state, 1, now+1000, 1)
	publication, err := state.DecidePublication(now + 1000)
	if err != nil {
		t.Fatalf("DecidePublication: %v", err)
	}
	if publication.Kind != PublicationData || publication.Redcon != 3 {
		t.Fatalf("target 1 without board evidence must report redcon 3, got kind=%d redcon=%d", publication.Kind, publication.Redcon)
	}
}

func TestMacDeviceReachesLadderTopWithBoardEvidence(t *testing.T) {
	state := NewDeviceRuntimeState(macInventory())
	now := uint64(1_776_000_000_000)

	observeMacDaemonState(t, state, 1, now, 0)
	if _, err := state.DecidePublication(now); err != nil {
		t.Fatalf("DecidePublication: %v", err)
	}

	// Action-layer retained state (adapterId dev.txing.mac.DaemonBoard,
	// arriving via txings/<thing>/capability/v2/state) raises board-owned
	// capabilities; the manager merges it with the watch-layer state.
	boardState := protocol.CapabilityState{
		SchemaVersion: protocol.SchemaVersion,
		AdapterID:     "dev.txing.mac.DaemonBoard",
		ThingName:     "mac-ab12cd",
		Capabilities:  map[string]bool{"board": true, "mcp": true, "video": false},
		ObservedAtMS:  now + 1000,
		Seq:           0,
	}
	if err := state.ObserveState(boardState); err != nil {
		t.Fatalf("observe board state: %v", err)
	}
	publication, err := state.DecidePublication(now + 1000)
	if err != nil {
		t.Fatalf("DecidePublication: %v", err)
	}
	if publication.Kind != PublicationData || publication.Redcon != 2 {
		t.Fatalf("board+mcp evidence must report redcon 2, got kind=%d redcon=%d", publication.Kind, publication.Redcon)
	}

	boardState.Capabilities = map[string]bool{"board": true, "mcp": true, "video": true}
	boardState.ObservedAtMS = now + 2000
	boardState.Seq = 1
	if err := state.ObserveState(boardState); err != nil {
		t.Fatalf("observe video-ready board state: %v", err)
	}
	publication, err = state.DecidePublication(now + 2000)
	if err != nil {
		t.Fatalf("DecidePublication: %v", err)
	}
	if publication.Kind != PublicationData || publication.Redcon != 1 {
		t.Fatalf("video evidence must report redcon 1, got kind=%d redcon=%d", publication.Kind, publication.Redcon)
	}
}

func TestMacDeviceDiesWhenDaemonStopsPublishing(t *testing.T) {
	state := NewDeviceRuntimeState(macInventory())
	now := uint64(1_776_000_000_000)

	observeMacDaemonState(t, state, 3, now, 0)
	publication, err := state.DecidePublication(now)
	if err != nil {
		t.Fatalf("DecidePublication: %v", err)
	}
	if publication.Kind != PublicationBirth || publication.Redcon != 3 {
		t.Fatalf("want DBIRTH redcon 3, got kind=%d redcon=%d", publication.Kind, publication.Redcon)
	}

	// No further states: after the TTL the sparkplug capability is
	// stale and the device must be projected dead.
	expired := now + StateTTLMS + 1
	publication, err = state.DecidePublication(expired)
	if err != nil {
		t.Fatalf("DecidePublication: %v", err)
	}
	if publication.Kind != PublicationDeath {
		t.Fatalf("want DDEATH after state TTL, got kind=%d", publication.Kind)
	}
}
