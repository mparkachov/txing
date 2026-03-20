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

## Initial Setup

On a fresh board image, update the OS packages first and install the local tooling used by this subproject:

```bash
sudo apt update
sudo apt dist-upgrade -y
sudo apt autoremove -y
sudo apt install -y git just pipx
pipx install uv
pipx ensurepath
```

Start a new shell after `pipx ensurepath`, then clone the repository onto the board if needed and continue with the build steps below.

## Build and Smoke Test

Assumed project location on the device:

- repo root: `/home/maxim/txing`
- board project: `/home/maxim/txing/board`
- shared certs: `/home/maxim/txing/certs`

Build the runtime and verify that the board process can publish once in the foreground:

```bash
cd /home/maxim/txing
python3 --version
just board::build
/home/maxim/txing/board/.venv/bin/board --once
```

For a longer foreground check before installing the service:

```bash
cd /home/maxim/txing/board
./.venv/bin/board --heartbeat-seconds 60
```

Notes:

- `just board::build` uses the OS-provided `python3`, installs the locked board environment into `board/.venv` as a non-editable runtime, and precompiles Python bytecode there.
- If `python3 --version` reports lower than `3.12`, update the OS Python before building the board runtime.
- Re-run `just board::build` after changing board code, dependencies, or the Python version on the device.
- Keep `WorkingDirectory=/home/maxim/txing/board` unless you also pass explicit `--cert-file`, `--key-file`, `--ca-file`, `--iot-endpoint-file`, and `--schema-file` paths or set `TXING_REPO_ROOT`.
- The default runtime paths continue to use `/home/maxim/txing/certs/txing.cert.pem`, `/home/maxim/txing/certs/txing.private.key`, `/home/maxim/txing/certs/AmazonRootCA1.pem`, and `/home/maxim/txing/certs/iot-data-ats.endpoint`.

## Install as a `systemd` Service

Create or replace `/etc/systemd/system/txing-board.service`, enable `NetworkManager-wait-online.service`, reload `systemd`, and enable the board service:

```bash
cd /home/maxim/txing
just board::install-service
```

Check status and logs:

```bash
sudo systemctl status txing-board
sudo journalctl -u txing-board -f
```

Notes:

- The unit intentionally omits `User=` so `systemd` runs it as `root`; that is required for local halt requests from `desired.board.power=false`.
- If you already have an older `txing-board.service`, update it in place instead of creating a second unit.
- Remove old `uv run` details if they are still present: `User=maxim`, `Environment=TMPDIR=/tmp`, `Environment=UV_CACHE_DIR=/tmp/uv-cache`, and `ExecStartPre=/usr/bin/mkdir -p /tmp/uv-cache`.
- If the old unit still uses `/home/maxim/.local/bin/uv run ...`, replace it with `ExecStart=/home/maxim/txing/board/.venv/bin/board --heartbeat-seconds 60`.
- If you need custom board arguments, edit `ExecStart=` and run `sudo systemctl daemon-reload && sudo systemctl restart txing-board`.

Useful `ExecStart=` overrides:

- `--thing-name <thing>`
- `--iot-endpoint <hostname>`
- `--cert-file <path>`
- `--key-file <path>`
- `--ca-file <path>`
- `--board-name <name>`
- `--once`

## Read-Only Root on Raspberry Pi Zero 2 W

After the board runtime is built and `txing-board.service` is running normally on a writable root filesystem, you can harden the Pi with a read-only Raspberry Pi OS Trixie layout. A practical deployment profile is:

- `/` mounted read-only
- `/boot/firmware` mounted read-only
- `/tmp`, `/var/tmp`, `/var/log`, and `/var/cache` mounted as `tmpfs`
- `journald` configured as volatile so local logs are lost on reboot
- one small writable ext4 partition used only for persistent NetworkManager state

The board process already stores its accepted-shadow mirror in `/tmp/txing_board_shadow.json`, so the board application itself does not need a persistent writable path.

