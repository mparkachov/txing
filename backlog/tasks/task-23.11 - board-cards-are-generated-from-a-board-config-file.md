---
id: TASK-23.11
title: board cards are generated from a board config file
status: To Do
assignee: []
created_date: '2026-07-25 17:44'
labels: []
milestone: m-4
dependencies:
  - TASK-23.10
references:
  - release/scripts
  - shared/aws/deploy-init.example.json
  - rig/install-mise-tools.sh
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
Preparing a board card is undocumented operator practice today: after imaging Alpine, files are hand-placed on the boot partition to get the board onto wifi and reachable. No tooling for this exists in the repository. Make the card material a generated artifact of a per-board config file so bring-up is reproducible and a board can be re-imaged cheaply. Note this requires narrowing repository constraints that currently forbid automated privileged board provisioning; the constraint permitting it applies to initial installation only, and binary updates stay manual operator actions.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 A single operator command turns a board config file into the complete set of files to copy onto a freshly imaged Alpine card.
- [ ] #2 The generated card material configures wlan0-only networking, operator ssh access, board identity, and the board's AWS credentials without further input.
- [ ] #3 A board config that is missing or malformed is rejected with a message naming the specific field at fault, before any output is written.
- [ ] #4 Generated card material is written outside version control and cannot be committed, since it carries private key material.
- [ ] #5 Repository constraints are updated to permit automated privileged provisioning for initial board installation only, leaving binary updates manual.
<!-- AC:END -->
