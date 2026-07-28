package daemon

// DaemonVersion is injected at build time from release/versions/<device>:
//
//	-X .../internal/daemon.DaemonVersion=<version>
//
// Each device type keeps its own release stream, so there is no source literal
// to bump. The fallback only ever reaches a developer build that skipped the
// injection.
var DaemonVersion = "0.0.0-dev"
