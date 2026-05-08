# Rust Debug Agent Guide

## Scope
- Keep changes isolated under `devices/rust-debug/` unless the user explicitly asks for a shared rig/tooling change.
- This device type is a rig-side Rust experiment for the BLE debug contract.
- Do not add Python projects, Python dependencies, `uv`, Zephyr MCU code, or firmware flashing flows under this project.
- Physical BLE tests may be prepared and exposed as commands, but agents must not run physical BLE commands unless the user explicitly asks for hardware-attached testing.

## Runtime Rules
- `devices/rust-debug/rig` is a Rust crate for Greengrass-style rig BLE connectivity experiments.
- Fast simulated tests should be runnable with `cargo test` and must not require BLE hardware.
- Real BLE runs use `btleplug` as the Rust BLE central implementation for macOS CoreBluetooth and Linux BlueZ.
- The production Greengrass entrypoint may depend on the AWS Greengrass Component SDK for Rust.
