---
id: doc-27
title: Cyberbrick device type architecture
type: specification
created_date: '2026-07-15 07:33'
updated_date: '2026-07-15 07:35'
tags:
  - cyberbrick
  - device-type
  - architecture
---
# Cyberbrick device type architecture

## Goal

Add a `cyberbrick` txing device type that is, in this phase, a functional copy of `unit`: the same Go daemon + KVS video master + hardware worker action layer on a Raspberry Pi Zero 2 W under a `raspi` rig, with the full REDCON 4-1 ladder, board/mcp/video shadows, and office visibility. The one deliberate difference is the board OS and ABI: cyberbrick boards run Alpine Linux (aarch64), all three daemons are dynamically linked against musl, services run under OpenRC, and the root filesystem is read-only — while keeping unit's manual workflow (manual initial setup, manual mise-based update, as close to stock Alpine as possible).

## Decisions

- Board OS: Alpine Linux aarch64 on Raspberry Pi Zero 2 W, **sys install** (`setup-disk -m sys`) with `/` mounted `ro` in fstab plus tmpfs mounts and a `root-rw`/`root-ro` maintenance workflow. Not diskless/lbu mode: sys mode preserves unit's maintenance model and keeps mise-installed binaries on disk.
- ABI: all three daemons dynamically linked against musl. The Go daemon is built with `CGO_ENABLED=1` and external linking inside an Alpine container (unit's Go daemon is CGO-free static); the C++ workers build in a pinned Alpine container against apk-provided libraries. CI and the runbook assert the `ld-musl-aarch64.so.1` interpreter and fully resolved shared libraries.
- Init: OpenRC init scripts (`supervise-daemon`) replace unit's systemd units; enablement via `rc-update add <svc> default` (no target-unit equivalent). Default Alpine stack otherwise: apk, ifupdown-ng + wpa_supplicant + udhcpc networking, chronyd time sync.
- Scope of the copy: board software only. `devices/unit/mcu/` is not copied; the watch-layer MCU remains unit's Zephyr firmware for this phase. The manifest keeps full unit parity (capabilities incl. `ble`, REDCON rules, `raspi` rig compatibility).
- Code reuse: copy-and-rename, following the mac precedent (doc-23) — Go `internal/` packages cannot be shared across modules and per-type divergence is expected later. Proto packages are renamed to `txing.cyberbrick.*` and stubs regenerated (never sed-edited); the gRPC contracts are private per-device unix-socket surfaces, so no wire compatibility is lost.
- Release artifacts keep the repo-wide asset shape `txing-cyberbrick-*-linux-aarch64.tar.gz` under a new immutable `cyberbrick-v*` tag prefix; the component name plus CI ldd assertions carry the musl/Alpine meaning, so no `-musl` suffix.

## Device type contract

`devices/cyberbrick/manifest.toml`:

- `type = "cyberbrick"`, `device_name = "cyberbrick"`, `display_name = "Cyberbrick"`
- `capabilities = ["sparkplug", "ble", "power", "board", "mcp", "video"]`
- `compatible_rig_types = ["raspi"]`, `redcon_command_levels = [4, 3, 2, 1]` with unit's redcon_rules
- `[shadows.<name>]` schema/default for every declared capability
- `[web] adapter = "web/cyberbrick-adapter.tsx"`, `[resources.board_video] channel_name = "{device_id}-board-video"`

The type catalog is triple-sourced and all three must stay in sync:

1. `devices/cyberbrick/manifest.toml`
2. `CyberbrickTypeCatalogV2` in `shared/aws/template.yaml` (`CatalogBasePath: /txing/town/raspi/cyberbrick`)
3. the device-type tuple in `shared/aws/python/src/aws/type_catalog.py` `build_type_records`

Certificate bundles need a `deviceType:cyberbrick` dispatch in `shared/aws/scripts/aws_lib.sh` via the existing `txing_cert_generate_device_daemon_bundle` (bundle type `cyberbrick-daemon`, rendered `devices/cyberbrick/daemon/daemon.env.template`), with the template path passed through the `shared/aws` justfile cert recipe. The office registers the adapter in `office/src/device-registry.ts`.

## Runtime shape

Identical to unit (see `docs/components/board.md` and `docs/contracts/unit-hardware-worker.md`), with renamed identifiers:

- Binaries/tools: `txing-cyberbrick-daemon`, `txing-cyberbrick-kvs-master`, `txing-cyberbrick-hardware-worker` (Go module `github.com/mparkachov/txing/devices/cyberbrick/daemon`).
- Adapter ID `dev.txing.cyberbrick.Daemon`; config dir `/root/.config/txing/cyberbrick-daemon/`.
- Sockets: `/run/txing-cyberbrick-daemon/{board-video-bridge,mcp-webrtc}.sock`, `/run/txing-cyberbrick-hardware-worker/cyberbrick-hardware.sock`.
- Proto packages `txing.cyberbrick.hardware.v1` (service `CyberbrickHardware`) and `txing.cyberbrick.board_video.v1`; C++ namespace `txing::cyberbrick`.
- Generic env keys (`TXING_MOTOR_*`, `TXING_BOARD_VIDEO_*`, ...) keep their names; only unit-specific path values change.

## Build and release shape

- Just recipes mirror unit's but swap the `debian:trixie` build container for a pinned Alpine aarch64 container (`kvs-build-alpine`, `hardware-build-alpine`, `docker-build` with the Go build inside the container). No Raspberry Pi apt repo: libcamera and all C++ dependencies come from apk (upstream libcamera, not the RPi 0.7 fork — the linked soname is asserted from the toolchain spike's finding).
- `.github/workflows/release-cyberbrick.yml` mirrors `release-unit.yml`: manual dispatch, `ubuntu-24.04-arm` runners with Alpine containers, immutable `cyberbrick-v*` releases, single-root-entry tar assertion, musl interpreter + resolved-libraries + libcamera ldd assertions.
- Release tooling: `release/versions/cyberbrick`, cyberbrick version surfaces (Go version.go + two C++ version.hpp), and a `cyberbrick` component in `release/src/txing_release/cli.py` and `release/justfile`.

