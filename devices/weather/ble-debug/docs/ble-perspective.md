# Weather BLE Perspective

## Advertisement

The debug firmware advertises as a connectable LE peripheral using Nordic S115
SoftDevice.

- Flags: LE General Discoverable Mode, BR/EDR Not Supported
- Complete local name: factory Thing name, for example `weather-q8zbgb`
- Scan response: primary weather service UUID

Weather service UUID:

```text
f6b4b000-7b32-4d2d-9f4b-4ff0a2b8f100
```

The debug CLI accepts a device only when both the local name and service UUID
match. It connects with the discovered `BLEDevice` object on both supported
host stacks.

## Connection And Discovery

Expected sequence:

1. CLI receives a matching advertisement.
2. CLI opens a GATT connection using the discovered object.
3. CLI forces service discovery if Bleak has not populated the service cache.
4. CLI reads the state characteristic.
5. CLI subscribes to state and measurement notifications.
6. CLI writes REDCON commands when asked.

The host setup phase is retried up to the configured `--connect-attempts`
count. A retry covers failures before the command has reached the idle or soak
observation phase: connection establishment, service discovery, initial state
read, and notification subscription. Once setup succeeds, unexpected
disconnects remain hard failures.

The CLI uses Bleak's CoreBluetooth backend on macOS and BlueZ D-Bus backend on
Linux, including Raspberry Pi OS / Debian Trixie. CoreBluetooth does not expose
HCI-level connection parameters through Bleak. The CLI can prove observable
GATT behavior, but it cannot show on-air supervision timeout, interval, or
latency on macOS. Use Linux `btmon` on the Raspberry Pi when those values
matter.

