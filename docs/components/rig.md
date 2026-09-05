# Rig

The `raspi` rig is the always-on host coordinator for local MCU devices. It
ships three standalone Go daemons:

- `txing-sparkplug-manager`: owns AWS IoT MQTT, Sparkplug node/device
  publication, inventory loading, board retained capability-state ingestion,
  BLE shadow update forwarding, and CloudWatch logging.
- `txing-ble-connectivity`: owns BLE scan/connect/read/write behavior and
  publishes local capability state, command results, and BLE-owned shadow
  updates.
- `txing-thread-connectivity`: owns Thread SRP/DNS-SD discovery and CoAP
  communication for `power-si`, `power-nrf`, and `tbot` devices, and publishes
  local capability state, command results, and Thread/power shadow updates. It
  reads SRP records from a colocated, already-configured OTBR through `ot-ctl`;
  it does not install or configure OTBR.

The daemons communicate only through local IPC. The default Linux IPC socket is
`/run/txing-rig/rig-ipc.sock`; the macOS development default is under
`/tmp/txing-rig`.

Daemon enablement is controlled by `daemon.env`. The rendered default is
manager-only: `txing-sparkplug-manager` is enabled, while BLE and Thread
connectivity are disabled until the operator turns on the corresponding
`TXING_*_ENABLED` variable and restarts the rig.

The same three daemons also back the `local` rig type: a development Mac
registered as a `local` rig thing. A `local` rig has no systemd units, no
autostart, and no release install; it exists only while `just rig::start` is
running. Its Sparkplug edge node is born with `NBIRTH redcon=1` on start and
projected `NDEATH` (graceful shutdown or MQTT will) as soon as the processes
stop. `local` rigs manage `mac` devices; see
[devices/mac/README.md](../../devices/mac/README.md).

## Runtime Contract

`txing-sparkplug-manager` owns all external AWS connectivity for the standalone
rig host. It uses the rig certificate and IoT role alias to:

- connect to AWS IoT MQTT with the rig Thing name `<rig>` as the Sparkplug node
  client id, so AWS IoT connectivity indexing shows the rig as connected
- create per-device Sparkplug MQTT sessions using managed thing names as client
  ids
- subscribe to Sparkplug `DCMD` messages and publish local IPC commands
- subscribe to retained board capability state under
  `txings/<device>/capability/v2/state`
- forward BLE-owned named-shadow updates from IPC to AWS IoT MQTT
- write CloudWatch logs to `txing/<town>/<rig>`

Per-device MQTT sessions are evidence-gated rather than inventory-gated. A
validated BLE GATT or Thread CoAP capability state creates a device session
immediately before its `DBIRTH`. When that adapter makes `sparkplug`
unavailable, the manager publishes one `DDEATH`, disconnects that device client,
and leaves it disconnected through later publication ticks. A later validated
adapter state creates a fresh session before the recovery `DBIRTH`. This lets
AWS IoT Thing connection status agree with the transport availability shown in
Office; the rig node MQTT session and other device sessions are unaffected.

Inventory refreshes are cost-aware so an idle-awake rig stays cheap at
REDCON 1. Each refresh performs one fleet-indexing `SearchIndex` query and
builds device registrations from the returned documents; there are no
per-device `DescribeThing` calls. The rig's own thing type is read once at
startup and the SSM type catalog is cached for one hour. The default refresh
interval is 300 seconds, so a newly registered device appears within 5
minutes; a rig restart or an `NCMD redcon=4 -> 1` cycle refreshes immediately
and is the manual force-refresh. Unchanged refreshes publish nothing over IPC
and log nothing at the default (info) log level.

`txing-ble-connectivity` and `txing-thread-connectivity` have no direct AWS MQTT
dependency. They consume rig inventory over IPC and publish:

- retained local capability state under
  `dev/txing/rig/v2/capability/state/<thing>/<adapter>`
- local command results under
  `dev/txing/rig/v2/capability/command-result/<thing>/<adapter>`
- BLE-owned `$aws/things/<device>/shadow/name/<shadow>/update` messages for the
  manager to forward
- Thread-owned `$aws/things/<device>/shadow/name/thread/update` messages and
  `power` battery updates for the manager to forward

Before forwarding a named-shadow update to AWS IoT, the manager suppresses an
identical payload previously accepted for the same topic during its current
process lifetime. This prevents periodic BLE measurement notifications from
creating shadow writes when their reported values did not change. A changed
payload, a new manager process, or a re-enlisted device publishes normally.

For every Thread-managed power device, `txing-thread-connectivity` retains the
last successfully published `power.batteryMv` per Thing in process memory. It
publishes the first valid value and a later value only when it differs by more
than 10% from that baseline; it never reads a named shadow to make this
decision. A reported unavailable value is still published and resets the
baseline, so the next valid measurement is published.

