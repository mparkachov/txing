# Rust Debug Device

`rust-debug` is a rig-side Rust experiment for the current BLE debug wake/sleep
contract. It intentionally does not contain MCU firmware, Python projects, or
`uv` environments.

The Rust rig has two BLE backends:

- `btleplug`: real BLE central/client path for macOS CoreBluetooth and Linux
  BlueZ.
- simulator: deterministic fake BLE peripheral for fast tests and overnight
  matrix simulation.

The BLE protocol matches the current `ble-debug` GATT surface:

```text
service      f6b4b000-7b32-4d2d-9f4b-4ff0a2b8f100
command      f6b4b001-7b32-4d2d-9f4b-4ff0a2b8f100
state        f6b4b002-7b32-4d2d-9f4b-4ff0a2b8f100
```

Command payloads are `<BB>` or `<BBHHH>` and state payloads are `<BBBH>`.
REDCON `3` means wakeup state and REDCON `4` means sleep state.

## Commands

Fast simulated tests:

```sh
just rust-debug::rig::sim-test
cargo test --manifest-path devices/rust-debug/rig/Cargo.toml
```

Simulated overnight matrix:

```sh
just rust-debug::rig::sim-overnight
```

Physical BLE cycle test:

```sh
just rust-debug::rig::test
just rust-debug::rig::test 60 weather-q8zbgb --conn-profile stable-100-0-20
```

`just rust-debug::rig::test N` uses the requested `--conn-profile` values as
test suites and generates `N` ignored Rust test cases per suite during the Cargo
build. Each generated test runs one physical BLE wake/sleep cycle, serially. The
focused physical test default is a 50 second cycle (`wakeSeconds=30`,
`cycleSeconds=50`) to stay below Rust's 60 second long-test warning in normal
passing cases. The recipe runs only the library test target and uses terse
captured test output. Detailed cycle logs are appended to one run-level
`cycle.log` under `/tmp/rust-debug-rig-test-results/`, and the recipe prints
that exact path before the tests start. For direct CLI debugging without the
Rust test harness, use:

```sh
just rust-debug::rig::run-test
```

Physical BLE overnight matrix:

```sh
just rust-debug::rig::overnight
```

Physical BLE commands attach to the host Bluetooth controller. On macOS, the
terminal or app running the command needs Bluetooth permission. On Linux, BlueZ
and DBus access must be available.

The AWS Greengrass Component SDK crate builds bundled C sources through Rust
build scripts. In the current 1.0.3 crate, that SDK path is Linux-only for this
project because the crate compiles `epoll` sources. The real BLE backend is also
an explicit `ble-real` Cargo feature so the Greengrass component build does not
pull Linux DBus development headers just to start.

The default macOS/Linux test build uses the mock Greengrass service; build the
real component path on Linux with:

```sh
just rust-debug::rig::component
```

That command compiles the AWS SDK crate and requires a native C/clang toolchain.
On Ubuntu-class hosts, install:

```sh
sudo apt install build-essential clang libclang-dev libc6-dev
```

The real component command must run under a Greengrass component lifecycle, or
with the same IPC environment that the Greengrass nucleus provides:
`AWS_GG_NUCLEUS_DOMAIN_SOCKET_FILEPATH_FOR_COMPONENT` and `SVCUID`. Direct shell
runs without those variables intentionally fail before the SDK starts.

To distinguish a missing lifecycle environment from a real IPC socket
permission/user issue, run:

```sh
just rust-debug::rig::greengrass-doctor
```

If the IPC environment is present, the doctor prints the current user/group,
socket metadata, and a Unix socket connection probe result without printing the
`SVCUID` secret value.

For an SDK-free component smoke test:

```sh
just rust-debug::rig::mock-component
```

Physical BLE commands enable `ble-real`. On Linux, those commands require the
usual BlueZ/DBus development files, for example `libdbus-1-dev` and
`pkg-config` on Ubuntu.
