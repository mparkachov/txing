# BLE Debug Device

`ble-debug` is a standalone XIAO nRF54L15 BLE power probe. Most profiles are
advertising-only. The `gatt-*` profiles add only the minimal GATT surface needed
to test wake/sleep power behavior and battery reporting. This physical device
has no sensor measurement characteristic. There is still no factory/NVE data,
no S115, no SoftDevice, no nRF-BM, and no PlatformIO.

The only supported build path uses:

```text
devices/common/mcu/zephyr                       Zephyr 4.2.1
devices/common/mcu/seeed-platform              Seeed board platform
devices/common/mcu/modules/hal/cmsis           Zephyr CMSIS module
devices/common/mcu/modules/hal/cmsis_6         Zephyr CMSIS_6 module
devices/common/mcu/modules/hal/nordic          Zephyr Nordic HAL module
devices/common/mcu/modules/lib/picolibc        Zephyr picolibc module
Homebrew arm-none-eabi-gcc/binutils            compiler and binutils
openocd from PATH                              manual flashing only
```

There is no alternate external build path in this subproject.

MCU profiles live in `devices/ble-debug/mcu/conf/mcu.yaml`. The default profile is
`gatt-320-tx8`, because the default should favor first-connect reliability over
minimum idle current. Build a slower profile explicitly when measuring lowest
advertising current.

## Setup

Install host tools manually:

```sh
brew install arm-none-eabi-gcc arm-none-eabi-binutils open-ocd
```

Initialize repo-local firmware submodules:

```sh
just ble-debug::mcu::submodules
```

Create the Zephyr Python environment and validate the Homebrew toolchain:

```sh
just ble-debug::mcu::install
```

The default toolchain prefix is detected from `/opt/homebrew/bin/arm-none-eabi-`,
`/usr/local/bin/arm-none-eabi-`, or `arm-none-eabi-gcc` in `PATH`. Override it
only when needed:

```sh
export BLE_DEBUG_CROSS_COMPILE=/opt/homebrew/bin/arm-none-eabi-
```

## Build

Build the default firmware:

```sh
just ble-debug::mcu::check
just ble-debug::mcu::build
```

Build a specific profile from `mcu/conf/mcu.yaml`:

```sh
just ble-debug::mcu::build tx-minus20
just ble-debug::mcu::build tx-0
just ble-debug::mcu::build named-1280
just ble-debug::mcu::build service-1280
just ble-debug::mcu::build service-1280-tx4
just ble-debug::mcu::build service-1280-tx8
just ble-debug::mcu::build gatt-1280-tx0
just ble-debug::mcu::build gatt-1280-tx4
just ble-debug::mcu::build gatt-1280-tx8
just ble-debug::mcu::build gatt-320-tx8
just ble-debug::mcu::build service-320
```

Inspect resolved paths:

```sh
just ble-debug::mcu::paths
just ble-debug::mcu::paths service-1280
```

Build outputs are profile-specific:

```text
devices/ble-debug/mcu/build/zephyr-xiao_nrf54l15_cpuapp-brew-<profile>/zephyr/zephyr.hex
```

## Flash

Manual flash only:

```sh
just ble-debug::mcu::flash
just ble-debug::mcu::flash gatt-320-tx8
just ble-debug::mcu::flash gatt-1280-tx8
just ble-debug::mcu::flash service-1280
```

`flash` does not rebuild. Run `just ble-debug::mcu::build` first when the source
changed.

Agents must not run `flash` or any other hardware-attached command.

To check the exact flash command without touching hardware:

```sh
just ble-debug::mcu::flash-check
just ble-debug::mcu::flash-check service-1280
```

The flash command intentionally starts with plain `openocd`, so `brew upgrade`
is enough to pick up the latest OpenOCD available in your shell `PATH`.

## Firmware Behavior

All profiles:

1. Boots with the XIAO user LED and D1 `power` GPIO off.
2. Disables `pdm_imu_pwr` and `vbat_pwr`.
3. Leaves `rfsw_pwr` and `rfsw_ctl` unchanged for the BLE radio path.
4. Starts Zephyr Bluetooth.
5. Advertises indefinitely, except connectable advertising pauses during a
   connection and restarts after disconnect.

This Zephyr revision has a broken nRF54L static TX-power default path for the
lowest power values, so the app enables dynamic TX power control and programs
the advertising handle with the Zephyr vendor HCI command before advertising
starts.

Profiles are configured in `devices/ble-debug/mcu/conf/mcu.yaml`. The table below
summarizes the current profiles, ordered from lowest current toward easiest
detection:

