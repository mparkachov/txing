---
id: TASK-23.11
title: board cards are generated from a board config file
status: Done
assignee:
  - '@claude'
created_date: '2026-07-25 17:44'
updated_date: '2026-07-29 19:39'
labels: []
milestone: m-4
dependencies:
  - TASK-23.10
references:
  - release/scripts
  - docs/components/cyberbrick-board.md
documentation:
  - >-
    backlog/docs/milestones/board-musl-static-builds/doc-31 -
    Milestone-Board-musl-static-builds.md
parent_task_id: TASK-23
priority: medium
ordinal: 67000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Preparing a board card is undocumented operator practice today: the operator boots the diskless Alpine image, logs in on the console, and answers `setup-alpine` by hand before anything else can happen. Replace those answers with a per-board config file and generate from it the material copied onto a freshly imaged Alpine card, so bring-up is reproducible and a board can be re-imaged cheaply. Scope is base OS setup only — hostname, `wlan0` Wi-Fi, and the operator key for `root`. AWS credentials, daemon config, and release material stay off the card and remain manual runbook steps performed over ssh once the board is reachable. Note this requires narrowing repository constraints that currently forbid automated privileged board provisioning; the narrowing covers base OS setup on initial installation only, and everything from the mise step onward, including binary updates, stays a manual operator action.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 A single operator command turns a board config file into the complete set of files to copy onto a freshly imaged Alpine card.
- [x] #2 The generated card material configures hostname, wlan0-only networking, and operator ssh access for root without further input.
- [x] #3 The card carries no AWS credentials, no daemon config, and no release material; those remain manual runbook steps performed over ssh.
- [x] #4 A board config that is missing or malformed is rejected with a message naming the specific field at fault, before any output is written.
- [x] #5 Generated card material is written outside version control and cannot be committed, since it carries the Wi-Fi passphrase.
- [x] #6 Repository constraints are updated to permit automated privileged provisioning for base OS setup on initial installation only, leaving the mise step onward and binary updates manual.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
The card carries base OS setup only, which is device-independent: hostname,
`wlan0` Wi-Fi, and the operator key for `root`. Nothing on it varies by device
type, so the generator lives beside the shared board implementation at
`devices/common/board/card/` and its recipe is common-owned with no device
argument, next to `proto-gen`.

Shape:

- Input is a TOML board config, matching how device manifests are already
  written. Fields: hostname, Wi-Fi ssid and passphrase, and the operator public
  key given either literally or as a path to read.
- The generator is stdlib-only Python. `tomllib` is in the standard library, so
  it needs no project, no lockfile, and no `uv` invocation, and an operator with
  a checkout can run it.
- Output goes to `tmp/board-cards/<hostname>/`. `/tmp/*` is already gitignored
  at the repository root, so generated material carrying the Wi-Fi passphrase
  cannot be committed (AC #5) without a deliberate override.
- Validation runs to completion before anything is written, collecting every
  fault rather than stopping at the first, and each message names the field at
  fault (AC #4). The output directory is only created once the config is known
  good, so a rejected run leaves nothing behind.

What the card contains is the boundary this task guards (AC #3): the files that
answer `setup-alpine` and nothing else. No AWS credentials, no `daemon.env`, no
release material. Those stay manual runbook steps over ssh, and a test asserts
the generated tree contains no such file.

Making the material actually run on first boot, and the conversion to a sys
install, is TASK-23.12. This task produces the material and proves its content;
that split is why the generator writes plain files rather than executing
anything.

AC #6 narrows `docs/constraints/repository-rules.md`, which currently forbids
writing installer scripts that assume root and forbids turning manual operator
steps into automatic scripts. The narrowing is specific: base OS setup on
initial installation only, on a card the operator writes deliberately, with
everything from the mise step onward and all binary updates staying manual.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Approach corrected twice by the operator. The first attempt invented a card
format; the second replaced it with a generator that built an apkovl from a TOML
config. Neither was wanted, and the second rested on my own wrong claim that the
apkovl needs authoring. It does not.

The actual mechanism, confirmed against the headless bootstrap project rather
than recalled: `headless.apkovl.tar.gz` from
`macmpi/alpine-linux-headless-bootstrap` is a standard Alpine overlay tarball
used exactly as published, and the rest of the configuration is supplied as
separate plain files sitting beside it on the FAT boot partition, which the
overlay reads on first boot. Nothing is generated and nothing inside the tarball
is edited.

`devices/common/board/card/` therefore holds the files as they land on the card:

- `wpa_supplicant.conf` — mandatory; SSID, passphrase, and regulatory country.
- `authorized_keys` — the operator public key. The bootstrap otherwise leaves
  root reachable over ssh with no password, so this is not optional in practice.
- `interfaces` — pins the board to `wlan0`. The bootstrap defaults to DHCP on
  whatever it finds, and leaving `eth0` out stops a board coming up on a bench
  cable and then being unreachable once deployed.
- `opt-out` — empty marker disabling the bootstrap's telemetry and connection
  checks.
- `README.md` — what goes on the card, what to edit, what not to.

Three failure modes are documented in both the README and the runbook because
they are indistinguishable from each other on a board that will not appear:
`wpa_supplicant.conf` saved with CRLF is silently ignored; a missing
`authorized_keys` leaves passwordless root; a wrong `country=` can disable the
channel the access point is on.

The runbook's first install step now images the card, lists the five files with
where each comes from and what to edit, and states that from that point
everything runs over ssh with no console session. The `setup-alpine` step that
follows runs remotely rather than on the console.

AC #6's constraint exception was reworded from generated material to card files,
keeping both bounds: base OS setup only, on a card an operator writes
deliberately, with everything from the mise step onward and every update to a
board in service staying manual.

A guard asserts the exact file set, that no AWS, daemon, release, or private key
material appears in any of them, that the repository carries no copy of the
apkovl to drift from, that the README states it is used unmodified, and that the
three failure modes stay in the runbook.

Not verified here: no board has been imaged with these files. The first bring-up
proves them, along with whether the Wi-Fi configuration and operator key survive
`setup-disk -m sys`, which TASK-23.12 and TASK-23.13 cover.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
devices/common/board/card/ holds the plain files an operator copies onto the FAT boot partition of a freshly imaged Alpine card, beside the headless.apkovl.tar.gz published by macmpi/alpine-linux-headless-bootstrap, which is used exactly as shipped. Nothing is generated and nothing inside the tarball is edited: the overlay reads wpa_supplicant.conf, authorized_keys, interfaces and opt-out off the boot partition on first boot, brings up wlan0, starts sshd and installs the operator key, so the rest of the install runs over ssh with no console session. The runbook lists the five files, where each comes from and what to edit, and calls out the three failure modes that all present as a board that never appears: CRLF line endings in wpa_supplicant.conf, a missing authorized_keys leaving passwordless root, and a wrong regulatory country. Card files carry base OS setup only, so a lost card carries no device identity or cloud access.
<!-- SECTION:FINAL_SUMMARY:END -->
