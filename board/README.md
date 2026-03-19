# txing board

Python service for the device-side Raspberry Pi board that is power-switched by the MCU and reports runtime state to the shared `txing` Thing Shadow under `state.reported.board`.

This is not the same Raspberry Pi as `gw/`. The `gw/` Pi remains the BLE/AWS gateway. This `board/` service is for the separate Pi mounted on the device itself.

The board reuses the same AWS IoT mTLS certificate files as `gw/`, stored in `../certs/` as `txing.cert.pem` and `txing.private.key`.

When the service is managed by `systemd`, run it as `root`. The board control consumes `state.desired.board.power=false` and requests a local system halt, which requires root privileges.

## Shadow contract

The board publishes to the same classic Thing Shadow as `mcu`, but under a sibling path:

```json
{
  "state": {
    "reported": {
      "board": {
        "power": true,
        "wifi": {
          "online": true,
          "ipv4": "192.168.1.25",
          "ipv6": "2001:db8::25"
        }
      }
    }
  }
}
```

Notes:

- `board.*` is owned by this subproject.
- `desired.board.power=false` is a one-shot shutdown request. The board control clears that desired field on clean shutdown so the request does not persist across the next boot.
- `reported.board.power=false` is only a best-effort clean-shutdown update.
- `reported.board.wifi.online` reflects the board-side online status while the board OS is up and the board control is running.
- `reported.board.wifi.ipv4` and `reported.board.wifi.ipv6` are resolved once at daemon start from the interface the OS selects for the default route in each address family.
- On a clean daemon stop, the board publishes `wifi.ipv4=null` and `wifi.ipv6=null` so AWS removes those two fields from the reported shadow document.
- Because this Pi can lose power abruptly through the MOSFET, consumers should not treat stale `power=true` or stale `wifi.online=true` as authoritative after a hard power cut.

## Project layout

- `pyproject.toml`: `uv` project definition
- `src/board/shadow_control.py`: CLI entrypoint and MQTT board control
- `src/board/shadow_store.py`: local mirror file helper for accepted shadow responses
- `justfile`: convenience commands for local use

## Prerequisites

- Python `3.12+` installed by the base OS and available as `python3`
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
just build
./.venv/bin/board --once
```

The build uses the system `python3`. Check that first:

```bash
python3 --version
```

Long-running service example:

```bash
cd board
./.venv/bin/board --heartbeat-seconds 60
```

From the repository root, the same build step is:

```bash
just board::build
```

## systemd Service

Assumed project location on the device:

- repo root: `/home/maxim/txing`
- board project: `/home/maxim/txing/board`
- shared certs: `/home/maxim/txing/certs`

Build the runtime once before enabling the service:

```bash
cd /home/maxim/txing
python3 --version
just board::build
```

Create the service unit:

```bash
sudo tee /etc/systemd/system/txing-board.service >/dev/null <<'EOF'
[Unit]
Description=txing board control
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/home/maxim/txing/board
ExecStart=/home/maxim/txing/board/.venv/bin/board --heartbeat-seconds 60
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

- `just board::build` uses the OS-provided `python3`, installs the locked board environment into `board/.venv` as a non-editable runtime, and precompiles Python bytecode there.
- If `python3 --version` reports lower than `3.12`, update the OS Python before building the board runtime.
- The unit intentionally omits `User=` so `systemd` runs it as `root`; that is required for local halt requests from `desired.board.power=false`.
- Re-run `just board::build` after changing board code, dependencies, or the Python version on the device.
- Keep `WorkingDirectory=/home/maxim/txing/board` unless you also pass explicit `--cert-file`, `--key-file`, `--ca-file`, `--iot-endpoint-file`, and `--schema-file` paths or set `TXING_REPO_ROOT`.
- The default runtime paths continue to use `/home/maxim/txing/certs/txing.cert.pem`, `/home/maxim/txing/certs/txing.private.key`, `/home/maxim/txing/certs/AmazonRootCA1.pem`, and `/home/maxim/txing/certs/iot-data-ats.endpoint`.
- If you need custom arguments, edit `ExecStart=` and run `sudo systemctl daemon-reload && sudo systemctl restart txing-board`.

## Migrating an Existing `systemd` Service

If the board is still running through `uv run`, update it in place:

1. Rebuild the board runtime:

```bash
cd /home/maxim/txing
python3 --version
just board::build
```

2. Edit the existing unit at `/etc/systemd/system/txing-board.service`:
   - remove `User=maxim` if it is still present
   - remove `Environment=TMPDIR=/tmp`
   - remove `Environment=UV_CACHE_DIR=/tmp/uv-cache`
   - remove `ExecStartPre=/usr/bin/mkdir -p /tmp/uv-cache`
   - replace the old `ExecStart=/home/maxim/.local/bin/uv run ...` with:

```ini
ExecStart=/home/maxim/txing/board/.venv/bin/board --heartbeat-seconds 60
```

3. Reload and restart the service:

```bash
sudo systemctl daemon-reload
sudo systemctl restart txing-board
sudo systemctl status txing-board
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
- Subscribes to `$aws/things/<thing>/shadow/get/accepted`, `$aws/things/<thing>/shadow/update/accepted`, and `$aws/things/<thing>/shadow/update/delta`.
- Requests the full shadow snapshot on connect so a persisted `desired.board.power=false` is consumed immediately after startup.
- Resolves `board.wifi.ipv4` and `board.wifi.ipv6` portably by asking the OS which source address it would use for IPv4 and IPv6 default-route traffic.
- Validates each outgoing payload against `../docs/txing-shadow.schema.json`.
- Stores the last accepted shadow response in `/tmp/txing_board_shadow.json`.
- Publishes `state.reported.board.power=true` and `state.reported.board.wifi.online=true` while the board service is running.
- When it observes `state.desired.board.power=false`, it publishes a final best-effort shutdown update with `reported.board.power=false`, clears `desired.board.power`, and then requests `systemctl halt --no-wall`.
- On clean `SIGINT` or `SIGTERM`, it attempts a final best-effort shutdown update, clears `wifi.ipv4` and `wifi.ipv6`, and removes `desired.board.power` before disconnecting.

For a production deployment on the Pi, use a service manager such as `systemd` with restart-on-failure, because hard power removal can terminate the process without a graceful shutdown window.