| Profile | Interval | TX power | Scannable | Payload |
| --- | ---: | ---: | --- | --- |
| `low-current` | 10.24 s | -46 dBm | no | name only |
| `tx-minus20` | 10.24 s | -20 dBm | no | name only |
| `tx-0` | 10.24 s | 0 dBm | no | name only |
| `named-1280` | 1.28 s | 0 dBm | no | name only |
| `service-1280` | 1.28 s | 0 dBm | yes | name + weather UUID scan response |
| `service-1280-tx4` | 1.28 s | +4 dBm | yes | name + weather UUID scan response |
| `service-1280-tx8` | 1.28 s | +8 dBm | yes | name + weather UUID scan response |
| `gatt-1280-tx0` | 1.28 s | 0 dBm | connectable | name + weather UUID scan response + weather GATT |
| `gatt-1280-tx4` | 1.28 s | +4 dBm | connectable | name + weather UUID scan response + weather GATT |
| `gatt-1280-tx8` | 1.28 s | +8 dBm | connectable | name + weather UUID scan response + weather GATT |
| `gatt-320-tx8` | 320 ms | +8 dBm | connectable | conservative first-connect default |
| `service-320` | 320 ms | 0 dBm | yes | name + weather UUID scan response |

All profiles include flags and the complete local name:

```text
weather-q8zbgb
```

Only `service-*` profiles include the weather service UUID in scan response.
Use those when you need active scanners to report `service=1`. The lowest
current profiles intentionally omit scan response and service UUID because those
increase current.

The `gatt-*` profiles expose the existing weather BLE UUIDs:

```text
service      f6b4b000-7b32-4d2d-9f4b-4ff0a2b8f100
command      f6b4b001-7b32-4d2d-9f4b-4ff0a2b8f100  write with response
state        f6b4b002-7b32-4d2d-9f4b-4ff0a2b8f100  read + notify
```

The GATT profiles start in REDCON `4` sleep state with user LED and D1 `power`
off. Writing command payload `<BB>` with protocol version `1` and REDCON `3`
switches to wakeup state, turns the user LED and D1 `power` on, sends state
notification immediately, and sends refreshed state notifications every 10
seconds while active. Requested REDCON `1` or `2` is normalized to REDCON `3`.

Wake can also use extended command payload `<BBHHH>`:

```text
protocol version
REDCON target
connection interval ms
connection latency
connection supervision timeout ms
```

When the extended payload is used with REDCON `3`, the peripheral requests those
connected BLE parameters immediately during wake. The central still owns the
final decision and may accept, modify, or reject the requested parameters.
Writing REDCON `4` switches user LED and D1 `power` off, sends an idle state
notification, stops periodic state updates, and then the device terminates the
BLE connection so it can return to advertising idle. A later disconnect also
returns the board to REDCON `4`, switches user LED and D1 `power` off, and
restarts advertising.

State payload is `<BBBH>`: protocol version, actual REDCON, flags, and battery
millivolts. There is intentionally no measurement payload, because this physical
device has no BME280 or other environmental sensor. Battery sampling explicitly
enables the VBAT divider and ADC only for the sample, then disables both again
so REDCON `4` can return to the same advertising-idle current as a fresh boot.

## Current Measurement Flow

1. Build with `just ble-debug::mcu::check <profile>`.
2. Flash manually with `just ble-debug::mcu::flash <profile>`.
3. Disconnect USB and debug wiring.
4. Power through the battery pads and multimeter.
5. Run a BLE scan long enough for the selected interval and confirm `weather-q8zbgb`.
6. Measure idle current while the device is advertising, with user LED and D1 `power` off.
7. For `gatt-*`, write REDCON `3` from the BLE tool to measure wakeup-state current with user LED and D1 `power` on.

## Wake/Sleep Cycle Test

The `rig` helper is a macOS/Linux manual test tool. It uses `uv` and keeps its
own Python environment under `devices/ble-debug/rig/.venv`.

Prepare the Python environment:

```sh
just ble-debug::rig::install
```

Run one quick cycle:

```sh
just ble-debug::rig::test 1
```

Run one hour:

```sh
just ble-debug::rig::test 60
```

Each repetition connects, writes REDCON `3`, requires the device to enter wakeup
state within 10 seconds, keeps it awake for 30 seconds, requires at least three
active battery state updates, writes REDCON `4`, checks that sleep state is
reported, waits for the device to terminate the connection, and then leaves the
device in advertising idle for the rest of the minute. This default proves the
MCU owns the sleep transition and measures the low-power sleep current that
matched the advertising-only profiles.

The `starting`, `cycle-start`, `connected`, and `wake-ok` events include enough
wall-clock and elapsed timing to separate scan/connect time from REDCON command
latency.

To intentionally measure connected REDCON `4` current instead:

```sh
just ble-debug::rig::test 1 weather-q8zbgb --keep-connected-during-sleep
```

Useful overrides:

```sh
just ble-debug::rig::test 60 weather-q8zbgb --wake-deadline 10 --min-battery 3
just ble-debug::rig::test 60 weather-q8zbgb --no-require-service
```

Connected BLE parameter testing does not require reflashing. By default the rig
uses `central-default`, which sends the original two-byte command and lets the
central choose connection parameters. To request one parameter set on every wake:

```sh
just ble-debug::rig::test 180 weather-q8zbgb --conn-profile stable-100-0-20
```

To sweep multiple parameter sets in one long run, rotate through profiles every
20 cycles:

```sh
just ble-debug::rig::test 180 weather-q8zbgb \
  --conn-profile stable-100-0-10,stable-100-0-20,stable-200-0-20 \
  --conn-profile-cycles 20
```

