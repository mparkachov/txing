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
- `reported.board.wifi.ipv4` and `reported.board.wifi.ipv6` are refreshed on each publish loop from the interface the OS selects for the default route in each address family.
- On a clean daemon stop, the board publishes `wifi.ipv4=null` and `wifi.ipv6=null` so AWS removes those two fields from the reported shadow document.
- Because this Pi can lose power abruptly through the MOSFET, consumers should not treat stale `power=true` or stale `wifi.online=true` as authoritative after a hard power cut.

## Project layout

- `pyproject.toml`: `uv` project definition
- `src/board/shadow_control.py`: CLI entrypoint and MQTT board control, including MediaMTX startup gating and video reporting
- `src/board/media_runtime.py`: MediaMTX viewer URL and readiness probe helpers
- `src/board/media_state.py`: board video shadow-state normalization helpers
- `src/board/shadow_store.py`: local mirror file helper for accepted shadow responses
- `examples/mediamtx.yml`: sample MediaMTX config for the phase-1 local video MVP
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

## End-to-End Reinstall From Raspberry Pi Imager

Use this order on a fresh board rebuild:

1. On the development machine, prepare the AWS IoT artifacts in the repo `certs/` directory.
2. Flash a fresh Raspberry Pi OS Lite image with Raspberry Pi Imager and enable SSH + Wi-Fi.
3. Boot the board, install local tools, and clone the repo to `/home/user/txing`.
4. Copy the four AWS IoT client files from the development machine to `/home/user/txing/certs` on the board.
5. Install MediaMTX and its `systemd` unit on the board.
6. Build and smoke-test `txing-board` on the normal writable root filesystem.
7. Enable `mediamtx` and `txing-board` services and verify they survive a reboot.
8. Only after both services work normally, apply the read-only-root steps later in this document.

Assumptions used below:

- the board login user is `user`
- `user` is the login account created with Raspberry Pi Imager
- the repo path on the board is `/home/user/txing`
- the board is reachable as `user@<board-host>`

If you choose a different Imager username or clone path, replace `/home/user` consistently in the commands below.

### 1. Prepare AWS Artifacts on the Development Machine

If the AWS stack already exists and you only need the board/gateway client artifacts:

```bash
cd /path/to/txing
just aws::cert
just aws::endpoint
just aws::ca
just aws::init-shadow
just aws::check
```

If this is a new AWS environment and you want the stack plus IoT artifacts in one pass:

```bash
cd /path/to/txing
just aws::bootstrap \
  <unique-cognito-prefix> \
  <admin-email>
just aws::check
```

The board only needs these four files from the repo `certs/` directory:

- `txing.cert.pem`
- `txing.private.key`
- `AmazonRootCA1.pem`
- `iot-data-ats.endpoint`

### 2. Flash and Boot the Board

In Raspberry Pi Imager:

- choose Raspberry Pi OS Lite based on Raspberry Pi OS Trixie
- use the advanced options to set the hostname, username, password, Wi-Fi, locale, and enable SSH
- if you want to reuse the commands below exactly, set the username to `user`

After the first boot, connect over SSH:

```bash
ssh user@<board-host>
```

## Initial Setup

On a fresh board image, update the OS packages first and install the local tooling used by this subproject:

```bash
sudo apt update
sudo apt dist-upgrade -y
sudo apt autoremove -y
sudo apt install -y curl git jq just pipx
pipx install uv
pipx ensurepath
```

Start a new shell after `pipx ensurepath`, then clone the repository onto the board:

```bash
cd /home/user
git clone <your-txing-repo-url> txing
cd /home/user/txing
```

## Copy AWS IoT Client Artifacts to the Board

From the development machine, create the target directory and copy the shared AWS IoT client files:

```bash
ssh user@<board-host> 'install -d -m 0755 /home/user/txing/certs'
scp \
  certs/txing.cert.pem \
  certs/txing.private.key \
  certs/AmazonRootCA1.pem \
  certs/iot-data-ats.endpoint \
  user@<board-host>:/home/user/txing/certs/
ssh user@<board-host> '\
  chmod 0644 /home/user/txing/certs/txing.cert.pem \
             /home/user/txing/certs/AmazonRootCA1.pem \
             /home/user/txing/certs/iot-data-ats.endpoint && \
  chmod 0600 /home/user/txing/certs/txing.private.key'
```