`power-si`, `power-nrf`, and `tbot` are Thread Sleepy End Devices with a 5
second poll period. Thread REDCON commands remain synchronous, so the Thread
CoAP timeout is longer than the BLE command timeout to allow one sleepy poll
window plus network jitter. The Thread daemon coalesces overlapping
discovery/state-maintenance cycles and uses bounded per-device work scheduling:
a received REDCON command cancels an in-flight maintenance GET for that device
and runs before queued maintenance. This prevents a command for a sleeping
device from missing its next child poll behind periodic state work. `tbot`
normalizes public REDCON 1, 2, and 3 to transport REDCON 3; `power-si` and
`power-nrf` accept only transport REDCON 3 and 4. A Thread loss or REDCON 4
invalidates retained board evidence, so a later tbot wake requires fresh board,
MCP, and video state before it can project REDCON 2 or 1. The daemon's
command-received and transition-confirmed logs are the operator evidence for
this bound.
The Thread daemon reads the active SRP registry through the configured
`TXING_THREAD_OT_CTL` command (`ot-ctl` by default). It does not require mDNS
publication or DNS records in `/etc/resolv.conf`; a rig using `power-si` must
run OTBR on the same host as the Thread daemon.

## Cost Posture

REDCON 1 is the normal affordable resting state for every rig type when no
managed device is awake. REDCON 4 remains the deep-sleep commandable state, but
operators should not need to park rigs there just to control idle AWS cost.

Idle-awake cost is driven by different work for each rig family:

- `raspi` and `local` rigs pay for the Sparkplug manager MQTT session, the
  inventory refresh loop, AWS IoT registry/fleet-indexing calls, SSM type
  catalog reads, and CloudWatch log ingestion. The idle loop is intentionally
  paced at `TXING_INVENTORY_INTERVAL_SECONDS=300`: one fleet-indexing
  `SearchIndex` call per unchanged refresh, no recurring per-device
  `DescribeThing`, cached type catalog reads, and no unchanged-refresh info
  log line. A restart or an `NCMD redcon=4 -> 1` cycle is the manual
  force-refresh when an operator does not want to wait up to 300 seconds for a
  newly registered device.
- `cloud` rigs pay for the EventBridge/Lambda/SQS tick chain, named-shadow
  operations, Sparkplug publishes, IoT rules, and witness projections. A
  sleeping `cloud-mcu` device receives one tick per minute, shadow writes happen
  only when rendered state changes, and stable sleeping devices do not emit
  recurring device Sparkplug publications. A device commanded awake to REDCON 3
  keeps the 6 second tick cadence for ECS reconciliation; that spend is the
  intended awake-device cost, not idle cost.

Keep an AWS Budgets monthly cost alert for each deployed environment or town.
Set the warning threshold near the expected steady-state idle spend with enough
headroom for deliberate REDCON 3 work, and treat the alert as an operations
guardrail rather than a runtime control.

## Local Development

From the repository checkout on macOS or Linux:

```bash
just rig::test
just rig::start
just rig::status
just rig::log
just rig::restart
just rig::stop
```

By default `start` runs only `txing-sparkplug-manager` — the `local` rig
default, where BLE and Thread transports are not used. The daemons resolve
their config directory like the raspi services do: `TXING_RIG_CONFIG_DIR` if
set, otherwise `~/.config/txing/rig-daemon` (raspi production is the same rule
with `HOME=/root`). Arguments are positional:

```bash
just rig::start                         # use daemon.env enablement
just rig::start <config-dir>            # explicit config directory
just rig::restart <config-dir>          # restart using daemon.env enablement
```

To enable connectivity on a local rig, edit
`~/.config/txing/rig-daemon/daemon.env`, set
`TXING_BLE_CONNECTIVITY_ENABLED=true` and/or
`TXING_THREAD_CONNECTIVITY_ENABLED=true`, then run `just rig::restart`.
If the BLE connectivity daemon should run without touching the host BLE radio
for development, set `TXING_BLE_NO_RADIO=true`; this is separate from
`TXING_BLE_CONNECTIVITY_ENABLED`.

To run the Mac as a registered `local` rig, register a `local` rig thing and
generate its config bundle from the operator machine:

```bash
just aws::deploy-rig <town-id> local <rig-name>
just aws::cert <local-rig-id>
```

