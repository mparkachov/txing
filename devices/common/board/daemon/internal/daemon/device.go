package daemon

// DeviceType is the board device type this binary was built for, injected at
// build time from the device profile:
//
//	-X .../internal/daemon.DeviceType=<device>
//
// One implementation serves every board device type, so every device-specific
// identifier below is derived from it rather than duplicated per device. The
// fallback only ever reaches a developer build that skipped the injection.
var DeviceType = "board"

// Derived device identity. These were per-device constants before the board
// components were consolidated onto one implementation; the values they produce
// are unchanged, so deployed socket paths, config directories, and the adapter
// id stay exactly as the board runbook documents them.
var (
	AdapterID                     = "dev.txing." + DeviceType + ".Daemon"
	DaemonBinaryName              = "txing-" + DeviceType + "-daemon"
	KVSMasterBinaryName           = "txing-board-kvs-master"
	HardwareWorkerBinaryName      = "txing-" + DeviceType + "-hardware-worker"
	DefaultConfigSubdir           = "txing/" + DeviceType + "-daemon"
	DefaultKVSMasterCommand       = KVSMasterBinaryName
	DefaultMCPWebRTCSocketPath    = "/run/" + DaemonBinaryName + "/mcp-webrtc.sock"
	DefaultBoardVideoBridgeSocket = "/run/" + DaemonBinaryName + "/board-video-bridge.sock"
	DefaultMavlinkBridgeSocket    = "/run/" + DaemonBinaryName + "/mavlink-bridge.sock"
	DefaultMavlinkServiceSocket   = "/run/txing-" + DeviceType + "-mavlink/" + DeviceType + "-mavlink.sock"
	DefaultHardwareSocketPath     = "/run/" + HardwareWorkerBinaryName + "/" + DeviceType + "-hardware.sock"
)
