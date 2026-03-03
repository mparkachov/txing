# `gw` gateway subproject

Python service for the Raspberry Pi 5 gateway.

Planned responsibilities:
- Run AWS Greengrass components/services on the gateway
- Communicate with the MCU over BLE

## BLE Bridge Process

Run from `gw/`:

```bash
uv run gw
```

Dry-run mode (no BLE calls, logs only to stdout):

```bash
uv run gw --no-ble
```

Create trigger files from another terminal:

```bash
uv run wake
uv run sleep
uv run print
```

`uv run wake` / `uv run sleep` only create trigger files. `gw` is the single process that updates simulated shadow desired/reported. `uv run print` prints the current simulated shadow JSON.

Behavior:
- Discovers the MCU over BLE on startup
- Keeps BLE connection open
- Re-discovers/reconnects when the connection is lost
- On each BLE connect/reconnect, reads MCU `State Report` and synchronizes `reported.mcu.power`.
- Caches discovered BLE id in memory only (no temp file)
- Maintains an in-memory simulated Shadow:
  - `state.desired.mcu.power` (`"on"`/`"off"`)
  - `state.reported.mcu.power` (`"on"`/`"off"`)
- Mirrors the current simulated shadow into `/tmp/txing_shadow.json` so `uv run print` can print it.
- Enforces single gw instance with lock file `/tmp/txing_gw.lock` (override with `--lock-file`).
- Every 1 second:
  - if `/tmp/wake` exists, sets `desired.mcu.power="on"`, writes `sleep=false` (`0x00`), then updates `reported.mcu.power="on"` after success
  - if `/tmp/sleep` exists, sets `desired.mcu.power="off"`, writes `sleep=true` (`0x01`), then updates `reported.mcu.power="off"` after success
- If requested desired power already equals reported power, gateway performs a no-op: logs it, removes trigger file, and clears `state.desired`.
- After a successful report update, if `reported.mcu.power` equals desired, `state.desired` is removed from the simulated shadow.
- If BLE is disconnected, gateway logs the command as pending and keeps trigger + desired until reconnect and successful send.
- In `--no-ble` mode, it performs the same file polling/removal but only logs the intended BLE action.
- Current simulated shadow payload is logged on initialization and each desired/reported update.