Back on the board, verify the files before building anything:

```bash
cd /home/user/txing
ls -l certs
test -s certs/txing.cert.pem
test -s certs/txing.private.key
test -s certs/AmazonRootCA1.pem
test -s certs/iot-data-ats.endpoint
```

## Build and Smoke Test

Assumed project location on the device:

- repo root: `/home/user/txing`
- board project: `/home/user/txing/board`
- shared certs: `/home/user/txing/certs`

Build the runtime and verify that the board process can publish once in the foreground:

```bash
cd /home/user/txing
python3 --version
just board::build
/home/user/txing/board/.venv/bin/board --once
```

For a longer foreground check before installing the service:

```bash
cd /home/user/txing/board
./.venv/bin/board --heartbeat-seconds 60
```

Notes:

- `just board::build` uses the OS-provided `python3`, installs the locked board environment into `board/.venv` as a non-editable runtime, and precompiles Python bytecode there.
- If `python3 --version` reports lower than `3.12`, update the OS Python before building the board runtime.
- Re-run `just board::build` after changing board code, dependencies, or the Python version on the device.
- Keep `WorkingDirectory=/home/user/txing/board` unless you also pass explicit `--cert-file`, `--key-file`, `--ca-file`, `--iot-endpoint-file`, and `--schema-file` paths or set `TXING_REPO_ROOT`.
- The default runtime paths continue to use `/home/user/txing/certs/txing.cert.pem`, `/home/user/txing/certs/txing.private.key`, `/home/user/txing/certs/AmazonRootCA1.pem`, and `/home/user/txing/certs/iot-data-ats.endpoint`.

## Install as a `systemd` Service

Create or replace `/etc/systemd/system/txing-board.service`, enable `NetworkManager-wait-online.service`, reload `systemd`, and enable the board service. The generated unit pulls in `mediamtx.service` and starts `txing-board` after MediaMTX:

```bash
cd /home/user/txing
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
- Remove old `uv run` details if they are still present: `User=user`, `Environment=TMPDIR=/tmp`, `Environment=UV_CACHE_DIR=/tmp/uv-cache`, and `ExecStartPre=/usr/bin/mkdir -p /tmp/uv-cache`.
- If the old unit still uses `/home/user/.local/bin/uv run ...`, replace it with `ExecStart=/home/user/txing/board/.venv/bin/board --heartbeat-seconds 60`.
- The generated unit now includes `Wants=mediamtx.service` and `After=mediamtx.service`.
- `txing-board` waits for a successful local MediaMTX probe before its first shadow publish. If MediaMTX does not become ready within the startup timeout, the process exits non-zero so `systemd` can retry it.
- If you need custom board arguments, edit `ExecStart=` and run `sudo systemctl daemon-reload && sudo systemctl restart txing-board`.

Useful `ExecStart=` overrides:

- `--thing-name <thing>`
- `--iot-endpoint <hostname>`
- `--cert-file <path>`
- `--key-file <path>`
- `--ca-file <path>`
- `--board-name <name>`
- `--stream-path <path>`
- `--viewer-port <port>`
- `--viewer-host <name-or-address>`
- `--probe-host <host>`
- `--probe-timeout-seconds <seconds>`
- `--media-startup-timeout-seconds <seconds>`
- `--once`

## Board Video MVP

The local board video MVP uses a single Python board daemon plus a separate operator-managed MediaMTX service:

- `txing-board` remains the only AWS IoT shadow publisher
- `txing-board` now probes MediaMTX locally and publishes `board.video.*` directly
- `txing-board` blocks its first shadow publish until the MediaMTX viewer page is reachable
- MediaMTX owns the Raspberry Pi camera directly through its `rpiCamera` source
- the web app connects directly to the board over the local LAN from the Vite dev server
- the published viewer URL prefers the board's default-route IPv4 address and falls back to IPv6 if IPv4 is unavailable

Useful local commands:

```bash
cd /home/user/txing/board
./.venv/bin/board --once --debug
./.venv/bin/board --once --debug --viewer-host txing
```

Notes:

- The sample MediaMTX config in `examples/mediamtx.yml` is pinned to `1920x1080` at `30 fps`.
- The sample config uses `rpiCameraCodec: hardwareH264`, which works on the tested Pi image even though the GStreamer `v4l2h264enc` path does not.
- The default browser viewer URL published into the Thing Shadow is `http://<board-ipv4>:8889/board-cam/`.
- If you prefer to publish a hostname instead of the detected address, start `board` with `--viewer-host txing`.
- `board --once` now waits for a successful local MediaMTX probe before publishing; if MediaMTX is not ready within the startup timeout, it exits non-zero.

