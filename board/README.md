# txing board

Python service for the device-side Raspberry Pi board that is power-switched by the MCU and reports runtime state to the shared `txing` Thing Shadow under `state.reported.board`.

This is not the same Raspberry Pi as `gw/`. The `gw/` Pi remains the BLE/AWS gateway. This `board/` service is for the separate Pi mounted on the device itself.

`txing-board` is the only process that publishes `board.*` Thing Shadow updates. For video, it supervises a dedicated local sender helper and publishes coarse AWS WebRTC session state under `reported.board.video`.

The board reuses the same AWS IoT mTLS certificate files as `gw/`, stored in `../certs/` as `txing.cert.pem` and `txing.private.key`.

When the service is managed by `systemd`, run it as `root`. The board control consumes `state.desired.board.power=false` and requests a local system halt, which requires root privileges. The supervised video sender resolves AWS credentials from `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` first and otherwise falls back to the shared credentials file for the active profile, so the simplest service setup is to keep the sender credentials in the root account's AWS files unless you override the credential file paths in the generated unit.

## Video runtime

Phase 1 board video is a headless AWS KVS WebRTC path:

- board camera and encoder
- repo-owned C++ KVS master sender command on the board
- `board-video-sender` adapter and state writer
- `txing-board` shadow publisher
- browser viewer at the SPA `/video` route

Important:

- This repo now ships the native sender in `board/kvs_master/`.
- `board-video-sender` remains a supervisor/state adapter around a child command exposed through `TXING_BOARD_VIDEO_SENDER_COMMAND`.
- The native sender is a standalone C++ executable that spawns `rpicam-vid`, parses inline H.264 Annex-B access units, and feeds them to AWS KVS WebRTC as master through the AWS WebRTC C SDK directly.

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
- `desired.board.power=false` is a one-shot shutdown request. The board control clears that desired field on clean shutdown so the request does not persist across the next boot.
- `reported.board.power=false` is only a best-effort clean-shutdown update.
- `reported.board.wifi.online` reflects the board-side online status while the board OS is up and the board control is running.
- `reported.board.wifi.ipv4` and `reported.board.wifi.ipv6` are refreshed on each publish loop from the interface the OS selects for the default route in each address family.
- `reported.board.video.viewerConnected` is best-effort board-side viewer presence derived from sender events. The browser does not write it.
- Because this Pi can lose power abruptly through the MOSFET, consumers should not treat stale `power=true` or stale `wifi.online=true` as authoritative after a hard power cut.

## Prerequisites

- Raspberry Pi OS Lite 64-bit with Python `3.12+` available as `python3`
- `git`, `just`, `pipx`, `uv`, `cmake`, `pkg-config`, and a native C/C++ toolchain
- native build packages for the AWS WebRTC C SDK dependencies: `build-essential`, `curl`, `libssl-dev`, `libcurl4-openssl-dev`, and `liblog4cplus-dev`
- AWS IoT endpoint, root CA, client certificate, and client private key
- AWS credentials for the board video sender with permission to use the KVS signaling channel as master
- a working Raspberry Pi camera stack with `/usr/bin/rpicam-vid`

The defaults expect shared repo cert material in `../certs/`:

- endpoint: `../certs/iot-data-ats.endpoint`
- certificate: `../certs/txing.cert.pem`
- private key: `../certs/txing.private.key`
- root CA: `../certs/AmazonRootCA1.pem`

## Fresh Setup From Raspberry Pi Imager

Use this order on a full board rebuild from a new SD card image:

1. Prepare the AWS stack outputs, IoT client files, and board video IAM access on the development machine.
2. Flash Raspberry Pi OS Lite with Raspberry Pi Imager and enable SSH plus Wi-Fi.
3. Boot the board, install local tools, and clone the repo to `/home/user/txing`.
4. Copy the four AWS IoT client files from the development machine to `/home/user/txing/certs`.
5. Install the native sender build prerequisites and build the KVS master sender on the board.
6. Configure AWS credentials for the sender in the same location the `systemd` service will use.
7. Build the board runtime and run a foreground smoke test.
8. Install `txing-board` as a `systemd` service and verify it survives a reboot.

