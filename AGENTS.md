# txing agent guide

## Repository structure
- `mcu/`: Rust firmware subproject for the MCU.
- `rig/`: Python subproject for the Raspberry Pi 5 rig runtime (AWS IoT MQTT + BLE communication with MCU).
- `board/`: Python subproject for the device-side Raspberry Pi board control (AWS IoT MQTT shadow control/reporting).
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
- Before starting implementation, make sure the work is attached to an open Beads epic. If no epic exists yet, create it first and then create the implementation task under that epic.
- Before starting implementation, run `bd ready`.
- Claim the task you are working on with `bd update <id> --claim`.
- Record dependencies with `bd dep add`.
- Keep implementation tasks open through review and follow-up adjustments. Do not close them just because local code changes are done.
- When a commit is the completion point, put the task IDs in a `Beads-Close:` commit trailer, for example `Beads-Close: txing-123 txing-123.1`; the repo `post-commit` hook closes those Beads issues after the commit succeeds.
- If no commit is being made yet, leave the Beads task open. For non-code/admin work with no commit, close the task manually in Beads with a short resolution note once the user confirms completion.
- Keep `AGENTS.md` focused on stable instructions, not transient task lists.

## Shared contracts
- Thing Shadow schema source of truth: `docs/txing-shadow.schema.json`.
- Current rig-era shadow + BLE compatibility contract: `docs/device-rig-shadow-spec.md`.
- Sparkplug phase-1 target lifecycle design: `docs/sparkplug-phase1-design.md`.
- Ownership rule: `rig` owns the `mcu.*` shadow subtree contract.
- Ownership rule: `board` owns the `board.*` shadow subtree contract.

## Board Video Phase 1
- Phase 1 board video is a headless network-service design. Do not assume any GUI, local browser, or desktop session on the board.
- `txing-board` remains the only publisher of `board.*` Thing Shadow updates.
- Phase 1 uses plain AWS KVS WebRTC signaling as the live operator video path.
- `board.video_sender` writes local runtime state and probes supervised sender readiness, but it does not publish to AWS IoT directly.
- The browser operator path uses the AWS KVS viewer flow, not a board-local iframe page.
- The repo supervises an externally configured native sender command rather than embedding the full media pipeline directly.
- Browser-to-board motion control currently stays out of the media path on `txing/board/cmd_vel`.

## Terminology
- `power=true` means the device is in the wakeup state.
- `power=false` means the device is in the sleep state.
- In the sleep state, the MCU stays in RTC-driven low-power idle between periodic rendezvous wakeups.
- The sleep-state rendezvous interval is every `5 s`: the MCU wakes briefly, refreshes BLE state, advertises for a bounded window, and returns to low-power idle if no BLE session is needed.
- Use `wakeup state` / `sleep state` when describing the external device power contract. Distinguish that from the firmware's internal `Wake` step inside the sleep-state rendezvous cycle.
