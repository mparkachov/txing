---
id: doc-29
title: 'Constraints: cyberbrick Alpine board'
type: guide
created_date: '2026-07-15 07:33'
updated_date: '2026-07-21 19:55'
tags:
  - cyberbrick
  - alpine
  - constraints
---
# Constraints: cyberbrick Alpine board

Durable rules for building, shipping, and operating cyberbrick board software. These extend, and never relax, the repository-wide rules in `docs/agent-guidance/editing-boundaries.md` and unit's board contracts.

## ABI and toolchain

- Linkage policy is defined by the board-wide contract in doc-32 (Constraints: board musl static builds), which supersedes the original musl-dynamic-only rule that stood here: the Go daemon builds `CGO_ENABLED=0` static and the hardware worker links fully static musl (no `PT_INTERP` program header); the KVS master remains **dynamically linked against musl** and stock Alpine libcamera. CI must assert the linkage kind per binary (`release/scripts/assert-board-musl.sh`).
- All release binaries are built in the **single pinned Alpine version** declared in the cyberbrick daemon justfile. The justfile build image, the release workflow containers, and the runbook's on-device apk branch must name the same Alpine release; bumping it is one coordinated change across all three plus a new cyberbrick release.
- Dynamic linking couples the KVS master to the device's installed libraries: on-device `apk upgrade` and `mise upgrade` happen together in the same maintenance window, and a major Alpine release bump on the device requires a matching cyberbrick release built on that version first. The static daemon and hardware worker depend only on the kernel.
- The KVS master links apk's **upstream libcamera** (not the Raspberry Pi fork unit uses). The linked soname is asserted in builds; libcamera apk upgrades that change the soname require a rebuild/release.
- Source patches needed for musl or upstream-libcamera compatibility live only in `devices/cyberbrick/`; never patch `devices/unit/` for cyberbrick's benefit.

## Unit parity and divergence

- Phase-one cyberbrick behavior is unit parity; intentional divergence is limited to OS (Alpine), ABI (musl per doc-32), and init (OpenRC). Any other behavioral difference is a bug or a new planned milestone.
- The copied stack uses cyberbrick-owned identifiers throughout (binaries, sockets, config dirs, adapter IDs, proto packages `txing.cyberbrick.*`). Do not reuse unit identifiers, and do not text-edit generated proto stubs — regenerate them.
- The watch layer remains unit's Zephyr MCU firmware in this phase; cyberbrick declares unit's full capability set including `ble`.

## Operations

- OpenRC only (no systemd on the board); services are enabled via `rc-update add <service> default` and supervised with `supervise-daemon`. Stay close to stock Alpine: apk, ifupdown-ng + wpa_supplicant + udhcpc, chronyd.
- Read-only root is the steady state (fstab `ro` + tmpfs for volatile paths). All package, mise, config, and service changes happen inside an explicit writable-root window that ends with a return to read-only.
- Install and update remain **manual and operator-driven** (mise pull from immutable `cyberbrick-v*` GitHub releases); no auto-update mechanisms.
- Repository-wide gates apply unchanged: no automatic `git commit`, no mutating AWS commands from agents, no firmware flashing by agents.

## GitHub issue references

- [#62 — Alpine musl toolchain is proven for the cyberbrick board stack](https://github.com/mparkachov/txing/issues/62) (migrated from `TASK-22.1`)
- [#66 — cyberbrick board daemons build as musl-dynamic Alpine binaries](https://github.com/mparkachov/txing/issues/66) (migrated from `TASK-22.3`)
- [#70 — cyberbrick Alpine board runbook is complete](https://github.com/mparkachov/txing/issues/70) (migrated from `TASK-22.5`)
- [#72 — cyberbrick board reaches unit parity on hardware](https://github.com/mparkachov/txing/issues/72) (migrated from `TASK-22.6`)
- [#85 — cyberbrick board binaries align to the static-musl policy](https://github.com/mparkachov/txing/issues/85) (migrated from `TASK-23.3`)