Assumptions used below:

- the board login user is `user`
- the repo path on the board is `/home/user/txing`
- the board is reachable as `user@<board-host>`
- the AWS region is `eu-central-1`
- the signaling channel name is `txing-board-video`

If you use a different username, hostname, repo path, region, or channel name, replace those values consistently in the commands below.

### 1. Prepare AWS Artifacts on the Development Machine

If the AWS stack already exists and you only need the board artifacts:

```bash
cd /path/to/txing
just aws::cert
just aws::endpoint
just aws::ca
just aws::describe
```

If this is a new AWS environment:

```bash
cd /path/to/txing
just aws::deploy <unique-cognito-prefix> <admin-email>
just aws::cert
just aws::endpoint
just aws::ca
just aws::describe
```

Fetch the board video outputs you need:

```bash
aws cloudformation describe-stacks \
  --stack-name txing-iot \
  --region eu-central-1 \
  --query "Stacks[0].Outputs[?OutputKey=='BoardVideoViewerUrl' || OutputKey=='BoardVideoChannelName' || OutputKey=='BoardVideoSenderManagedPolicyArn'].[OutputKey,OutputValue]" \
  --output table
```

The board needs these four files from the repo `certs/` directory:

- `txing.cert.pem`
- `txing.private.key`
- `AmazonRootCA1.pem`
- `iot-data-ats.endpoint`

The sender AWS credentials must be allowed to use the exported signaling channel as master. The stack exports `BoardVideoSenderManagedPolicyArn` for that purpose, but how you attach it depends on the IAM user or role you choose for the board.

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
sudo apt install -y build-essential cmake curl git g++ just libcurl4-openssl-dev liblog4cplus-dev libssl-dev make pipx pkg-config unzip
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

### 4. Copy AWS IoT Client Artifacts to the Board

From the development machine:

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

Back on the board, verify the files:

```bash
cd /home/user/txing
ls -l certs
test -s certs/txing.cert.pem
test -s certs/txing.private.key
test -s certs/AmazonRootCA1.pem
test -s certs/iot-data-ats.endpoint
```

### 5. Build the Native KVS Sender

Build the repo-owned sender:

```bash
cd /home/user/txing/board
just build-native
```

The resulting sender binary lives at:

```bash
/home/user/txing/board/kvs_master/build/txing-board-kvs-master
```

You do not need to set sender regex environment variables for the repo sender. `board-video-sender` now recognizes these built-in markers by default:

- `TXING_KVS_READY`
- `TXING_VIEWER_CONNECTED clientId=<id> viewers=<n>`
- `TXING_VIEWER_DISCONNECTED clientId=<id> viewers=<n>`

`board-video-sender` also exports `TXING_BOARD_VIDEO_REGION` and `TXING_BOARD_VIDEO_CHANNEL_NAME` to the child automatically, so the native sender does not need those flags when it is started under the Python supervisor.

### 6. Configure AWS Credentials for the Sender

The sender resolves credentials from environment variables first and otherwise falls back to the shared AWS credentials file for the active profile. The generated `systemd` unit runs as `root`, so the simplest path is to install the credentials in `/root/.aws/`.

Create the root AWS config directory:

```bash
sudo install -d -m 0700 /root/.aws
```

Copy or create the credentials and config files there:

```bash
sudo cp /path/to/credentials /root/.aws/credentials
sudo cp /path/to/config /root/.aws/config
sudo chmod 0600 /root/.aws/credentials /root/.aws/config
```

Verify the root account can resolve the intended identity:

```bash
sudo AWS_SHARED_CREDENTIALS_FILE=/root/.aws/credentials \
  AWS_CONFIG_FILE=/root/.aws/config \
  aws sts get-caller-identity
```

If you want the install recipe to use different credential paths, region, or channel defaults, export these variables before running `just board::install-service`:

- `TXING_BOARD_AWS_SHARED_CREDENTIALS_FILE`
- `TXING_BOARD_AWS_CONFIG_FILE`
- `TXING_BOARD_VIDEO_REGION`
- `TXING_BOARD_VIDEO_CHANNEL_NAME`

