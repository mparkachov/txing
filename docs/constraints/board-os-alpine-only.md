# Board OS: Alpine only, Debian frozen

Status: accepted, 2026-07-29.

Read this before adding, restoring, or repairing any Debian or systemd path for
a board.

## Decision

Boards run Alpine Linux with OpenRC. Debian receives no further investment: no
new Debian builds, no Debian release artifacts, no Debian-targeted fixes, and no
compatibility work to keep Debian boards interoperating with current ones. A
board still on Debian is reimaged to Alpine rather than upgraded, and the
remaining Debian material in the documentation is frozen history rather than a
supported path.

## Why

The choice was forced rather than preferred. The camera KVS master cannot be
linked statically and builds musl-dynamic against stock Alpine libcamera, so new
camera builds are Alpine-only. A Debian board is therefore pinned to the last
Debian-built KVS master and cannot take any subsequent board release. Every
change after that pin either skips the Debian board or has to be built twice.

Carrying Debian forward would mean maintaining a second toolchain, a second set
of release artifacts, and a second wire-compatibility story for the local gRPC
contracts, to keep a small number of boards on an OS the camera path had already
left. The cost is continuous and the benefit expires the moment those boards are
reimaged. Reimaging is a bounded, one-time operator task per board.

This also removes the last reason to keep compatibility shims in the board
implementation. One implementation, one OS, one protocol version in service.

## Consequences

- Board work targets Alpine only. Do not add Debian or systemd build paths,
  packaging, or CI lanes, and do not reintroduce a Debian container to any board
  recipe.
- The local gRPC contracts are free to change without a migration path for
  Debian boards, because there is no supported way for such a board to receive a
  build that speaks the current protocol. `txing.board.board_video.v1` and
  `txing.board.hardware.v1` superseded the per-device packages on exactly these
  terms.
- Debian and systemd instructions remain in the documentation as clearly frozen
  material, not current practice. `docs/components/board.md` carries that
  material today; consolidating and freezing it is TASK-23.10.
- A Debian board is out of service for the current protocol until it is
  reimaged. Reimaging the last one is gated by TASK-23.13 AC #3.
- Alpine version moves stay coordinated: the pinned build image, the release
  built on it, and the device apk branch move together, because the KVS master
  is dynamically linked against the installed Alpine libraries. See the
  maintenance section of the board runbook.

## Scope

This covers the board only. It says nothing about the rig, which is a separate
host with its own OS baseline, and nothing about the macOS development lane,
which builds the same shared sources through Homebrew.
