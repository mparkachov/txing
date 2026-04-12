# txing board

Python service for the device-side Raspberry Pi board that is power-switched by the MCU and reports runtime state to the shared `txing` Thing Shadow under `state.reported.board`.

This is not the same Raspberry Pi as `rig/`. The `rig/` Pi remains the BLE/AWS control node. This `board/` service is for the separate Pi mounted on the device itself.

`txing-board` is the only process that publishes `board.*` Thing Shadow updates. For video, it supervises a dedicated local sender helper and publishes coarse AWS WebRTC session state under `reported.board.video`.

The txing runtime now connects to AWS IoT Core over SigV4-authenticated MQTT over WebSockets using the standard AWS SDK credential chain. The intended project-local profile layout is `town`, `rig`, and `txing`, with `txing` assuming the stack output role `TxingRuntimeRoleArn`.

When the service is managed by `systemd`, run it as `root`. The board control consumes internal `state.desired.board.power=false` requests from the phase-1 `rig` runtime and requests a local system halt, which requires root privileges. The supervised video sender keeps using the board host's AWS SDK credential chain, and the generated service unit now loads both AWS and board runtime defaults from `config/aws.env`.

## Video runtime

Phase 1 board video is a headless AWS KVS WebRTC path:

- board camera and encoder
- repo-owned C++ KVS master sender command on the board
- `board-video-sender` adapter and state writer
- `txing-board` shadow publisher
- browser viewer at the SPA `/video` route

Important:

- This repo now ships the native sender in `board/kvs_master/`.
- `board-video-sender` remains a supervisor/state adapter around a child command configured through the board runtime `--video-sender-command` option.
- The native sender is a standalone C++ executable that captures with `libcamera`, encodes H.264 through the Raspberry Pi V4L2 hardware encoder, and feeds those encoded access units to AWS KVS WebRTC as master through the AWS WebRTC C SDK directly.

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
        },
        "video": {
          "status": "ready",
          "ready": true,
          "transport": "aws-webrtc",
          "session": {
            "viewerUrl": "https://example.cloudfront.net/video",
            "channelName": "txing-board-video"
          },
          "codec": {
            "video": "h264"
          },
          "viewerConnected": false,
          "lastError": null
        }
      }
    }
  }
}
```

Notes:

- `board.*` is owned by this subproject.
- `desired.board.power=false` is an internal one-shot shutdown request from the `rig` runtime. The board control clears that desired field on clean shutdown so the request does not persist across the next boot.
- `reported.board.power=false` is only a best-effort clean-shutdown update.
- `reported.board.wifi.online` reflects the board-side online status while the board OS is up and the board control is running.
- `reported.board.wifi.ipv4` and `reported.board.wifi.ipv6` are refreshed on each publish loop from the interface the OS selects for the default route in each address family.
- `reported.board.drive.leftSpeed` and `reported.board.drive.rightSpeed` expose the last applied tank-drive effort in the current provisional signed-percent range `[-100, 100]`.
- `reported.board.video.viewerConnected` is best-effort board-side viewer presence derived from sender events. The browser does not write it.
- Because this Pi can lose power abruptly through the MOSFET, consumers should not treat stale `power=true` or stale `wifi.online=true` as authoritative after a hard power cut.

## `cmd_vel` contract

Live motion control is out of band from Thing Shadow and uses the MQTT topic `txing/board/cmd_vel`.

This topic is a strict ROS `geometry_msgs/Twist` semantic contract:

- `linear.x` is forward body velocity in `m/s`
- `angular.z` is yaw rate in `rad/s`
- `linear.y`, `linear.z`, `angular.x`, and `angular.y` are unsupported on the current differential-drive board and must be `0`

The board converts `linear.x` and `angular.z` to tank-drive motor commands through standard differential-drive kinematics. Browser key-step behavior is not part of this contract; browser teleop and AI clients are equal producers of the same strict `Twist` meaning.

The board also reports the currently applied left and right track effort back into Thing Shadow under `state.reported.board.drive.*`. Those values are best-effort runtime state published by `txing-board`, so they can lag the instantaneous motor command slightly.

Temporary phase constants currently hardcoded in the board control:

- `TRACK_WIDTH_M = 0.28`
- `MAX_WHEEL_LINEAR_SPEED_MPS = 0.50`
- `MAX_SPEED = 100`

`txing-board` keeps `MAX_SPEED=100` as the reported/runtime percent-effort contract and maps that scale to the DRV8835 raw range `[-480, 480]` before writing hardware.

Default DRV8835 hardware settings in the board runtime:

- `BOARD_DRIVE_RAW_MAX_SPEED=480`
- `BOARD_DRIVE_PWM_HZ=20000`
- `BOARD_DRIVE_PWM_CHIP=0`
- `BOARD_DRIVE_LEFT_PWM_CHANNEL=0`
- `BOARD_DRIVE_RIGHT_PWM_CHANNEL=1`
- `BOARD_DRIVE_GPIO_CHIP=0`
- `BOARD_DRIVE_LEFT_DIR_GPIO=5`
- `BOARD_DRIVE_RIGHT_DIR_GPIO=6`
- `BOARD_DRIVE_LEFT_INVERTED=false`
- `BOARD_DRIVE_RIGHT_INVERTED=false`

Default stock Pololu shield mapping in this repo:

- PWM speed outputs: GPIO12 (left), GPIO13 (right)
- Direction outputs: GPIO5 (left), GPIO6 (right)

## Prerequisites

- Raspberry Pi OS Lite 64-bit with Python `3.12+` available as `python3`
- `git`, `just`, `pipx`, `uv`, `cmake`, `pkg-config`, and a native C/C++ toolchain
- `python3-lgpio` available on the board image for the `gpiozero` LGPIO pin factory
- native build packages for the AWS WebRTC C SDK dependencies: `build-essential`, `curl`, `libssl-dev`, `libcurl4-openssl-dev`, `liblog4cplus-dev`, `libsrtp2-dev`, `libusrsctp-dev`, `libwebsockets-dev`, and `zlib1g-dev`
- `libcamera-dev` for the in-process camera capture path
- `ca-certificates` for general HTTPS tooling on the board
- project-local AWS config files for the `town` source profile and the `txing` runtime profile
- AWS credentials for the board video sender with permission to use the KVS signaling channel as master
- a working Raspberry Pi camera stack with the modern `libcamera` pipeline and the Pi V4L2 H.264 encoder available
- hardware PWM enabled for GPIO12/GPIO13 with this line in `/boot/firmware/config.txt`:

```ini
dtoverlay=pwm-2chan,pin=12,func=4,pin2=13,func2=4
```

The board runtime and raw motor test helper must run as `root`.

`txing-board` now sets `LG_WD=/tmp/txing-lgpio` by default before initializing `gpiozero`/`lgpio` so notification FIFO files are created in a stable writable location under systemd. If needed, override with `LG_WD=/some/writable/path`.

## Manual Motor Bring-Up

Use raw DRV8835 units only for this helper (`[-480, 480]`, where `240` is approximately 50% duty):

```bash
cd /home/user/txing
sudo systemctl stop board
just board::motor-raw left=240 right=240
```

Timed run (auto-stop after one second):

```bash
cd /home/user/txing
just board::motor-raw left=240 right=240 duration=1
```

Explicit stop helper:

```bash
cd /home/user/txing
just board::motor-stop
sudo systemctl start board
```

## Fresh Setup From Raspberry Pi Imager

Use this order on a full board rebuild from a new SD card image:

1. Prepare the AWS stack outputs and txing runtime IAM access on the development machine.
2. Flash Raspberry Pi OS Lite with Raspberry Pi Imager and enable SSH plus Wi-Fi.
3. Boot the board, install local tools, and clone the repo to `/home/user/txing`.
4. Copy the project-local AWS config files from the development machine to `/home/user/txing/config`.
5. Install the native sender build prerequisites and build the KVS master sender on the board.
6. Verify the `txing` runtime profile resolves on the board.
7. Build the board runtime and run a foreground smoke test.
8. Install `board` as a `systemd` service and verify it survives a reboot.

Assumptions used below:

- the board login user is `user`
- the repo path on the board is `/home/user/txing`
- the board is reachable as `user@<board-host>`
- the AWS region is `eu-central-1`
- the signaling channel name is `txing-board-video`

If you use a different username, hostname, repo path, region, or channel name, replace those values consistently in the commands below.

### 1. Prepare AWS Artifacts on the Development Machine

If the AWS stack already exists and you only need the txing runtime artifacts:

```bash
cd /path/to/txing
just aws::describe
```

If this is a new AWS environment:

```bash
cd /path/to/txing
just aws::deploy <unique-cognito-prefix> <admin-email>
just aws::describe
```

Fetch the txing runtime and board video outputs you need:

```bash
aws cloudformation describe-stacks \
  --stack-name txing-iot \
  --region eu-central-1 \
  --query "Stacks[0].Outputs[?OutputKey=='BoardVideoViewerUrl' || OutputKey=='BoardVideoChannelName' || OutputKey=='TxingRuntimeRoleArn' || OutputKey=='TxingBootstrapManagedPolicyArn'].[OutputKey,OutputValue]" \
  --output table