### 7. Build and Smoke Test

Get the published viewer URL from the stack output and export the sender command:

```bash
export BOARD_VIDEO_VIEWER_URL='https://<cloudfront-domain>/video'
export TXING_BOARD_VIDEO_SENDER_COMMAND=/home/user/txing/board/kvs_master/build/txing-board-kvs-master
```

Build the board runtime:

```bash
cd /home/user/txing
python3 --version
just board::build
```

Run a one-shot foreground publish using the same user that will later install the service:

```bash
cd /home/user/txing/board
sudo env \
  TXING_BOARD_VIDEO_SENDER_COMMAND="$TXING_BOARD_VIDEO_SENDER_COMMAND" \
  AWS_SHARED_CREDENTIALS_FILE=/root/.aws/credentials \
  AWS_CONFIG_FILE=/root/.aws/config \
  ./.venv/bin/board \
  --once \
  --video-viewer-url "$BOARD_VIDEO_VIEWER_URL" \
  --video-region eu-central-1 \
  --video-channel-name txing-board-video
```

What this proves:

- the board can load the shared AWS IoT mTLS files from `/home/user/txing/certs`
- the sender can resolve the signaling channel in AWS
- the sender command starts successfully
- `txing-board` can publish the initial `reported.board.video` payload

If the command exits with a video startup timeout or an AWS KVS permission error, fix that before moving on to the service install.

### 8. Install as a `systemd` Service

From the repo root on the board:

```bash
cd /home/user/txing
just board::install-service \
  "$BOARD_VIDEO_VIEWER_URL" \
  "$TXING_BOARD_VIDEO_SENDER_COMMAND"
```

If the root AWS credentials are stored elsewhere or you need a different region or channel:

```bash
cd /home/user/txing
export TXING_BOARD_AWS_SHARED_CREDENTIALS_FILE=/path/to/credentials
export TXING_BOARD_AWS_CONFIG_FILE=/path/to/config
export TXING_BOARD_VIDEO_REGION=eu-central-1
export TXING_BOARD_VIDEO_CHANNEL_NAME=txing-board-video
just board::install-service \
  "$BOARD_VIDEO_VIEWER_URL" \
  "$TXING_BOARD_VIDEO_SENDER_COMMAND"
```

The generated unit:

- enables `NetworkManager-wait-online.service`
- runs `txing-board` as `root`
- sets `TXING_BOARD_VIDEO_SENDER_COMMAND`
- starts `board` with `--video-viewer-url`, `--video-region`, and `--video-channel-name`

If you also need sender regex environment variables in the service, add `Environment=` lines to `/etc/systemd/system/txing-board.service`, then run `sudo systemctl daemon-reload && sudo systemctl restart txing-board`.

### 9. Verify and Reboot

Check status and logs:

```bash
sudo systemctl status txing-board
sudo journalctl -u txing-board -f
```

The unit file should now contain the sender command and the published viewer URL:

```bash
sudo systemctl cat txing-board
```

Reboot and verify again:

```bash
sudo reboot
```

After the board comes back:

```bash
ssh user@<board-host>
sudo systemctl status txing-board
sudo journalctl -u txing-board -n 100 --no-pager
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
- `--iot-endpoint <hostname>`
- `--cert-file <path>`
- `--key-file <path>`
- `--ca-file <path>`
- `--video-viewer-url <https-url>`
- `--video-region <aws-region>`
- `--video-channel-name <channel-name>`
- `--video-startup-timeout-seconds <seconds>`
- `--board-name <name>`

Useful sender options:

- `--region <aws-region>` or `TXING_BOARD_VIDEO_REGION`
- `--channel-name <channel-name>` or `TXING_BOARD_VIDEO_CHANNEL_NAME`
- `--client-id <id>`
- `--rpicam-vid-path </path/to/rpicam-vid>`
- `--camera <index>`
- `--width <pixels>`
- `--height <pixels>`
- `--framerate <fps>`
- `--bitrate <bps>`
- `--intra <frames>`
