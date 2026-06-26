# Rig

The `raspi` rig is the always-on host coordinator for local MCU devices. It runs
three standalone Go daemons:

- `txing-sparkplug-manager`: owns AWS IoT MQTT, Sparkplug node/device
  publication, inventory loading, board retained capability-state ingestion,
  BLE shadow update forwarding, and CloudWatch logging.
- `txing-ble-connectivity`: owns BLE scan/connect/read/write behavior and
  publishes local capability state, command results, and BLE-owned shadow
  updates.
- `txing-thread-connectivity`: owns Thread SRP/DNS-SD discovery and CoAP
  communication for `power-si` devices, and publishes local capability state,
  command results, and Thread/power shadow updates. It assumes an external OTBR
  is already configured on the rig network.

The daemons communicate only through local IPC. The default Linux IPC socket is
`/run/txing-rig/rig-ipc.sock`; the macOS development default is under
`/tmp/txing-rig`.

## Runtime Contract

`txing-sparkplug-manager` owns all external AWS connectivity for the standalone
rig host. It uses the rig certificate and IoT role alias to:

- connect to AWS IoT MQTT with the Sparkplug node client id
  `<rig>-sparkplug-manager`
- create per-device Sparkplug MQTT sessions using managed thing names as client
  ids
- subscribe to Sparkplug `DCMD` messages and publish local IPC commands
- subscribe to retained board capability state under
  `txings/<device>/capability/v2/state`
- forward BLE-owned named-shadow updates from IPC to AWS IoT MQTT
- write CloudWatch logs to `txing/<town>/<rig>`

`txing-ble-connectivity` and `txing-thread-connectivity` have no direct AWS MQTT
dependency. They consume rig inventory over IPC and publish:

- retained local capability state under `dev/txing/rig/v2/state/...`
- local command results under `dev/txing/rig/v2/command-result/...`
- BLE-owned `$aws/things/<device>/shadow/name/<shadow>/update` messages for the
  manager to forward
- Thread-owned `$aws/things/<device>/shadow/name/thread/update` messages and
  `power` battery updates for the manager to forward

`power-si` is a Thread Sleepy End Device with a 5 second poll period. Thread
REDCON commands remain synchronous, so the Thread CoAP timeout is longer than
the BLE command timeout to allow one sleepy poll window plus network jitter.

## Local Development

From the repository checkout on macOS or Linux:

```bash
just rig::test
just rig::start <config-dir> true
just rig::log
just rig::restart <config-dir> true
just rig::stop
```

The second `start` argument is `no_ble`. Use `true` on a Mac when you want the
processes and IPC path without touching BLE hardware. Arguments are positional.

## Runtime Configuration

Production rigs use root-owned config:

```text
/root/.config/txing/rig-daemon/daemon.env
/root/.config/txing/rig-daemon/AmazonRootCA1.pem
/root/.config/txing/rig-daemon/certificate.arn
/root/.config/txing/rig-daemon/certificate.pem.crt
/root/.config/txing/rig-daemon/private.pem.key
/root/.config/txing/rig-daemon/public.pem.key
```

`daemon.env` is sourceable and rendered from `rig/rig-daemon.env.template`.
Certificate paths are omitted by default; both daemons derive colocated paths
from the loaded config directory.

Important defaults:

- `TXING_RIG_IPC_SOCKET=/run/txing-rig/rig-ipc.sock`
- `TXING_INVENTORY_INTERVAL_SECONDS=30`
- `TXING_BLE_RECONNECT_DELAY_MS=2000`
- `TXING_BLE_CONNECT_TIMEOUT_MS=8000`
- `TXING_BLE_COMMAND_TIMEOUT_MS=8000`
- `TXING_CLOUDWATCH_LOG_GROUP=txing/<town>/<rig>`
- `TXING_THREAD_SERVICE_DOMAIN=default.service.arpa`
- `TXING_THREAD_DISCOVERY_INTERVAL_MS=10000`
- `TXING_THREAD_POLL_INTERVAL_MS=10000`
- `TXING_THREAD_COAP_TIMEOUT_MS=12000`

Generate rig daemon material on the operator machine:

```bash
just aws::cert <rig-id>
```

Copy `certs/<rig-id>/<rig-id>-rig-daemon-config.tgz` to the rig and unpack it
under `/root/.config/txing/rig-daemon`.

## Release Artifacts

Production `raspi` rigs install three GitHub Release assets with root-owned
`mise`:

