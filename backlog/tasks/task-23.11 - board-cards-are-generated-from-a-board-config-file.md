---
id: TASK-23.11
title: board cards are generated from a board config file
status: To Do
assignee: []
created_date: '2026-07-25 17:44'
updated_date: '2026-07-28 06:43'
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
- [ ] #1 A single operator command turns a board config file into the complete set of files to copy onto a freshly imaged Alpine card.
- [ ] #2 The generated card material configures hostname, wlan0-only networking, and operator ssh access for root without further input.
- [ ] #3 The card carries no AWS credentials, no daemon config, and no release material; those remain manual runbook steps performed over ssh.
- [ ] #4 A board config that is missing or malformed is rejected with a message naming the specific field at fault, before any output is written.
- [ ] #5 Generated card material is written outside version control and cannot be committed, since it carries the Wi-Fi passphrase.
- [ ] #6 Repository constraints are updated to permit automated privileged provisioning for base OS setup on initial installation only, leaving the mise step onward and binary updates manual.
<!-- AC:END -->