## Board OS shape (Alpine)

- Fresh install: Alpine aarch64 Raspberry Pi image, `setup-alpine`, `setup-disk -m sys`; default networking (ifupdown-ng + wpa_supplicant + udhcpc) and chronyd.
- Daemons install via root-owned mise (static musl binary) from GitHub Releases: `/root/.config/mise/conf.d/txing-cyberbrick-daemon.toml`, `version_prefix = "cyberbrick-v"`.
- OpenRC services `/etc/init.d/txing-cyberbrick-{hardware-worker,daemon,kvs-master}`: `supervise-daemon`, `depend()` on net/dns, chronyd wait-sync guard, `checkpath` runtime dirs, env-file sourcing for the hardware worker; start order hardware-worker -> daemon -> kvs-master.
- PWM overlay `dtoverlay=pwm-2chan,pin=12,func=4,pin2=13,func2=4` on the boot FAT partition.
- Read-only root: fstab `/` ext4 `ro,noatime` + boot FAT `ro`; tmpfs `/tmp`, `/var/tmp`, `/var/log`, `/var/lib/chrony`; udhcpc `RESOLV_CONF=/run/resolv.conf` with `/etc/resolv.conf` symlinked; `root-rw`/`root-ro` aliases.
- Update workflow parity with unit: during a writable-root window, `apk upgrade` + `mise upgrade` together, verify versions and ldd, reboot. Dynamic musl linking couples device runtime packages to the build container's Alpine branch — see the constraints doc.

## Registration runbook

Once per stack: `just aws::deploy` (ships the cyberbrick thing type and SSM catalog). Per device: `just aws::deploy-device <raspi-rig-id> cyberbrick <name>`, `just aws::cert <thing-id>` (cyberbrick-daemon bundle), shadow inits, then the board runbook (`docs/components/cyberbrick-board.md`).

## Risks

1. Video stack on Alpine is the top functional risk: apk libcamera is upstream (different soname/API than the RPi fork) and the `bcm2835-codec` V4L2 H.264 encoder is a downstream RPi kernel driver that Alpine's `linux-rpi` may not ship. A toolchain/kernel spike runs first; acceptable phase outcome is build-verified video with a documented degraded state on hardware and a follow-up task.
2. apk availability of usrsctp/log4cplus is unconfirmed; fallbacks are the KVS SDK's bundled usrsctp and a source-built log4cplus confined to the build container.
3. musl compile breaks in the pinned KVS WebRTC SDK (glibc-isms); patches stay confined to cyberbrick's copy.
4. Rename collateral from the unit copy: token-specific renames plus residual grep review; proto stubs are regenerated, never text-edited.

## Non-goals

Cyberbrick-specific MCU firmware (watch layer stays unit's Zephyr firmware), any behavior change relative to unit beyond the OS/ABI/init swap, changes to unit/rig/office internals, consolidation of shared daemon code into `devices/common/`, and automated fleet updates (workflow stays manual by design).