```text
txing-sparkplug-manager-linux-aarch64.tar.gz
txing-ble-connectivity-linux-aarch64.tar.gz
txing-thread-connectivity-linux-aarch64.tar.gz
```

Each archive contains one root-level executable with the same command name.
Service starts are offline by design. A systemd restart does not invoke `mise`
or GitHub.

Rig tools are released from the `rig` component stream. Root-owned `mise`
configs must set `version_prefix = "rig-v"` so `latest` resolves from `rig-v*`
GitHub Releases instead of the repository-wide latest release. This release
model is forward-only; replace old host configs manually if they do not include
the component prefix.

## Fresh Rig Install

From a root shell on the rig, install host packages and root-owned `mise`:

```bash
apt update
apt full-upgrade -y
apt install -y ca-certificates curl jq bluetooth bluez libdbus-1-3

mkdir -p "$HOME/.local/bin"
curl https://mise.run | sh
eval "$("$HOME/.local/bin/mise" activate bash)"
mise --version
```

Install the root-owned mise config:

```bash
install -d -m 700 /root/.config/mise/conf.d /root/.local/share/mise
cat >/root/.config/mise/conf.d/txing-rig.toml <<'EOF'
[settings]
fetch_remote_versions_cache = "0s"

[tool_alias]
txing-sparkplug-manager = "github:mparkachov/txing"
txing-ble-connectivity = "github:mparkachov/txing"
txing-thread-connectivity = "github:mparkachov/txing"

[tools.txing-sparkplug-manager]
version = "latest"
version_prefix = "rig-v"
asset_pattern = "txing-sparkplug-manager-linux-aarch64.tar.gz"

[tools.txing-ble-connectivity]
version = "latest"
version_prefix = "rig-v"
asset_pattern = "txing-ble-connectivity-linux-aarch64.tar.gz"

[tools.txing-thread-connectivity]
version = "latest"
version_prefix = "rig-v"
asset_pattern = "txing-thread-connectivity-linux-aarch64.tar.gz"
EOF

MISE_TRUSTED_CONFIG_PATHS=/root/.config/mise \
  /root/.local/bin/mise install txing-sparkplug-manager@latest txing-ble-connectivity@latest txing-thread-connectivity@latest
```

Check installed versions:

```bash
/root/.local/share/mise/installs/txing-sparkplug-manager/latest/txing-sparkplug-manager --version
/root/.local/share/mise/installs/txing-ble-connectivity/latest/txing-ble-connectivity --version
/root/.local/share/mise/installs/txing-thread-connectivity/latest/txing-thread-connectivity --version
```

Write the systemd units manually:

```ini
# /etc/systemd/system/txing-sparkplug-manager.service
[Unit]
Description=Txing Sparkplug manager
PartOf=rig-daemon.target
Wants=network-online.target systemd-time-wait-sync.service
After=network-online.target systemd-time-wait-sync.service time-sync.target

[Service]
Type=simple
User=root
Environment=HOME=/root
Environment=TXING_RIG_CONFIG_DIR=/root/.config/txing/rig-daemon
Environment=TXING_RIG_IPC_SOCKET=/run/txing-rig/rig-ipc.sock
RuntimeDirectory=txing-rig
RuntimeDirectoryMode=0755
ExecStartPre=/usr/bin/test -x /root/.local/share/mise/installs/txing-sparkplug-manager/latest/txing-sparkplug-manager
ExecStartPre=-/root/.local/share/mise/installs/txing-sparkplug-manager/latest/txing-sparkplug-manager --version
ExecStart=/root/.local/share/mise/installs/txing-sparkplug-manager/latest/txing-sparkplug-manager
Restart=always
RestartSec=5

[Install]
WantedBy=rig-daemon.target
```

```ini
# /etc/systemd/system/txing-thread-connectivity.service
[Unit]
Description=Txing Thread connectivity
PartOf=rig-daemon.target
Requires=txing-sparkplug-manager.service
Wants=network-online.target systemd-time-wait-sync.service
After=txing-sparkplug-manager.service network-online.target systemd-time-wait-sync.service time-sync.target

[Service]
Type=simple
User=root
Environment=HOME=/root
Environment=TXING_RIG_CONFIG_DIR=/root/.config/txing/rig-daemon
Environment=TXING_RIG_IPC_SOCKET=/run/txing-rig/rig-ipc.sock
ExecStartPre=/usr/bin/test -x /root/.local/share/mise/installs/txing-thread-connectivity/latest/txing-thread-connectivity
ExecStartPre=-/root/.local/share/mise/installs/txing-thread-connectivity/latest/txing-thread-connectivity --version
ExecStart=/root/.local/share/mise/installs/txing-thread-connectivity/latest/txing-thread-connectivity
Restart=always
RestartSec=5

[Install]
WantedBy=rig-daemon.target
```