```

Prepare the local config files the board will use:

- `config/aws.env` with `AWS_TXING_PROFILE=txing`
- `config/aws.credentials` with the `town` source credentials
- `config/aws.config` with `[profile txing]` assuming `TxingRuntimeRoleArn`

### 2. Flash and Boot the Board

In Raspberry Pi Imager:

- choose Raspberry Pi OS Lite
- choose the 64-bit image, not the 32-bit image
- set the hostname, username, password, Wi-Fi, locale, and enable SSH
- if you want to reuse the commands below exactly, set the username to `user`

After the first boot, connect over SSH:

```bash
ssh user@<board-host>
```

### 3. Install Local Tooling and Clone the Repo

```bash
sudo apt update
sudo apt dist-upgrade -y
sudo apt autoremove -y
sudo apt install -y \
  build-essential \
  ca-certificates \
  cmake \
  curl \
  g++ \
  git \
  just \
  libcamera-dev \
  libcurl4-openssl-dev \
  liblog4cplus-dev \
  libssl-dev \
  libsrtp2-dev \
  libusrsctp-dev \
  libwebsockets-dev \
  make \
  pipx \
  pkg-config \
  python3-lgpio \
  unzip \
  zlib1g-dev
sudo update-ca-certificates
pipx install uv
pipx ensurepath
```

Start a new shell so the `pipx` path is active, then clone the repository:

```bash
cd /home/user
git clone <your-txing-repo-url> txing
cd /home/user/txing
```

Install AWS CLI v2 from AWS's official Linux ARM installer:

```bash
uname -m
test "$(uname -m)" = "aarch64"
cd /tmp
curl "https://awscli.amazonaws.com/awscli-exe-linux-aarch64.zip" -o "awscliv2.zip"
unzip -q awscliv2.zip
sudo ./aws/install
aws --version
rm -rf /tmp/aws /tmp/awscliv2.zip
```

If `uname -m` is not `aarch64`, stop and reinstall a 64-bit Raspberry Pi OS image. AWS documents AWS CLI v2 support for 64-bit Linux ARM and the official Linux ARM installer uses the `awscli-exe-linux-aarch64.zip` package.

### 4. Copy Project-Local AWS Config to the Board

From the development machine:

```bash
ssh user@<board-host> 'install -d -m 0755 /home/user/txing/config'
scp \
  config/aws.env \
  config/aws.credentials \
  config/aws.config \
  user@<board-host>:/home/user/txing/config/