Unpack `certs/<local-rig-id>/<local-rig-id>-rig-daemon-config.tgz` into
`~/.config/txing/rig-daemon` and run `just rig::start` with no arguments.
The rendered `daemon.env` keeps the standard raspi contract, including the
Linux IPC socket path; `just rig::start` exports the macOS `/tmp/txing-rig`
IPC socket default, and process environment values take precedence over
`daemon.env` values, so the bundle works on macOS unmodified.

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
- `TXING_SPARKPLUG_MANAGER_ENABLED=true`
- `TXING_BLE_CONNECTIVITY_ENABLED=false`
- `TXING_THREAD_CONNECTIVITY_ENABLED=false`
- `TXING_INVENTORY_INTERVAL_SECONDS=300`
- `TXING_BLE_RECONNECT_DELAY_MS=2000`
- `TXING_BLE_CONNECT_TIMEOUT_MS=8000`
- `TXING_BLE_COMMAND_TIMEOUT_MS=8000`
- `TXING_BLE_NO_RADIO=false`
- `TXING_CLOUDWATCH_LOG_GROUP=txing/<town>/<rig>`
- `TXING_THREAD_SERVICE_DOMAIN=default.service.arpa`
- `TXING_THREAD_OT_CTL=ot-ctl`
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
minimum_release_age = "0s"

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
ExecCondition=/bin/sh -c '. /root/.config/txing/rig-daemon/daemon.env; [ "${TXING_SPARKPLUG_MANAGER_ENABLED:-true}" = "true" ]'
ExecStart=/root/.local/share/mise/installs/txing-sparkplug-manager/latest/txing-sparkplug-manager
Restart=on-failure
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
ExecStartPre=/bin/sh -c '. /root/.config/txing/rig-daemon/daemon.env; command -v "${TXING_THREAD_OT_CTL:-ot-ctl}" >/dev/null'
ExecCondition=/bin/sh -c '. /root/.config/txing/rig-daemon/daemon.env; [ "${TXING_SPARKPLUG_MANAGER_ENABLED:-true}" = "true" ] && [ "${TXING_THREAD_CONNECTIVITY_ENABLED:-false}" = "true" ]'
ExecStart=/root/.local/share/mise/installs/txing-thread-connectivity/latest/txing-thread-connectivity
Restart=on-failure
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
ExecCondition=/bin/sh -c '. /root/.config/txing/rig-daemon/daemon.env; [ "${TXING_SPARKPLUG_MANAGER_ENABLED:-true}" = "true" ] && [ "${TXING_BLE_CONNECTIVITY_ENABLED:-false}" = "true" ]'
ExecStart=/root/.local/share/mise/installs/txing-ble-connectivity/latest/txing-ble-connectivity
Restart=on-failure
RestartSec=5

[Install]
WantedBy=rig-daemon.target
```

```ini
# /etc/systemd/system/rig-daemon.target
[Unit]
Description=Txing rig daemons
Wants=txing-sparkplug-manager.service txing-thread-connectivity.service txing-ble-connectivity.service
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

For daemon enablement rollout, make sure `daemon.env` contains
`TXING_SPARKPLUG_MANAGER_ENABLED`, `TXING_BLE_CONNECTIVITY_ENABLED`, and
`TXING_THREAD_CONNECTIVITY_ENABLED`. If a rig used the older BLE development
field, rename `TXING_BLE_NO_BLE` to `TXING_BLE_NO_RADIO`; the old name is not
read by current daemons.

If only daemon enablement changed, edit
`/root/.config/txing/rig-daemon/daemon.env`, then restart:

```bash
systemctl restart rig-daemon.target
```

## Health Checks

Useful rig checks:

```bash
systemctl status --no-pager -l rig-daemon.target
systemctl status --no-pager -l txing-sparkplug-manager.service txing-thread-connectivity.service txing-ble-connectivity.service
journalctl -u txing-sparkplug-manager.service -u txing-thread-connectivity.service -u txing-ble-connectivity.service -b --no-pager
test -S /run/txing-rig/rig-ipc.sock
/root/.local/bin/mise list
grep -E '^export TXING_(SPARKPLUG_MANAGER|BLE_CONNECTIVITY|THREAD_CONNECTIVITY)_ENABLED=' /root/.config/txing/rig-daemon/daemon.env
```

Expected behavior:

- manager logs show the Sparkplug MQTT connection and an inventory refresh
  line only when the inventory actually changed (first load, device added or
  removed); unchanged 300 s refreshes are silent at the info level
- disabled connectivity services are skipped by their systemd `ExecCondition`
  and may show as inactive without failing `rig-daemon.target`
- Thread logs are expected only when `TXING_THREAD_CONNECTIVITY_ENABLED=true`;
  then they show inventory reconciliation on inventory changes and direct
  `_txing-coap._udp` SRP discovery attempts through local `ot-ctl`
- BLE logs are expected only when `TXING_BLE_CONNECTIVITY_ENABLED=true`; then
  they show inventory reconciliation (debug level) and scanner activity, or
  offline/no-radio state when `TXING_BLE_NO_RADIO=true`
- CloudWatch receives logs under `txing/<town>/<rig>`
- `txing-sparkplug-manager` subscribes to `spBv1.0/<town>/NCMD/<rig>` for rig
  REDCON control
- `NCMD.redcon=4` keeps only the node MQTT session and NCMD path alive, then
  publishes `NBIRTH redcon=4`
- `NCMD.redcon=1` resumes inventory, per-device sessions, board retained-state
  subscriptions, device publications, and publishes `NBIRTH redcon=1`
- Sparkplug DBIRTH/DDATA/DDEATH follows the same REDCON projection as before
- BLE-owned `mcu` and device-type named shadow updates continue to reach AWS IoT
