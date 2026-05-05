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
baseline-100-0-6  interval=100 ms latency=0 supervision=6 s  fallback=10 s
stable-100-0-10  interval=100 ms latency=0 supervision=10 s fallback=10 s
stable-200-0-10  interval=200 ms latency=0 supervision=10 s fallback=10 s
fast-50-0-10     interval=50 ms  latency=0 supervision=10 s fallback=10 s
fast-50-0-6      interval=50 ms  latency=0 supervision=6 s  fallback=10 s
```

The firmware first waits for state and measurement notification subscriptions.
If the central does not subscribe, the fallback delay eventually requests the
same connected-idle parameters anyway.

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

## Expected Timelines

Idle:

- device remains connected
- state is REDCON `4`
- user LED is off
- measurement notifications do not arrive

Wake:

- CLI writes command payload `01 03`
- firmware turns user LED on immediately
- firmware notifies state REDCON `3`
- first BME280 measurement should arrive within 10 seconds
- additional measurements should arrive once per second

Sleep:

- CLI writes command payload `01 04`
- firmware turns user LED off immediately
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
paired with `btmon` for HCI-level timing. Compare the CLI timeout with RTT
`Peer connected` and `Peer disconnected reason=...` logs to distinguish a
peripheral link drop from a client-side connect timeout.

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