1. Keep the existing Imager-created Wi-Fi configuration.

On current Raspberry Pi OS Trixie, Raspberry Pi Imager can provision Wi-Fi through Netplan, while NetworkManager exposes the active connection in `nmcli` with a name such as `netplan-wlan0-<SSID>`. If the board is already online and `nmcli connection` shows that `netplan-wlan0-...` profile, keep using it instead of creating a second Wi-Fi connection just for the board service.

Check the current state while the root filesystem is still writable:

```bash
nmcli connection show
sudo ls -1 /etc/netplan
sudo sed -n '1,200p' /etc/netplan/*.yaml
```

On this setup, treat `/etc/netplan/*.yaml` as the persistent source of truth. NetworkManager may generate the runtime profile under `/run/NetworkManager/system-connections/`, so do not rely on editing `/etc/NetworkManager/system-connections/` directly if the connection came from Netplan.

If the board already connects reliably, leave the existing Netplan Wi-Fi YAML unchanged. The main speed win comes from keeping the existing autoconnect configuration and persistent NetworkManager state, not from rewriting the Wi-Fi definition.

Only if you specifically need to pin the board to one AP radio, add `bssid:` to the existing YAML while preserving the current SSID, password, DHCP, and renderer fields. Do not replace the whole file with the minimal example below:

```yaml
network:
  version: 2
  renderer: NetworkManager
  wifis:
    wlan0:
      dhcp4: true
      dhcp6: true
      access-points:
        "FRITZ!Box 7583 MP":
          password: "<existing-password>"
          bssid: "AA:BB:CC:DD:EE:FF"
```

```bash
sudo netplan try --timeout 120
```

`netplan try` is safer on a remote system because it rolls the config back if you do not confirm it. Use plain `netplan apply` only when you already have local console access and are sure the YAML is correct.

2. Choose how `NetworkManager` state will stay writable.

If this board has only the one already-expanded SD card and you currently only have SSH access, do not try to create a new partition from the live system. On that setup there is no safe in-place path to shrink `rootfs` and carve out `TXING-PERSIST`.

The practical single-card fallback is to keep the Netplan Wi-Fi definition on the read-only root and make `/var/lib/NetworkManager` a `tmpfs`. That means:

- Wi-Fi credentials still persist in `/etc/netplan/*.yaml`
- NetworkManager runtime state is rebuilt on each boot
- Wi-Fi may reconnect a bit slower than with a dedicated persistent state partition

If you later get offline access to the card, the preferred layout is still a small ext4 partition labeled `TXING-PERSIST` mounted at `/mnt/persist`, with `/var/lib/NetworkManager` bind-mounted from there.

3. Make `/etc/resolv.conf` compatible with a read-only root.

If `/etc/resolv.conf` is a regular file on the root filesystem, DNS updates can break after `/` becomes read-only because NetworkManager can no longer rewrite that file in `/etc`.

Check the current resolver mode:

```bash
ls -l /etc/resolv.conf
readlink -f /etc/resolv.conf || true
```

For the Netplan + NetworkManager setup used in this guide, make `/etc/resolv.conf` a symlink to NetworkManager's runtime resolver file while the root filesystem is still writable:

```bash
sudo mount -o remount,rw /
sudo rm -f /etc/resolv.conf
sudo ln -s /run/NetworkManager/resolv.conf /etc/resolv.conf
sudo systemctl restart NetworkManager
```

If `systemd-resolved` is already enabled and `/etc/resolv.conf` already points to `/run/systemd/resolve/stub-resolv.conf` or `/run/systemd/resolve/resolv.conf`, keep that existing symlink instead of replacing it.

Verify before continuing:

```bash
cat /etc/resolv.conf
getent hosts google.com
```

4. Update `/etc/fstab`.

For the current single-card, SSH-only setup, use this fallback layout:

