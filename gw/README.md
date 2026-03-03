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

Behavior:
- Discovers the MCU over BLE on startup
- Keeps BLE connection open
- Re-discovers/reconnects when the connection is lost
- Caches discovered BLE id in memory only (no temp file)
- Every 1 second:
  - if `/tmp/wake` exists, writes `sleep=false` (`0x00`) and removes `/tmp/wake`
  - if `/tmp/sleep` exists, writes `sleep=true` (`0x01`) and removes `/tmp/sleep`