```

Back on the board, verify the config and the `txing` profile:

```bash
cd /home/user/txing
ls -l config
test -s config/aws.env
test -s config/aws.credentials
test -s config/aws.config
just aws-txing sts get-caller-identity
cd board
just check
```

### 5. Build the Native KVS Sender

Clone and build the AWS KVS WebRTC SDK once into the board working tree, then build the repo-owned sender against that local install:

```bash
cd /home/user/txing/board
pkg-config --modversion libcamera
just build-aws-sdk
just build-native
```

The local AWS SDK checkout, build tree, and install prefix live under:

```bash
/home/user/txing/board/aws-kvs-webrtc-sdk
```

By default the local AWS SDK checkout tracks upstream `main`. After that SDK build completes once, repeat `just build-native` for sender code changes. You only need to rerun `just build-aws-sdk` when you want to refresh the local SDK checkout/install, change the dependency mode, or rebuild from scratch. Use `just clean` first if you want to rebuild both the local AWS SDK install and the sender from scratch, and `just distclean` if you also want to remove the local AWS SDK checkout.

The resulting sender binary lives at:

```bash
/home/user/txing/board/kvs_master/build/txing-board-kvs-master
```

Dependency mode note for Raspberry Pi OS Trixie:

- AWS documents the system dependency path as `BUILD_DEPENDENCIES=OFF` with system `libopenssl=1.1.1x`, `libsrtp2<=2.5.0`, `libusrsctp<=0.9.5.0`, and `libwebsockets>=4.2.0`.
- Debian Trixie currently ships `libssl-dev 3.5.5`, `libsrtp2-dev 2.7.0`, `libusrsctp-dev 0.9.5.0`, and `libwebsockets-dev 4.3.5`.
- That means `libusrsctp-dev` and `libwebsockets-dev` fit AWS's documented window, but `libssl-dev` and `libsrtp2-dev` do not.
- This repo now defaults to the system-dependency path for the board-local AWS SDK build, so it will try to use the Debian-supplied OpenSSL, libsrtp2, usrsctp, and libwebsockets packages first.
- In that system-dependency path, the board build now forces the shared Debian OpenSSL libraries (`libssl.so` / `libcrypto.so`) instead of the static archives so OpenSSL security updates can come from normal OS package updates.
- If that path fails on your image, export `TXING_BOARD_KVS_USE_SYSTEM_DEPENDENCIES=OFF` before `just build-aws-sdk` to fall back to the vendored AWS dependency build.

The SDK clone/build recipes are configurable through these optional environment variables:

- `TXING_BOARD_AWS_KVS_WEBRTC_SDK_REPOSITORY`
- `TXING_BOARD_AWS_KVS_WEBRTC_SDK_REF`

If you leave `TXING_BOARD_AWS_KVS_WEBRTC_SDK_REF` unset, the local SDK checkout stays on the `main` branch instead of a detached tag checkout.

`just build-native` now only checks that the local SDK install exists. It does not rebuild the AWS SDK on every sender rebuild. Run `just build-aws-sdk` explicitly when you need to refresh that local SDK install.

You do not need to set sender regex environment variables for the repo sender. `board-video-sender` now recognizes these built-in markers by default:

- `TXING_KVS_READY`
- `TXING_VIEWER_CONNECTED clientId=<id> viewers=<n>`
- `TXING_VIEWER_DISCONNECTED clientId=<id> viewers=<n>`

`board-video-sender` also exports `BOARD_VIDEO_REGION` and `BOARD_VIDEO_CHANNEL_NAME` to the child automatically, so the native sender does not need those flags when it is started under the Python supervisor.

For TLS trust on the KVS signaling path, `board-video-sender` strips inherited CA override environment variables before launching the native sender, and `kvs_master` points the upstream AWS signaling client at a system PEM path compiled into the native binary. The default is `/etc/ssl/certs/Starfield_Services_Root_Certificate_Authority_-_G2.pem`, which matches the SDK's historical `cert.pem`. If you need a different system certificate on another distro or image, override the full path during native build with `TXING_BOARD_KVS_SYSTEM_CA_CERT_PATH=/path/to/system-ca.pem just build-native`. You do not need repo-local AWS root CA files or IoT-specific certificate files for the txing runtime bootstrap.

### 6. Verify the `txing` Runtime Profile

The txing runtime and the supervised sender both use the standard AWS SDK chain. The generated service unit loads `config/aws.env` via `EnvironmentFile=`, so `AWS_REGION`, `AWS_TXING_PROFILE`, `AWS_SHARED_CREDENTIALS_FILE`, `AWS_CONFIG_FILE`, `THING_NAME`, `SCHEMA_FILE`, `BOARD_VIDEO_VIEWER_URL`, `BOARD_VIDEO_REGION`, `BOARD_VIDEO_CHANNEL_NAME`, `BOARD_VIDEO_SENDER_COMMAND`, and `KVS_DUALSTACK_ENDPOINTS` all come from the shared project-local config by default. It also sets `LG_WD` (default `/tmp/txing-lgpio`) for the `lgpio` notify FIFO workspace.

Verify the intended txing identity before installing the service:

```bash
cd /home/user/txing
just aws-txing sts get-caller-identity
```

If you want the install recipe to use credential files outside the checkout, pass `aws_shared_credentials_file=` and `aws_config_file=` directly to `just board::install-service`. To override the lgpio workspace path, pass `lg_wd=/some/writable/path`.

### 7. Build and Smoke Test

Set the board runtime defaults in `config/aws.env`, especially:

- `THING_NAME`
- `SCHEMA_FILE`
- `BOARD_VIDEO_VIEWER_URL`
- `BOARD_VIDEO_REGION`
- `BOARD_VIDEO_CHANNEL_NAME`
- `BOARD_VIDEO_SENDER_COMMAND`
- `KVS_DUALSTACK_ENDPOINTS=ON` to enable dual-stack KVS WebRTC endpoints for the native sender and allow IPv6 candidate gathering when the network supports it

Build the board runtime:

```bash
cd /home/user/txing
python3 --version
just board::build
```

`just board::build` is the normal install step for the Python board runtime. It creates or updates `board/.venv/` from the OS `python3` on `PATH` and installs the packaged entry points there. You do not need to run `sync` first for deployment.

Run a one-shot foreground publish using the same user that will later install the service:

```bash
cd /home/user/txing/board
sudo ./.venv/bin/board \
  --once \
  --video-viewer-url "$BOARD_VIDEO_VIEWER_URL" \
  --video-region eu-central-1 \
  --video-channel-name txing-board-video \
  --video-sender-command "$BOARD_VIDEO_SENDER_COMMAND"