The debug firmware requests conservative connected-idle parameters after GATT
notification subscriptions are ready. The exact request is selected at build
time through the debug firmware profile:

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
```

The firmware requests the active parameters as setup parameters shortly after
connect, so Linux/BlueZ does not have to finish service discovery under the
central's short initial supervision timeout and does not have to discover GATT
through a 1000 ms / latency 4 idle interval. The selected connected-idle
parameters are requested only after state and measurement notification
subscriptions are ready, or after a REDCON `4` sleep command on an already
subscribed connection.

For current work, `lowpower-1000-4-20` is the default because REDCON `4` is a
connected-idle power state. REDCON `3` switches to the active profile shown in
the table so wake and 1 Hz telemetry remain responsive.

## GATT Contract

Service:

```text
f6b4b000-7b32-4d2d-9f4b-4ff0a2b8f100
```

Characteristics:

```text
command      f6b4b001-7b32-4d2d-9f4b-4ff0a2b8f100  write with response
state        f6b4b002-7b32-4d2d-9f4b-4ff0a2b8f100  read + notify
measurement  f6b4b003-7b32-4d2d-9f4b-4ff0a2b8f100  read + notify
```

Payloads are little-endian:

```text
command      <BB>    version, target_redcon
state        <BBBH>  version, redcon, flags, battery_mv
measurement  <BiIHH> version, temperature_centi_c, pressure_pa, humidity_centi_percent, battery_mv
```

Protocol version is `1`. Requested REDCON `1` or `2` is accepted as actual
REDCON `3`.

State flags:

```text
0x01 active
0x02 bme280_valid
```

`battery_mv` is reported from the XIAO battery divider when available. The
debug app enables the divider on P1.15, samples AIN7/P1.14, applies the 2:1
divider correction, and publishes the result in both state and measurement
payloads. In the default low-power configuration the divider and SAADC are
only used while active; REDCON `4` leaves them shut down. A value of `0` means
unavailable and is omitted by the CLI.

Board-level signal mapping used by the debug app:

```text
power output        D1 / P1.05   active high, high-drive, mirrors user LED
BME280 Grove SDA    D4 / P1.10
BME280 Grove SCL    D5 / P1.11
VBAT ADC input      AIN7 / P1.14
VBAT divider enable P1.15        active high
Sense PDM/IMU power P0.01        active high, forced low by this app
```

D0/P1.04 is avoided for `power` because the BM board configuration also uses
P1.04 as UART TX. The OpenOCD XIAO board support used for flashing does not
define this firmware runtime GPIO mapping; the debug app uses its own explicit
pin constants.

The connected-idle firmware path also disables scan request events, periodic
idle diagnostics, and idle battery reporting by default. The current
power-measurement image compiles logging/RTT/console backends out and
overrides the BM board defconfig's enable-all nrfx list so only CLOCK, POWER,
GRTC, SYSTICK, RRAMC, TWIM, and SAADC remain. The SoftDevice random auto-seed path
stays enabled through PSA/CRACEN because S115 on nRF54L15 needs it for reliable
BLE startup. Re-enable the observability Kconfig flags only when investigating
a specific failure, because they intentionally trade current draw for
observability.

The production unit firmware has a dedicated board-low-power pin setup for
unused LEDs, IMU/mic rails, and external flash. This XIAO debug firmware follows
the same principle: the unused XIAO Sense PDM/IMU rail P0.01 is driven low at
boot in every BLE profile. RF-switch helper pins P2.03 and P2.05 are not touched
while BLE is running because the antenna path may depend on them.

The `floor-systemoff-5s` app profile is intentionally outside the BLE contract.
It starts no BLE stack and has no advertisement, service discovery, command, or
telemetry behavior. It exists only to measure board floor current: `power`
D1/P1.05, VBAT enable P1.15, and XIAO Sense PDM/IMU power P0.01 are held low,
the RF-switch helper pins are parked, sensor pins are released, the user LED is
on for the first 5 seconds, and the app turns the LED off, disables RAM
retention, and enters nRF54 System OFF.

## Expected Timelines

Idle:

- device remains connected
- state is REDCON `4`
- `power` output D1/P1.05 is low
- user LED is off
- measurement notifications do not arrive

Wake:

- CLI writes command payload `01 03`
- firmware drives high-drive `power` output D1/P1.05 high and turns user LED on
  immediately
- firmware notifies state REDCON `3`
- firmware initializes BME280 after `power` is high
- first BME280 measurement should arrive within 10 seconds
- additional measurements should arrive once per second

Sleep:

- CLI writes command payload `01 04`
- firmware drives `power` output D1/P1.05 low and turns user LED off immediately
- firmware notifies state REDCON `4`
- measurement notifications stop

Disconnect:

- firmware clears active state
- firmware restarts connectable advertising
- CLI emits `disconnect unexpected=1` if the host BLE stack reports a link drop
  before the command finishes
- CLI emits `disconnect unexpected=0` during normal cleanup

## Stability Ranking

Hard failures:

- no matching advertisement with service UUID
- missing GATT service or required characteristic
- any unexpected disconnect during idle or soak
- any CLI `error`
- wake latency over 10 seconds
- active measurement cadence outside the expected 1 Hz band
- measurement notification after REDCON `4`

Ranking is stability first, then conservative supervision timeout, then wake
p95 latency, then measurement interval jitter.

The log summarizer emits a `summary` line for each captured CLI log:

```text
summary status=pass|fail reason=... errorStage=... unexpectedDisconnects=... wakeP50Ms=... wakeP95Ms=... wakeMaxMs=... sleepP95Ms=... measurementCount=... minIntervalMs=... avgIntervalMs=... maxIntervalMs=... measurementsAfterSleep=...
```

## CLI Failure Categories

`error stage=discover` means no advertisement matched both name and service
UUID before the timeout.

`error stage=connect` means Bleak could not establish or keep the GATT
connection long enough for discovery. On macOS this includes the
CoreBluetooth service-discovery phase that Bleak performs inside
`BleakClient.connect()`. On Linux this is the BlueZ D-Bus client path and can be
paired with `btmon` for HCI-level timing. If you temporarily build a logging
image, compare the CLI timeout with `Peer connected` and
`Peer disconnected reason=...` logs to distinguish a peripheral link drop from
a client-side connect timeout.

`connect-retry` means one setup attempt failed before the test entered
idle/wake/soak behavior. This is useful on BlueZ where the first service
discovery attempt can occasionally fail while later attempts succeed.

`error stage=services` means GATT service discovery did not expose all required
characteristics.

`error stage=wake` means REDCON `3` was written, but active state and a fresh
measurement did not both arrive before the wake deadline.

`error stage=sleep` means REDCON `4` was written, but idle state did not arrive
before the sleep deadline.

`error stage=soak` means at least one wake/sleep cycle failed or the connection
dropped unexpectedly.

`disconnect unexpected=1` without a separate `error` can still fail a log. It
means the Bleak disconnect callback fired before the CLI intentionally closed
the connection.
