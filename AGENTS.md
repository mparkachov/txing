# txing agent guide

## Repository structure
- `devices/unit/mcu/`: Rust firmware subproject for the current `unit` device type MCU.
- `rig/`: Python subproject for the Raspberry Pi 5 rig runtime (AWS IoT MQTT + BLE communication with MCU).
- `devices/unit/board/`: Python subproject for the current `unit` device-side Raspberry Pi board control (AWS IoT MQTT shadow control/reporting).
- `web/`: React/Vite SPA for admin management of Thing Shadow.

## Working rules
- Treat this repository as a monorepo with the subprojects above.
- Keep changes scoped to the relevant subproject.
- Do not perform `git commit` automatically.
- Create commits only when explicitly requested by the user.
- Flashing/programming firmware onto hardware must only be performed manually by the user. Agents may prepare artifacts and commands, but must not run flashing steps automatically.

## Task tracking
Use `bd` for task tracking and execution state.

Rules:
- Treat Beads as the source of truth for active work. Do not rely on Codex task management, `update_plan`, or markdown checklists as a substitute for Beads status, sequencing, or dependency tracking.
- Do not keep active implementation plans only in markdown.
- When `/plan` produces actionable work, convert it into a Beads epic with child tasks before implementation starts.
- When `/plan` creates an epic, copy the approved plan summary into the epic description so the Beads record captures the implementation intent, constraints, and scope.
- When creating implementation issues, include a description with the concrete scope, constraints, and intended approach. Do not create bare-title issues when the work needs implementation detail; use the issue description and design fields to capture that context.
- Before starting implementation, make sure the work has a Beads issue. Use a Beads epic only for `/plan`-driven work that is being broken down into multiple actionable tasks; otherwise a standalone Beads task/bug/feature is sufficient.
- Before starting implementation, run `bd ready`.
- Claim the task you are working on with `bd update <id> --claim`.
- Record dependencies with `bd dep add`.
- Keep implementation tasks open through review and follow-up adjustments. Do not close them just because local code changes are done.
- When a commit is the completion point, put the task IDs in a `Beads-Close:` commit trailer, for example `Beads-Close: txing-123 txing-123.1`; the repo `post-commit` hook closes those Beads issues after the commit succeeds.
- If no commit is being made yet, leave the Beads task open. For non-code/admin work with no commit, close the task manually in Beads with a short resolution note once the user confirms completion.
- Keep Beads workflow rules centralized in this file. Subproject `AGENTS.md` files should reference these shared rules instead of duplicating them.
- Keep `AGENTS.md` focused on stable instructions, not transient task lists.

## Shared contracts
- Thing Shadow schema source of truth for the current `unit` device type: `devices/unit/aws/shadow.schema.json`.
- Current rig-era shadow + BLE compatibility contract: `devices/unit/docs/device-rig-shadow-spec.md`.
- Sparkplug lifecycle design: `docs/sparkplug-lifecycle.md`.
- Ownership rule: `rig` owns the `mcu.*` shadow subtree contract.
- Ownership rule: `board` owns the `board.*` shadow subtree contract.
- Ownership rule: `rig` owns the reflected top-level `video.*` shadow subtree contract.

## Board Video
- Board video is a headless network-service design. Do not assume any GUI, local browser, or desktop session on the board.
- `txing-board` remains the only publisher of `board.*` Thing Shadow updates.
- `rig` reflects top-level `video.*` into shadow from retained MQTT video service topics; `txing-board` does not publish video state into the Thing Shadow directly.
- The current implementation uses plain AWS KVS WebRTC signaling as the live operator video path.
- `board.video_sender` writes local runtime state and probes supervised sender readiness; `board.video_service` publishes retained video descriptor/status topics for `rig`.
- The browser operator path uses the AWS KVS viewer flow, not a board-local iframe page.
- The repo ships the native sender in-tree and supervises it as a child process from `board.video_sender`.
- Browser-to-board motion control currently stays out of the media path on `<device_id>/board/cmd_vel`.

## Terminology
- `power=true` means the device is in the wakeup state.
- `power=false` means the device is in the sleep state.
- In the sleep state, the MCU stays in RTC-driven low-power idle between periodic rendezvous wakeups.
- The sleep-state rendezvous interval is every `5 s`: the MCU wakes briefly, refreshes BLE state, advertises for a bounded window, and returns to low-power idle if no BLE session is needed.
- Use `wakeup state` / `sleep state` when describing the external device power contract. Distinguish that from the firmware's internal `Wake` step inside the sleep-state rendezvous cycle.