```

What this proves:

- the txing runtime can resolve AWS region, credentials, and the IoT Data-ATS endpoint from the shared config flow
- the sender can resolve the signaling channel in AWS
- the sender command starts successfully
- `txing-board` can publish the initial `reported.board.video` payload

If the command exits with a video startup timeout or an AWS KVS permission error, fix that before moving on to the service install.

### 8. Install as a `systemd` Service

From the repo root on the board:

```bash
cd /home/user/txing
just board::build
just board::install-service \
  video_viewer_url="$BOARD_VIDEO_VIEWER_URL" \
  video_sender_command="$BOARD_VIDEO_SENDER_COMMAND"
```

If the root AWS credentials are stored elsewhere or you need a different region or channel:

```bash
cd /home/user/txing
just board::install-service \
  thing_name=txing \
  schema_file=docs/txing-shadow.schema.json \
  video_viewer_url="$BOARD_VIDEO_VIEWER_URL" \
  video_region=eu-central-1 \
  video_channel_name=txing-board-video \
  video_sender_command="$BOARD_VIDEO_SENDER_COMMAND" \
  aws_shared_credentials_file=/path/to/credentials \
  aws_config_file=/path/to/config
```

The generated unit:

- enables `NetworkManager-wait-online.service`
- waits for `systemd-time-wait-sync.service` / `time-sync.target` before startup
- runs `board` as `root`
- sets `WorkingDirectory=/home/.../txing` and loads `config/aws.env` through `EnvironmentFile=`
- sets `LG_WD=/tmp/txing-lgpio` by default and creates that directory during install (override with `lg_wd=...`)
- only adds `Environment=` overrides for board or AWS values when you pass explicit `just board::install-service ...` overrides
- starts `board` with `ExecStart=/home/.../board/.venv/bin/board --heartbeat-seconds 60`

The Python service also waits up to `120 s` for `timedatectl` to report `SystemClockSynchronized=yes` before it starts the AWS-backed video sender. That avoids transient KVS `InvalidSignatureException` failures after boot when networking is up but NTP has not corrected the clock yet.

If you also need sender regex environment variables in the service, add `Environment=` lines to `/etc/systemd/system/board.service`, then run `sudo systemctl daemon-reload && sudo systemctl restart board`.

### 9. Verify and Reboot

Check status and logs:

```bash
sudo systemctl status board
sudo journalctl -u board -f
```

The unit file should now contain the sender command and the published viewer URL:

```bash
sudo systemctl cat board
```

Reboot and verify again:

```bash
sudo reboot
```

After the board comes back:

```bash
ssh user@<board-host>
sudo systemctl status board
sudo journalctl -u board -n 100 --no-pager
```

## Useful foreground commands

From `board/`:

```bash
uv run board --help
uv run board-video-sender --help
uv run board --once --video-viewer-url "$BOARD_VIDEO_VIEWER_URL"
./kvs_master/build/txing-board-kvs-master --help
```

Useful board options:

- `--thing-name <thing>`
- `--video-viewer-url <https-url>`
- `--video-region <aws-region>`
- `--video-channel-name <channel-name>`
- `--video-startup-timeout-seconds <seconds>`
- `--board-name <name>`

Useful sender options:

- `--region <aws-region>` or `BOARD_VIDEO_REGION`
- `--channel-name <channel-name>` or `BOARD_VIDEO_CHANNEL_NAME`
- `--client-id <id>`
- `--camera <index>`
- `--width <pixels>`
- `--height <pixels>`
- `--framerate <fps>`
- `--bitrate <bps>`
- `--intra <frames>`