```fstab
PARTUUID=<root-partuuid>  /                    ext4  defaults,ro,noatime          0 1
PARTUUID=<boot-partuuid>  /boot/firmware      vfat  defaults,ro,noatime          0 2
tmpfs                     /tmp                 tmpfs nosuid,nodev,mode=1777,size=32M 0 0
tmpfs                     /var/tmp             tmpfs nosuid,nodev,mode=1777,size=16M 0 0
tmpfs                     /var/log             tmpfs nosuid,nodev,mode=0755,size=16M 0 0
tmpfs                     /var/cache           tmpfs nosuid,nodev,mode=0755,size=32M 0 0
tmpfs                     /var/lib/NetworkManager tmpfs nosuid,nodev,mode=0755,size=16M 0 0
```

If you later repartition the card offline and create `TXING-PERSIST`, switch to this preferred variant instead:

```fstab
PARTUUID=<root-partuuid>  /                    ext4  defaults,ro,noatime          0 1
PARTUUID=<boot-partuuid>  /boot/firmware      vfat  defaults,ro,noatime          0 2
LABEL=TXING-PERSIST       /mnt/persist         ext4  defaults,noatime             0 2
tmpfs                     /tmp                 tmpfs nosuid,nodev,mode=1777,size=32M 0 0
tmpfs                     /var/tmp             tmpfs nosuid,nodev,mode=1777,size=16M 0 0
tmpfs                     /var/log             tmpfs nosuid,nodev,mode=0755,size=16M 0 0
tmpfs                     /var/cache           tmpfs nosuid,nodev,mode=0755,size=32M 0 0
/mnt/persist/NetworkManager /var/lib/NetworkManager none bind                    0 0
```

If you eventually have offline access and want the persistent partition, create it there by shrinking partition `2` (`rootfs`) and creating a new `512 MiB` to `1 GiB` ext4 partition labeled `TXING-PERSIST`, then return to the Pi and mount it:

```bash
sudo install -d -m 0755 /mnt/persist
sudo mount LABEL=TXING-PERSIST /mnt/persist
sudo install -d -m 0755 /mnt/persist/NetworkManager
```

Notes:

- `/run` is already a `tmpfs` on `systemd` systems; no extra `fstab` entry is needed there.
- Disable swap or move it off the root filesystem before switching `/` to read-only.
- The board service itself only needs `/tmp`, volatile logs, and some writable NetworkManager state.
- On the single-card fallback, NetworkManager state is intentionally volatile. The Netplan YAML still persists on the read-only root, so the board can reconnect, but without cached runtime state.
- On the preferred partitioned layout, `/var/lib/NetworkManager` stays persistent across reboots, which gives the fastest reconnect behavior.

5. Make the journal volatile.

```bash
sudo install -d -m 0755 /etc/systemd/journald.conf.d
sudo tee /etc/systemd/journald.conf.d/volatile.conf >/dev/null <<'EOF'
[Journal]
Storage=volatile
RuntimeMaxUse=16M
EOF
```

6. Add remount aliases for the sudo-capable user.

Add these lines to the user's shell rc file such as `~/.bashrc` or `~/.zshrc`:

```bash
alias txing-rw='sudo mount -o remount,rw / && sudo mount -o remount,rw /boot/firmware'
alias txing-ro='sudo sync && sudo mount -o remount,ro /boot/firmware && sudo mount -o remount,ro /'
```

7. Apply the changed mounts, restart the relevant services, and reboot once to validate the layout.

```bash
sudo mount -a
sudo systemctl daemon-reload
sudo systemctl restart systemd-journald
sudo systemctl restart txing-board
sudo reboot
```

After reboot, verify the mount state and the board service:

```bash
findmnt / /boot/firmware /tmp /var/tmp /var/log /var/cache /var/lib/NetworkManager
readlink -f /etc/resolv.conf
nmcli connection show --active
getent hosts google.com
sudo systemctl status txing-board
```

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
