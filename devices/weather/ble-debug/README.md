# Weather BLE Debug

This subproject isolates weather BLE debugging from Greengrass, Sparkplug, and
the production rig BLE adapter. It provides:

- a BLE CLI for macOS/CoreBluetooth and Linux/BlueZ: `weather-ble-debug`
- a separate SoftDevice S115 bare-metal debug firmware app for XIAO nRF54L15
- BLE behavior documentation for the weather connected-idle contract

The CLI is intentionally simple and prints only important events to stdout.

On macOS the CLI uses Bleak's CoreBluetooth backend. On Raspberry Pi OS /
Debian Trixie it uses Bleak's BlueZ D-Bus backend. The same commands work on
both systems; the CLI detects the OS at runtime.

## CLI

Install dependencies and run tests:

```sh
just weather::ble-debug::test
```

Run the CLI through `uv`:

```sh
just weather::ble-debug::scan weather-q8zbgb
just weather::ble-debug::inspect weather-q8zbgb
just weather::ble-debug::idle weather-q8zbgb 300
just weather::ble-debug::wake weather-q8zbgb 10 30
just weather::ble-debug::sleep weather-q8zbgb
just weather::ble-debug::soak weather-q8zbgb 50 20 20
```

Equivalent direct commands:

```sh
uv run --project devices/weather/ble-debug weather-ble-debug scan --name weather-q8zbgb --timeout 30
uv run --project devices/weather/ble-debug weather-ble-debug inspect --name weather-q8zbgb
uv run --project devices/weather/ble-debug weather-ble-debug idle --name weather-q8zbgb --duration 300
uv run --project devices/weather/ble-debug weather-ble-debug wake --name weather-q8zbgb --deadline 10 --active-seconds 30
uv run --project devices/weather/ble-debug weather-ble-debug sleep --name weather-q8zbgb
uv run --project devices/weather/ble-debug weather-ble-debug soak --name weather-q8zbgb --cycles 50 --active-seconds 20 --idle-seconds 20
```

On Linux, BlueZ's default adapter is used unless one is specified:

```sh
WEATHER_BLE_DEBUG_ADAPTER=hci0 just weather::ble-debug::soak weather-q8zbgb 45 20 20 10 60
uv run --project devices/weather/ble-debug weather-ble-debug inspect --name weather-q8zbgb --adapter hci0 --timeout 60
```

Raspberry Pi 5 / Debian Trixie host checks:

```sh
sudo systemctl enable --now bluetooth
rfkill list bluetooth
bluetoothctl show
```

If `bluetoothctl show` does not show a powered controller, fix that before
running the BLE tests. The CLI should normally be run as the logged-in user;
use system Bluetooth permissions rather than running the test as root unless
the host is configured that way.

Important event types are:

```text
adv connected services notify state measurement command wake-ok sleep-ok disconnect error summary
```

`idle` and `soak` fail on any unexpected link drop. The CLI uses the Bleak
disconnect callback and emits:

```text
disconnect unexpected=1
```

Expected cleanup disconnects are emitted as `disconnect unexpected=0`.
Connection setup events include timing fields:

```text
connected connectMs=...
services servicesMs=...
wake-ok latencyMs=...
sleep-ok latencyMs=...
```

The CLI passes its `--timeout` value through to both advertisement discovery
and the Bleak connection attempt. The `just` wrappers accept an optional final
timeout argument, for example:

```sh
just weather::ble-debug::inspect weather-q8zbgb 60
```

Summarize one or more captured stdout logs:

```sh
just weather::ble-debug::summarize /tmp/weather-ble-debug-results/baseline-100-0-6/*.log
```

The summarizer reports pass/fail, error stage, unexpected disconnect count,
wake latency, sleep latency, measurement cadence, and measurements observed
after sleep.

## Firmware

The debug firmware uses the same `sdk-nrf-bm`/S115 SoftDevice bare-metal stack
as the production weather firmware. The BM SDK build still uses Zephyr CMake
and Kconfig machinery, but it is not a Zephyr Bluetooth firmware.

Install the shared BM toolchain if needed:

```sh
just weather::ble-debug::firmware-install
```

Build the debug firmware:

```sh
just weather::ble-debug::firmware-check
```

List and build named connection-parameter profiles:

```sh
just weather::ble-debug::firmware-profiles
just weather::ble-debug::firmware-check baseline-100-0-6
just weather::ble-debug::firmware-check stable-100-0-10
just weather::ble-debug::firmware-check stable-200-0-10
just weather::ble-debug::firmware-check fast-50-0-10
just weather::ble-debug::firmware-check fast-50-0-6
```

Profiles are:

```text
baseline-100-0-6  interval=100 ms latency=0 supervision=6 s fallback=10 s
stable-100-0-10  interval=100 ms latency=0 supervision=10 s fallback=10 s
stable-200-0-10  interval=200 ms latency=0 supervision=10 s fallback=10 s
fast-50-0-10     interval=50 ms  latency=0 supervision=10 s fallback=10 s
fast-50-0-6      interval=50 ms  latency=0 supervision=6 s fallback=10 s
```

Manual-only flash, verify, and RTT targets are available for the user:

