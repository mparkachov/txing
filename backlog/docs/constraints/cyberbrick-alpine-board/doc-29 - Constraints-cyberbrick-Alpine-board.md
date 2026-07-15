---
id: doc-29
title: 'Constraints: cyberbrick Alpine board'
type: guide
created_date: '2026-07-15 07:33'
updated_date: '2026-07-15 07:35'
tags:
  - cyberbrick
  - alpine
  - constraints
---
# Constraints: cyberbrick Alpine board

Durable rules for building, shipping, and operating cyberbrick board software. These extend, and never relax, the repository-wide rules in `docs/constraints/repository-rules.md` and unit's board contracts.

## ABI and toolchain

- Every shipped cyberbrick binary targets aarch64 Linux and is **dynamically linked against musl**. Static linking (including CGO-free Go builds) is not an accepted substitute: CI must assert the `ld-musl-aarch64.so.1` interpreter and that `ldd` resolves every shared library.
- All release binaries are built in the **single pinned Alpine version** declared in the cyberbrick daemon justfile. The justfile build image, the release workflow containers, and the runbook's on-device apk branch must name the same Alpine release; bumping it is one coordinated change across all three plus a new cyberbrick release.
- Dynamic linking couples the binaries to the device's installed libraries: on-device `apk upgrade` and `mise upgrade` happen together in the same maintenance window, and a major Alpine release bump on the device requires a matching cyberbrick release built on that version first.
- The KVS master links apk's **upstream libcamera** (not the Raspberry Pi fork unit uses). The linked soname is asserted in builds; libcamera apk upgrades that change the soname require a rebuild/release.
- Source patches needed for musl or upstream-libcamera compatibility live only in `devices/cyberbrick/`; never patch `devices/unit/` for cyberbrick's benefit.

## Unit parity and divergence

- Phase-one cyberbrick behavior is unit parity; intentional divergence is limited to OS (Alpine), ABI (musl dynamic), and init (OpenRC). Any other behavioral difference is a bug or a new planned milestone.
- The copied stack uses cyberbrick-owned identifiers throughout (binaries, sockets, config dirs, adapter IDs, proto packages `txing.cyberbrick.*`). Do not reuse unit identifiers, and do not text-edit generated proto stubs — regenerate them.
- The watch layer remains unit's Zephyr MCU firmware in this phase; cyberbrick declares unit's full capability set including `ble`.

## Operations

- OpenRC only (no systemd on the board); services are enabled via `rc-update add <service> default` and supervised with `supervise-daemon`. Stay close to stock Alpine: apk, ifupdown-ng + wpa_supplicant + udhcpc, chronyd.
- Read-only root is the steady state (fstab `ro` + tmpfs for volatile paths). All package, mise, config, and service changes happen inside an explicit writable-root window that ends with a return to read-only.
- Install and update remain **manual and operator-driven** (mise pull from immutable `cyberbrick-v*` GitHub releases); no auto-update mechanisms.
- Repository-wide gates apply unchanged: no automatic `git commit`, no mutating AWS commands from agents, no firmware flashing by agents.
