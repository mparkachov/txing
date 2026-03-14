# txing board

Python service for the device-side Raspberry Pi board that is power-switched by the MCU and reports runtime state to the shared `txing` Thing Shadow under `state.reported.board`.

This is not the same Raspberry Pi as `gw/`. The `gw/` Pi remains the BLE/AWS gateway. This `board/` service is for the separate Pi mounted on the device itself.

The board reuses the same AWS IoT mTLS certificate files as `gw/`, stored in `../certs/` as `txing.cert.pem` and `txing.private.key`.

## Hardware wiring

What each wire means:

- Battery `+` -> Pololu board `VIN+`
  - The Pi board assembly still gets battery positive directly.
- Battery `-` -> nRF `GND`
  - The nRF stays powered all the time and keeps a permanent ground reference.
- MOSFET source -> battery `-`
  - This is the unswitched negative rail.
- MOSFET drain -> Pololu board `GND`
  - This is the switched ground return for the Pi board assembly.
- nRF GPIO `D0` / `P0.02` -> MOSFET gate through `100` to `330 ohm`
  - This limits ringing and inrush into the gate capacitance.
- `100 kOhm` resistor from gate to source
  - This keeps the MOSFET off during reset and boot.

## Power behavior

- GPIO low:
  - Gate and source both sit near battery negative.
  - `Vgs` is about `0 V`.
  - The MOSFET is off.
  - The Pi and Pololu board are off.
- GPIO high at `3.3 V`:
  - Gate is about `3.3 V` above source.
  - `Vgs` is about `+3.3 V`.
  - The `IRLB8721` turns on.
  - The Pololu board gets its ground return.
  - The regulator starts and the Pi powers up.

Adafruit markets the `IRLB8721` as a logic-level MOSFET suitable for `3.3 V` gate drive.

## Shadow contract

The board publishes to the same classic Thing Shadow as `mcu`, but under a sibling path:

```json
{
  "state": {
    "reported": {
      "board": {
        "online": true,
        "hostname": "txing-board",
        "bootId": "3f31df2f-9f2e-45c9-9d6a-91df3a9f0d07",
        "model": "Raspberry Pi 5 Model B Rev 1.0",
        "programVersion": "0.1.0",
        "startedAt": "2026-03-14T10:35:00Z",
        "reportedAt": "2026-03-14T10:36:00Z",
        "uptimeSeconds": 412,
        "clientId": "txing-board-txing-board-12345"
      }
    }
  }
}
```

Notes:

- `board.*` is owned by this subproject.
- `online=false` is only a best-effort clean-shutdown update.
- Because this Pi can lose power abruptly through the MOSFET, consumers should use `reportedAt` and `bootId` to judge freshness instead of relying only on `online`.

## Project layout

- `pyproject.toml`: `uv` project definition
- `src/board/shadow_reporter.py`: CLI entrypoint and MQTT shadow reporter
- `src/board/shadow_store.py`: local mirror file helper for accepted shadow responses
- `justfile`: convenience commands for local use

## Prerequisites

- Python `3.12`
- `uv`
- AWS IoT Core endpoint, root CA, client certificate, and client private key

The defaults expect shared repo cert material in `../certs/`:

- endpoint: `../certs/iot-data-ats.endpoint`
- certificate: `../certs/txing.cert.pem`
- private key: `../certs/txing.private.key`
- root CA: `../certs/AmazonRootCA1.pem`

The board uses the same certificate set as `gw/`; do not issue a separate board-specific certificate unless you intentionally want to rotate away from the shared default naming.

To issue or rotate the shared certificate set:

```bash
just aws::cert
```

## Quickstart

```bash
cd board
uv python install 3.12
uv sync
uv run board --once
```

Long-running service example:

```bash
cd board
uv run board --heartbeat-seconds 60
```

Useful overrides:

- `--thing-name <thing>`
- `--iot-endpoint <hostname>`
- `--cert-file <path>`
- `--key-file <path>`
- `--ca-file <path>`
- `--board-name <name>`
- `--once`

## Behavior of the scaffold

- Connects directly to AWS IoT Core over MQTT with mTLS.
- Publishes `state.reported.board` to `$aws/things/<thing>/shadow/update`.
- Validates each outgoing payload against `../docs/txing-shadow.schema.json`.
- Stores the last accepted shadow response in `/tmp/txing_board_shadow.json`.
- On clean `SIGINT` or `SIGTERM`, attempts a final best-effort `online=false` publish before disconnecting.

For a production deployment on the Pi, use a service manager such as `systemd` with restart-on-failure, because hard power removal can terminate the process without a graceful shutdown window.