```sh
just weather::ble-debug::firmware-flash weather-q8zbgb baseline-100-0-6
just weather::ble-debug::firmware-flash-app-factory weather-q8zbgb baseline-100-0-6
just weather::ble-debug::firmware-flash-app baseline-100-0-6
just weather::ble-debug::firmware-flash-softdevice
just weather::ble-debug::firmware-verify weather-q8zbgb baseline-100-0-6
just weather::ble-debug::firmware-verify-app-factory weather-q8zbgb baseline-100-0-6
just weather::ble-debug::firmware-rtt
```

Agents must not run flash targets.

The debug flash targets use the same fast OpenOCD path as the SoftDevice-native
weather firmware: Zephyr's XIAO nRF54L15 OpenOCD board support, unbuffered
RRAMC writes, and one merged HEX per flash operation. They do not use the
Zephyr-era pyOCD chunked programming path.

Flash targets retry transient OpenOCD write failures up to 3 times after the
first failed attempt. Override this with:

```sh
WEATHER_BLE_DEBUG_FLASH_RETRIES=1 just weather::ble-debug::firmware-flash-app-factory weather-q8zbgb baseline-100-0-6
WEATHER_BLE_DEBUG_FLASH_RETRY_DELAY_SECONDS=5 just weather::ble-debug::stability-matrix weather-q8zbgb --no-confirm
```

The stability matrix defaults to `--flash-mode app-factory`: it preserves the
existing S115 SoftDevice and writes only the selected debug app profile plus the
matching factory record. This is the normal mode for candidate sweeps.

`firmware-flash` is a clean full-image flash: it erases RRAM, then writes S115,
the selected debug app profile, and the matching factory record. Use it only
when S115 also needs to be rewritten. Use `firmware-flash-app` only when you
explicitly want an app-only update without touching SoftDevice/factory data.

## Manual Full Matrix Runner

The full runner is intended for the user to run manually. It flashes each
profile, verifies it, runs the screen tests, summarizes logs, picks the top
passing candidates, and runs confirmation tests.

```sh
just weather::ble-debug::stability-matrix weather-q8zbgb
```

Outputs are written under:

```text
/tmp/weather-ble-debug-results/<run-id>/
```

The main file for later analysis is:

```text
/tmp/weather-ble-debug-results/<run-id>/analysis-report.md
```

Useful options:

```sh
# Show the exact commands without flashing or touching BLE hardware.
just weather::ble-debug::stability-matrix weather-q8zbgb --dry-run --no-confirm

# Run only the 30 minute sweep, without the top-two confirmation runs.
just weather::ble-debug::stability-matrix weather-q8zbgb --no-confirm

# Flash only the application image, leaving SoftDevice/factory data untouched.
just weather::ble-debug::stability-matrix weather-q8zbgb --flash-mode app

# Erase and rewrite S115 + app + factory for every candidate.
just weather::ble-debug::stability-matrix weather-q8zbgb --flash-mode full

# Use a custom output folder.
just weather::ble-debug::stability-matrix weather-q8zbgb --results-root /tmp/weather-ble-debug-results --run-id manual-001

# Override flash retry behavior for this run.
just weather::ble-debug::stability-matrix weather-q8zbgb --flash-retries 3 --flash-retry-delay 2
```

The default full run is long: five 30 minute candidate sweeps plus confirmation
for the top two passing candidates.

## Stability Sweep

For each candidate, the user manually flashes and verifies that candidate.
Then keep the test host awake, keep the device position fixed, and run:

```sh
candidate=baseline-100-0-6
mkdir -p "/tmp/weather-ble-debug-results/$candidate"

bash -o pipefail -c "just weather::ble-debug::scan weather-q8zbgb 30 | tee /tmp/weather-ble-debug-results/$candidate/scan.log"
bash -o pipefail -c "just weather::ble-debug::inspect weather-q8zbgb | tee /tmp/weather-ble-debug-results/$candidate/inspect.log"
bash -o pipefail -c "just weather::ble-debug::idle weather-q8zbgb 300 | tee /tmp/weather-ble-debug-results/$candidate/idle-5m.log"
bash -o pipefail -c "just weather::ble-debug::soak weather-q8zbgb 45 20 20 10 | tee /tmp/weather-ble-debug-results/$candidate/soak-30m.log"
just weather::ble-debug::summarize /tmp/weather-ble-debug-results/$candidate/*.log
```

Run candidates in this order:

```text
baseline-100-0-6
stable-100-0-10
stable-200-0-10
fast-50-0-10
fast-50-0-6
```

Retest the top two candidates:

```sh
bash -o pipefail -c "just weather::ble-debug::idle weather-q8zbgb 1800 | tee /tmp/weather-ble-debug-results/$candidate/idle-30m-confirm.log"
bash -o pipefail -c "just weather::ble-debug::soak weather-q8zbgb 180 20 20 10 | tee /tmp/weather-ble-debug-results/$candidate/soak-2h-confirm.log"
just weather::ble-debug::summarize /tmp/weather-ble-debug-results/$candidate/*confirm.log
```

## Acceptance

The intended hardware acceptance sequence is:

1. `scan` sees the target local name and weather service UUID.
2. `idle` stays connected for 5 minutes with no unexpected disconnect.
3. `wake` reports `wake-ok` within 10 seconds.
4. Measurements arrive once per second while active.
5. `sleep` reports REDCON `4` and measurement notifications stop.
6. `soak` completes 50 wake/sleep cycles without unexpected disconnects.
