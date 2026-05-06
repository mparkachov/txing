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
adv connect-retry connected services notify state measurement command wake-ok sleep-ok disconnect error summary
```

`idle` and `soak` fail on any unexpected link drop. The CLI uses the Bleak
disconnect callback and emits:

```text
disconnect unexpected=1
```

Expected cleanup disconnects are emitted as `disconnect unexpected=0`.
Connection setup events include timing fields:

```text
connect-retry attempt=... attempts=...
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

Connect, service discovery, initial state read, and notification setup are
retried up to three times by default. This covers transient BlueZ/CoreBluetooth
startup failures without changing the idle/soak stability rule: after setup,
any unexpected disconnect still fails the command.

```sh
just weather::ble-debug::soak weather-q8zbgb 5 20 20 10 60 5
uv run --project devices/weather/ble-debug weather-ble-debug soak --name weather-q8zbgb --connect-attempts 5
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

List and build named firmware profiles:

```sh
just weather::ble-debug::firmware-profiles
just weather::ble-debug::firmware-check lowpower-1000-4-20
just weather::ble-debug::firmware-check lowpower-500-4-20
just weather::ble-debug::firmware-check baseline-100-0-6
just weather::ble-debug::firmware-check stable-100-0-10
just weather::ble-debug::firmware-check stable-200-0-10
just weather::ble-debug::firmware-check stable-200-0-20
just weather::ble-debug::firmware-check stable-400-0-20
just weather::ble-debug::firmware-check fast-50-0-10
just weather::ble-debug::firmware-check fast-50-0-6
just weather::ble-debug::firmware-check floor-systemoff-5s
```

Profiles are:

```text
lowpower-1000-4-20 idle=1000 ms latency=4 supervision=20 s fallback=10 s initial=250 ms active=100/0/10 s
lowpower-500-4-20  idle=500 ms  latency=4 supervision=20 s fallback=10 s initial=250 ms active=100/0/10 s
baseline-100-0-6   idle=100 ms  latency=0 supervision=6 s  fallback=10 s initial=250 ms active=100/0/10 s
stable-100-0-10    idle=100 ms  latency=0 supervision=10 s fallback=10 s initial=250 ms active=100/0/10 s
stable-200-0-10    idle=200 ms  latency=0 supervision=10 s fallback=10 s initial=250 ms active=100/0/10 s
stable-200-0-20    idle=200 ms  latency=0 supervision=20 s fallback=10 s initial=250 ms active=100/0/10 s
stable-400-0-20    idle=400 ms  latency=0 supervision=20 s fallback=10 s initial=250 ms active=100/0/10 s
fast-50-0-10       idle=50 ms   latency=0 supervision=10 s fallback=10 s initial=250 ms active=100/0/10 s
fast-50-0-6        idle=50 ms   latency=0 supervision=6 s  fallback=10 s initial=250 ms active=100/0/10 s
floor-systemoff-5s no BLE, no sensors, no battery ADC; waits 5 s, then enters nRF54 System OFF
```

The active parameters are also used as setup parameters shortly after connect,
so GATT discovery is not forced through a long low-power interval. The selected
connected-idle parameters are requested only after state and measurement
notifications are ready, or after a REDCON `4` sleep command on an already
subscribed connection.
The default no-argument firmware profile is `lowpower-1000-4-20`.

Manual-only flash and verify targets are available for the user. The firmware
is split into three independently writable regions:

```sh
just weather::ble-debug::firmware-softdevice
just weather::ble-debug::firmware-nve weather-q8zbgb
just weather::ble-debug::firmware-app lowpower-1000-4-20
```

Agents must not run flash targets.

Use the same split for read-only verification:

```sh
just weather::ble-debug::firmware-verify-softdevice
just weather::ble-debug::firmware-verify-nve weather-q8zbgb
just weather::ble-debug::firmware-verify-app stable-200-0-20
```

The regions are:

- `firmware-softdevice`: writes only S115.
- `firmware-nve <thing>`: writes only the `TXW1` NVE/factory record containing
  the advertised Thing name.
- `firmware-app <profile>`: writes only the debug app built with that BLE
  idle and active connection-parameter profile. The app also owns runtime GPIO behavior:
  `power` on D1/P1.05 mirrors the user LED, stays low at boot and in REDCON
  `4`, and goes high immediately for REDCON `3` before BME280 initialization.
  It also samples the XIAO battery divider on AIN7/P1.14 with P1.15 as the
  active-high VBAT enable and reports it as `batteryMv`.

Profiles such as `baseline-100-0-6` and `stable-200-0-20` affect only
`firmware-app`; they do not change S115 or NVE data.

For board floor-current measurements, use `floor-systemoff-5s`:

```sh
just weather::ble-debug::firmware-app floor-systemoff-5s
just weather::ble-debug::firmware-verify-app floor-systemoff-5s
```

That app profile does not start SoftDevice, BLE, advertising, GATT, BME280, or
the battery ADC. It keeps `power` D1/P1.05 and the VBAT divider enable P1.15
low, drives the XIAO Sense PDM/IMU rail P0.01 low, parks the RF-switch helper
pins, releases the sensor pins, turns the user LED on for 5 seconds after boot,
then turns the LED off, disables RAM retention, and enters nRF54 System OFF
through `NRF_REGULATORS->SYSTEMOFF`. Measure after the LED turns off. For the
lowest realistic floor-current reading, disconnect the debugger/probe and power
the board through the measurement fixture after flashing.

For connected-idle current measurements, start with `lowpower-1000-4-20`. In
REDCON `4`, the app leaves BME280 and the battery ADC shut down, disables
scan-request events, compiles out Zephyr logging/RTT/console backends, and
idles the CPU with the S115 WFE sequence until a BLE interrupt arrives. Battery
sampling is only performed while active unless
`CONFIG_TXING_WEATHER_IDLE_BATTERY_REPORT_ENABLE=y` is explicitly enabled. The
app also overrides the BM board defconfig's enable-all nrfx list and keeps only
CLOCK, POWER, GRTC, SYSTICK, RRAMC, TWIM, and SAADC.

The SoftDevice random auto-seed path remains enabled through PSA/CRACEN. It is
required for reliable S115 BLE startup on nRF54L15; disabling it can leave the
device non-advertising.

Runtime pin ownership in the app image:

```text
power output        D1 / P1.05   active high, high-drive, mirrors user LED
BME280 Grove SDA    D4 / P1.10
BME280 Grove SCL    D5 / P1.11
VBAT ADC input      AIN7 / P1.14
VBAT divider enable P1.15        active high
Sense PDM/IMU power P0.01        active high, forced low by app
```

D0/P1.04 is deliberately not used for `power`. The XIAO connector maps D0 to
P1.04, but the BM board configuration also aliases P1.04 as UART TX. The power
measurement app compiles out logging and disables the BM UARTE console, while
D1/P1.05 keeps the external power-control contract unambiguous.

This mirrors the production unit firmware's board-low-power step, which parks
unused LEDs, IMU/mic rails, and external flash before entering its sleep-state
loop. The weather BLE image does not touch XIAO RF-switch helper pins P2.03 and
P2.05 while BLE is running, because they may be part of the radio path; the
`floor-systemoff-5s` profile parks them because it never starts BLE.

For a new or unknown board, program and verify all three regions:

```sh
just weather::ble-debug::firmware-softdevice
just weather::ble-debug::firmware-nve weather-q8zbgb
just weather::ble-debug::firmware-app lowpower-1000-4-20
just weather::ble-debug::firmware-verify-softdevice
just weather::ble-debug::firmware-verify-nve weather-q8zbgb
just weather::ble-debug::firmware-verify-app lowpower-1000-4-20
```

For profile sweeps on a board with known-good S115 and NVE, only rewrite the
app profile:

```sh
just weather::ble-debug::firmware-app stable-400-0-20
just weather::ble-debug::firmware-verify-app stable-400-0-20
```

To print the generated NVE/factory record path and flash address:

```sh
just weather::ble-debug::firmware-paths stable-200-0-20 | grep weather_factory
```

The debug flash targets use the same fast OpenOCD path as the SoftDevice-native
weather firmware: Zephyr's XIAO nRF54L15 OpenOCD board support, unbuffered
RRAMC writes, and one merged HEX per flash operation. They do not use the
Zephyr-era pyOCD chunked programming path.

If OpenOCD reports `unable to find a matching CMSIS-DAP device`, the host did
not see a usable debug probe. Check that the XIAO debug probe USB is connected,
that no other OpenOCD/pyOCD/debug session owns it, and that the probe appears
to the OS before retrying:

```sh
system_profiler SPUSBDataType | grep -Ei -A8 'cmsis|dap|seeed|xiao'
ls /dev/cu.* /dev/tty.* 2>/dev/null | grep -Ei 'usb|modem'
ps aux | grep -Ei 'openocd|pyocd|JLinkGDBServer' | grep -v grep
```

When more than one CMSIS-DAP probe is attached, select the intended one:

```sh
OPENOCD_ADAPTER_SERIAL=811D579C just weather::ble-debug::firmware-softdevice
```

Flash targets retry transient OpenOCD write failures up to 3 times after the
first failed attempt. Override this with:

```sh
WEATHER_BLE_DEBUG_FLASH_RETRIES=1 just weather::ble-debug::firmware-app baseline-100-0-6
WEATHER_BLE_DEBUG_FLASH_RETRY_DELAY_SECONDS=5 just weather::ble-debug::stability-matrix weather-q8zbgb --no-confirm
```

The stability matrix defaults to `--flash-mode app`: it assumes S115 and NVE
were prepared once and rewrites only the selected debug app profile for each
candidate. On a clean or newly swapped physical board, run
`firmware-softdevice` and `firmware-nve <thing>` before running the matrix. A
board with a valid app but no working S115 will not advertise, and the CLI will
report `no matching advertisement`.

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

# Flash only the application image, leaving SoftDevice/NVE untouched.
just weather::ble-debug::stability-matrix weather-q8zbgb --flash-mode app

# Erase and rewrite S115 + app + NVE for every candidate.
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
lowpower-1000-4-20
lowpower-500-4-20
baseline-100-0-6
stable-100-0-10
stable-200-0-10
stable-200-0-20
stable-400-0-20
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