To define a one-off profile from the command line:

```sh
just ble-debug::rig::test 60 weather-q8zbgb \
  --conn-params pi-test=150,0,20000 \
  --conn-profile pi-test
```

Built-in connection profiles:

| Profile | Interval | Latency | Supervision |
| --- | ---: | ---: | ---: |
| `central-default` | central-chosen | central-chosen | central-chosen |
| `fast-50-0-10` | 50 ms | 0 | 10 s |
| `fast-50-0-20` | 50 ms | 0 | 20 s |
| `stable-75-0-20` | 75 ms | 0 | 20 s |
| `stable-100-0-10` | 100 ms | 0 | 10 s |
| `stable-100-0-20` | 100 ms | 0 | 20 s |
| `stable-100-0-30` | 100 ms | 0 | 30 s |
| `stable-125-0-20` | 125 ms | 0 | 20 s |
| `stable-150-0-20` | 150 ms | 0 | 20 s |
| `stable-200-0-10` | 200 ms | 0 | 10 s |
| `stable-200-0-20` | 200 ms | 0 | 20 s |
| `slow-500-0-20` | 500 ms | 0 | 20 s |

Agents must not run this command because it attaches to local BLE hardware.

## Overnight Matrix Test

The overnight runner is for manual Raspberry Pi or macOS tests. It catches test
failures, keeps going, and writes analysis files under `/tmp` by default:

```sh
just ble-debug::rig::overnight
```

Default behavior is eight hours total:

1. Seven hours of round-robin matrix trials.
2. One hour confirming the best observed candidate.

Each matrix trial runs five one-minute wake/sleep cycles. The MCU-side variable
is the connection parameter request sent inside the extended REDCON `3` command.
The default matrix now focuses around the area that first looked stable on the
Pi: 75, 100, 125, 150, and 200 ms intervals with 20 s supervision, plus 100 ms
with 30 s supervision and `central-default` as a baseline. The central-side
variable is a BlueZ-style scan/connect profile: name-vs-service matching, scan
timeout, connect timeout, connect attempts, retry delay, and disconnect
deadline. The default central profiles compare conservative and balanced
timeouts with both name-only and service-required matching. The script does not
mutate global BlueZ adapter settings.

After a failed trial the runner waits 10 seconds before trying the next
candidate. Override that when needed:

```sh
just ble-debug::rig::overnight weather-q8zbgb --failure-recovery-delay 20
```

Output files:

```text
/tmp/ble-debug-overnight-results/<timestamp>/overnight.log
/tmp/ble-debug-overnight-results/<timestamp>/summary.json
/tmp/ble-debug-overnight-results/<timestamp>/report.md
```

The report ranks only candidates that actually ran. Untested candidates are
listed separately so interrupted overnight runs do not make untouched candidates
look better than failed candidates. The ranked table includes pass ratio, mean
cycles before failure, primary failure stage, wake/connect p95, unexpected
disconnect count, and RSSI avg/min/max.

Useful overrides:

```sh
just ble-debug::rig::overnight weather-q8zbgb --output-dir /tmp/ble-debug-night
just ble-debug::rig::overnight weather-q8zbgb --connection-profiles stable-75-0-20,stable-100-0-20,stable-125-0-20
just ble-debug::rig::overnight weather-q8zbgb --central-profiles bluez-conservative-name,bluez-balanced-name
```

To inspect the matrix without touching BLE hardware:

```sh
just ble-debug::rig::overnight weather-q8zbgb --dry-run
```

Agents must not run overnight tests because they attach to local BLE hardware.

Recommended detectability ladder:

```sh
just ble-debug::mcu::build tx-minus20
just ble-debug::mcu::flash-check tx-minus20

just ble-debug::mcu::build tx-0
just ble-debug::mcu::flash-check tx-0

just ble-debug::mcu::build named-1280
just ble-debug::mcu::flash-check named-1280

just ble-debug::mcu::build service-1280
just ble-debug::mcu::flash-check service-1280

just ble-debug::mcu::build service-1280-tx4
just ble-debug::mcu::flash-check service-1280-tx4

just ble-debug::mcu::build service-1280-tx8
just ble-debug::mcu::flash-check service-1280-tx8

just ble-debug::mcu::build gatt-1280-tx0
just ble-debug::mcu::flash-check gatt-1280-tx0

just ble-debug::mcu::build gatt-1280-tx4
just ble-debug::mcu::flash-check gatt-1280-tx4

just ble-debug::mcu::build gatt-1280-tx8
just ble-debug::mcu::flash-check gatt-1280-tx8

just ble-debug::mcu::build gatt-320-tx8
just ble-debug::mcu::flash-check gatt-320-tx8
```

## Generated State

Generated files stay under:

```text
devices/ble-debug/mcu/.venv/
devices/ble-debug/mcu/.pip-cache/
devices/ble-debug/mcu/.zephyr-cache/
devices/ble-debug/mcu/.ccache/
devices/ble-debug/mcu/build/
```

Clean build output:

```sh
just ble-debug::mcu::clean
```