```ini
# /etc/systemd/system/txing-ble-connectivity.service
[Unit]
Description=Txing BLE connectivity
PartOf=rig-daemon.target
Requires=txing-sparkplug-manager.service
Wants=bluetooth.service
After=txing-sparkplug-manager.service bluetooth.service

[Service]
Type=simple
User=root
Environment=HOME=/root
Environment=TXING_RIG_CONFIG_DIR=/root/.config/txing/rig-daemon
Environment=TXING_RIG_IPC_SOCKET=/run/txing-rig/rig-ipc.sock
ExecStartPre=/usr/bin/test -x /root/.local/share/mise/installs/txing-ble-connectivity/latest/txing-ble-connectivity
ExecStartPre=-/root/.local/share/mise/installs/txing-ble-connectivity/latest/txing-ble-connectivity --version
ExecStart=/root/.local/share/mise/installs/txing-ble-connectivity/latest/txing-ble-connectivity
Restart=always
RestartSec=5

[Install]
WantedBy=rig-daemon.target
```

```ini
# /etc/systemd/system/rig-daemon.target
[Unit]
Description=Txing rig daemons
Requires=txing-sparkplug-manager.service txing-thread-connectivity.service txing-ble-connectivity.service
After=txing-sparkplug-manager.service txing-thread-connectivity.service txing-ble-connectivity.service

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
systemctl daemon-reload
systemctl enable bluetooth.service
systemctl enable rig-daemon.target
systemctl restart rig-daemon.target
systemctl status --no-pager -l rig-daemon.target
journalctl -u txing-sparkplug-manager.service -u txing-ble-connectivity.service -n 160 --no-pager
journalctl -u txing-thread-connectivity.service -n 160 --no-pager
```

## Upgrade

Publish a new immutable `rig-vX.Y.Z` release first. On the rig, enter a root shell
while the filesystem is writable and run:

```bash
MISE_TRUSTED_CONFIG_PATHS=/root/.config/mise \
  /root/.local/bin/mise upgrade txing-sparkplug-manager txing-ble-connectivity txing-thread-connectivity
/root/.local/share/mise/installs/txing-sparkplug-manager/latest/txing-sparkplug-manager --version
/root/.local/share/mise/installs/txing-ble-connectivity/latest/txing-ble-connectivity --version
/root/.local/share/mise/installs/txing-thread-connectivity/latest/txing-thread-connectivity --version
sync
```

From the operator machine, the release helper runs the upgrade and restart over
SSH:

```bash
just release::publish rig
```

On the rig host, after the binaries are upgraded, this is enough to activate
them:

```bash
sudo systemctl restart rig-daemon.target
```

If config or systemd units changed, apply those manual edits before restarting
the target.

## Health Checks

Useful rig checks:

```bash
systemctl status --no-pager -l rig-daemon.target
systemctl status --no-pager -l txing-sparkplug-manager.service txing-thread-connectivity.service txing-ble-connectivity.service
journalctl -u txing-sparkplug-manager.service -u txing-thread-connectivity.service -u txing-ble-connectivity.service -b --no-pager
test -S /run/txing-rig/rig-ipc.sock
/root/.local/bin/mise list
```

Expected behavior:

- manager logs show inventory refreshes and Sparkplug MQTT connection
- Thread logs show inventory reconciliation and `_txing-coap._udp` discovery
  attempts once an external OTBR is available
- BLE logs show inventory reconciliation and scanner activity
- CloudWatch receives logs under `txing/<town>/<rig>`
- `txing-sparkplug-manager` subscribes to `spBv1.0/<town>/NCMD/<rig>` for rig
  REDCON control
- `NCMD.redcon=4` keeps only the node MQTT session and NCMD path alive, then
  publishes `NBIRTH redcon=4`
- `NCMD.redcon=1` resumes inventory, per-device sessions, board retained-state
  subscriptions, device publications, and publishes `NBIRTH redcon=1`
- Sparkplug DBIRTH/DDATA/DDEATH follows the same REDCON projection as before
- BLE-owned `mcu` and device-type named shadow updates continue to reach AWS IoT
