# txing board

Python service for the device-side Raspberry Pi board that is power-switched by the MCU and reports runtime state to the shared `txing` Thing Shadow under `state.reported.board`.

This is not the same Raspberry Pi as `gw/`. The `gw/` Pi remains the BLE/AWS gateway. This `board/` service is for the separate Pi mounted on the device itself.

The board reuses the same AWS IoT mTLS certificate files as `gw/`, stored in `../certs/` as `txing.cert.pem` and `txing.private.key`.

## Shadow contract

The board publishes to the same classic Thing Shadow as `mcu`, but under a sibling path:

```json
{
  "state": {
    "reported": {
      "board": {
        "online": true,
        "ipv4": "192.168.1.25",
        "ipv6": "2001:db8::25"
      }
    }
  }
}
```

Notes:

- `board.*` is owned by this subproject.
- `online=false` is only a best-effort clean-shutdown update.
- `ipv4` and `ipv6` are resolved once at daemon start from the interface the OS selects for the default route in each address family.
- On a clean daemon stop, the board publishes `ipv4=null` and `ipv6=null` so AWS removes those two fields from the reported shadow document.
- Because this Pi can lose power abruptly through the MOSFET, consumers should not treat stale `online=true` as authoritative after a hard power cut.

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

## systemd Service

Assumed project location on the device:

- repo root: `/home/maxim/txing`
- board project: `/home/maxim/txing/board`
- shared certs: `/home/maxim/txing/certs`

Create the service unit:

```bash
sudo tee /etc/systemd/system/txing-board.service >/dev/null <<'EOF'
[Unit]
Description=txing board reporter
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=maxim
WorkingDirectory=/home/maxim/txing/board
ExecStart=/home/maxim/.local/bin/uv run board --heartbeat-seconds 60
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
```

Reload `systemd`, enable the service at boot, and start it now:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now txing-board
```

Check status and logs:

```bash
sudo systemctl status txing-board
sudo journalctl -u txing-board -f
```

Notes:

- The command above assumes `uv` is installed at `/home/maxim/.local/bin/uv`.
- The default runtime paths continue to use `/home/maxim/txing/certs/txing.cert.pem`, `/home/maxim/txing/certs/txing.private.key`, `/home/maxim/txing/certs/AmazonRootCA1.pem`, and `/home/maxim/txing/certs/iot-data-ats.endpoint`.
- If you need custom arguments, edit `ExecStart=` and run `sudo systemctl daemon-reload && sudo systemctl restart txing-board`.

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
- Resolves `board.ipv4` and `board.ipv6` portably by asking the OS which source address it would use for IPv4 and IPv6 default-route traffic.
- Validates each outgoing payload against `../docs/txing-shadow.schema.json`.
- Stores the last accepted shadow response in `/tmp/txing_board_shadow.json`.
- On clean `SIGINT` or `SIGTERM`, attempts a final best-effort `online=false` publish and clears `ipv4` and `ipv6` before disconnecting.

For a production deployment on the Pi, use a service manager such as `systemd` with restart-on-failure, because hard power removal can terminate the process without a graceful shutdown window.