Install the Raspberry Pi camera tools first:

```bash
sudo apt update
sudo apt install -y \
  libcamera-tools
```

Check the target board before enabling the service:

```bash
rpicam-hello --list-cameras
rpicam-vid -t 5000 --width 1920 --height 1080 --framerate 30 --codec h264 -o /tmp/rpicam-1080p30.h264
ls -lh /tmp/rpicam-1080p30.h264
```

Install MediaMTX separately. The repo does not vendor it. Use the upstream Linux release that matches the Pi OS architecture and then install the sample config from this repo:

```bash
arch="$(dpkg --print-architecture)"
case "$arch" in
  arm64) mediamtx_arch='linux_arm64v8' ;;
  armhf) mediamtx_arch='linux_armv7' ;;
  *)
    echo "Unsupported architecture for this guide: $arch" >&2
    exit 1
    ;;
esac

MEDIAMTX_VERSION="$(curl -fsSL https://api.github.com/repos/bluenviron/mediamtx/releases/latest | jq -r .tag_name)"
workdir="$(mktemp -d)"
archive="mediamtx_${MEDIAMTX_VERSION}_${mediamtx_arch}.tar.gz"
trap 'rm -rf "$workdir"' EXIT
curl -fsSL \
  -o "$workdir/$archive" \
  "https://github.com/bluenviron/mediamtx/releases/download/${MEDIAMTX_VERSION}/${archive}"
tar -xzf "$workdir/$archive" -C "$workdir"
sudo install -m 0755 "$workdir/mediamtx" /usr/local/bin/mediamtx

sudo install -d -m 0755 /etc/mediamtx
sudo install -m 0644 /home/user/txing/board/examples/mediamtx.yml /etc/mediamtx/mediamtx.yml
```

For the IPv4-local MVP, no extra `webrtcAdditionalHosts` entry is required. If you later switch back to IPv6-only local access, add the board's reachable IPv6 address there and restart MediaMTX.

Create the operator-managed MediaMTX unit:

```bash
sudo tee /etc/systemd/system/mediamtx.service >/dev/null <<'EOF'
[Unit]
Description=MediaMTX
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/local/bin/mediamtx /etc/mediamtx/mediamtx.yml
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
```

Then enable and start MediaMTX:

```bash
sudo systemctl enable NetworkManager-wait-online.service
sudo systemctl daemon-reload
sudo systemctl enable --now mediamtx
sudo systemctl status mediamtx
```

The sample config already opens the camera directly at `1920x1080` and `30 fps`. Verify that MediaMTX has the stream online:

```bash
sudo journalctl -u mediamtx -n 50 --no-pager
curl -sSf http://127.0.0.1:8889/board-cam/ >/dev/null
```

Look for a line like:

```text
[path board-cam] stream is available and online, 1 track (H264)
```

Build and start the board process with MediaMTX gating:

```bash
cd /home/user/txing
just board::build

cd /home/user/txing/board
./.venv/bin/board --once --debug
```

If you want the published URL to use your local hostname instead of the detected address:

```bash
./.venv/bin/board --once --debug --viewer-host txing
```

The expected `reported.board.video` payload in the accepted shadow response is:

```json
{
  "status": "ready",
  "ready": true,
  "local": {
    "viewerUrl": "http://192.168.0.10:8889/board-cam/",
    "streamPath": "board-cam"
  },
  "codec": {
    "video": "h264"
  },
  "viewerConnected": false,
  "lastError": null
}
```

From the Mac, you can test the viewer page directly before using the web app:

```text
http://192.168.0.10:8889/board-cam/
```

- The MVP uses MediaMTX and the built-in viewer page over plain HTTP.
- The MVP does not use auth, TLS, CloudFront, browser-to-board control transport, or cloud upload.
- The MVP advertises the exact iframe URL under `reported.board.video.local.viewerUrl`.
- On the tested Pi image, MediaMTX `rpiCamera` works for hardware H.264 while the GStreamer `v4l2h264enc` path fails on the first frame. Keep the MVP on the MediaMTX camera source unless the OS image changes.

