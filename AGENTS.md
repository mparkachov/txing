# txing agent guide

## Repository structure
- `devices/unit/mcu/`: Rust firmware subproject for the current `unit` device type MCU.
- `rig/`: Python subproject for the Raspberry Pi 5 rig runtime (AWS IoT MQTT + BLE communication with MCU).
- `devices/unit/board/`: Python subproject for the current `unit` device-side Raspberry Pi board control (AWS IoT MQTT shadow control/reporting).
- `web/`: React/Vite SPA for admin management of Thing Shadow.

## Working rules
- Treat this repository as a monorepo with the subprojects above.
- Keep changes scoped to the relevant subproject.
- `just` recipe arguments in this repository are positional. Do not invoke recipes with `name=value` syntax such as `just unit::daemon::cert thing_id=unit-bl95f2`; pass values positionally, for example `just unit::daemon::cert unit-bl95f2`.
- Do not read from, copy from, execute from, or depend on files outside this repository (`/Users/Maxim/Developer/txing`) unless the user explicitly provides the content in the conversation or explicitly asks to vendor it into the repository first.
- Do not run any command against AWS that could create, update, or delete cloud resources. Agents may run read-only AWS inspection commands only when needed.
- Prefer manual cleanup plus CloudFormation-forward changes over backward-compatible migration code. When existing AWS resources must be removed, renamed, imported, or otherwise reconciled, explain the required manual steps and let the user perform them.
- Prefer moving development to new functionality without preserving backward compatibility, except for protocols and protocol versions. Before making a change that drops or ignores backward compatibility, ask the user every time whether that is acceptable.
- After every code, firmware, infrastructure, or configuration change, explain the relevant deployment or rollout steps in the final response, including any manual steps the user must perform.
- Do not perform `git commit` automatically.
- Create commits only when explicitly requested by the user.
- Flashing/programming firmware onto hardware must only be performed manually by the user. Agents may prepare artifacts and commands, but must not run flashing steps automatically.

## Shared contracts
- Thing Shadow schema source of truth for the current `unit` device type: `devices/unit/aws/*-shadow.schema.json`.
- Current rig-era shadow + BLE compatibility contract: `devices/unit/docs/device-rig-shadow-spec.md`.
- Sparkplug lifecycle design: `docs/sparkplug-lifecycle.md`.
- Ownership rule: `rig` owns the `sparkplug`, `device`, and `mcu` named shadow contracts.
- Ownership rule: `board` owns the `board` named shadow contract.

## Board Video
- Board video is a headless network-service design. Do not assume any GUI, local browser, or desktop session on the board.
- `txing-board` remains the only publisher of `board.*` Thing Shadow updates.
- The current implementation uses plain AWS KVS WebRTC signaling as the live operator video path.
- `board.video_sender` writes local runtime state and probes supervised sender readiness; `board.video_service` publishes retained video descriptor/status topics for `rig`.
- `rig` consumes retained MQTT video service topics for REDCON derivation; `board` also mirrors video descriptor/status into the `video` named shadow for readers.
- The browser operator path uses the AWS KVS viewer flow, not a board-local iframe page.
- The repo ships the native sender in-tree and supervises it as a child process from `board.video_sender`.
- Browser-to-board motion control uses board MCP tools with a lease hard gate; the legacy raw `<device_id>/board/cmd_vel` path is removed.

## Terminology
- `power=true` means the device is in the wakeup state.
- `power=false` means the device is in the sleep state.
- In the sleep state, the MCU stays in RTC-driven low-power idle between periodic rendezvous wakeups.
- The sleep-state rendezvous interval is every `5 s`: the MCU wakes briefly, refreshes BLE state, advertises for a bounded window, and returns to low-power idle if no BLE session is needed.
- Use `wakeup state` / `sleep state` when describing the external device power contract. Distinguish that from the firmware's internal `Wake` step inside the sleep-state rendezvous cycle.