## Fresh-Image Service Install Order

Once the foreground checks above pass on the writable root filesystem, install the services in this order:

```bash
cd /home/user/txing
just board::install-service
sudo systemctl status mediamtx
sudo systemctl status txing-board
sudo reboot
```

After reboot, verify both services before switching the board to read-only mode:

```bash
sudo systemctl status mediamtx
sudo systemctl status txing-board
sudo journalctl -u mediamtx -n 50 --no-pager
sudo journalctl -u txing-board -n 50 --no-pager
curl -sSf http://127.0.0.1:8889/board-cam/ >/dev/null
```

## Read-Only Root on Raspberry Pi Zero 2 W

After the board runtime is built and both `mediamtx.service` and `txing-board.service` are running normally on a writable root filesystem, you can harden the Pi with a read-only Raspberry Pi OS Trixie layout. A practical deployment profile is:

- `/` mounted read-only
- `/boot/firmware` mounted read-only
- `/tmp`, `/var/tmp`, and `/var/log` mounted as `tmpfs`
- `journald` configured as volatile so local logs are lost on reboot
- one small writable ext4 partition used only for persistent NetworkManager state

The board process already stores its accepted-shadow mirror in `/tmp/txing_board_shadow.json`, so the board application itself does not need a persistent writable path.

Leave `/var/cache` on the root filesystem. It is not needed by the board services during normal read-only operation, and keeping it on disk makes maintenance sessions simpler when you temporarily remount `/` read-write to run `apt`.

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
- Keeping `/var/cache` on disk avoids special-case maintenance steps when you temporarily remount `/` read-write for package installs or upgrades.
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
alias root-rw='sudo mount -o remount,rw /'
alias root-ro='sudo sync && sudo mount -o remount,ro /'
```

If you also keep `/boot/firmware` mounted read-only, remount it explicitly only when needed:

```bash
sudo mount -o remount,rw /boot/firmware
sudo mount -o remount,ro /boot/firmware
```

7. Disable periodic maintenance timers and optional cron jobs that are not useful on the read-only board.

Inspect what is active first:

```bash
systemctl list-timers --all
```

For a minimal headless board, a practical default is to disable automatic package maintenance, disable log rotation because logs are already volatile, and disable cron if nothing on the board needs it:

```bash
sudo systemctl disable --now apt-daily.timer apt-daily-upgrade.timer 2>/dev/null || true
sudo systemctl mask apt-daily.service apt-daily-upgrade.service 2>/dev/null || true
sudo systemctl disable --now logrotate.timer 2>/dev/null || true
sudo systemctl disable --now cron.service 2>/dev/null || true
```

Keep `systemd-tmpfiles-clean.timer` enabled. It cleans old files from `/tmp` and other volatile directories and is useful on this layout.

On Raspberry Pi OS, after disabling the generic maintenance timers above, the remaining ones you are likely to still see are:

```bash
sudo systemctl disable --now dpkg-db-backup.timer
sudo systemctl disable --now rpi-zram-writeback.timer
```

If present on the image and not needed for your deployment, you can also disable other periodic housekeeping timers one by one:

```bash
sudo systemctl disable --now man-db.timer 2>/dev/null || true
sudo systemctl disable --now e2scrub_all.timer 2>/dev/null || true
sudo systemctl disable --now fstrim.timer 2>/dev/null || true
```

Re-check the active timers afterward:

```bash
systemctl list-timers --all
```

8. Apply the changed mounts, restart the relevant services, and reboot once to validate the layout.

```bash
sudo mount -a
sudo systemctl daemon-reload
sudo systemctl restart systemd-journald
sudo systemctl restart mediamtx
sudo systemctl restart txing-board
sudo reboot
```

After reboot, verify the mount state and both services:

```bash
findmnt / /boot/firmware /tmp /var/tmp /var/log /var/cache /var/lib/NetworkManager
readlink -f /etc/resolv.conf
nmcli connection show --active
getent hosts google.com
sudo systemctl status mediamtx
sudo systemctl status txing-board
curl -sSf http://127.0.0.1:8889/board-cam/ >/dev/null
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
