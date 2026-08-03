# txing agent guide

This is the root routing guide for agents working in the `txing` monorepo.
Keep it short: durable technical details live in focused docs and subproject
`AGENTS.md` files. User instructions override this file.

## Start here

- Follow `POLICY.md` for execution policy, ambiguity handling, escalation,
  approval gates, milestone discipline, and completion behavior.
- Read the nearest subproject `AGENTS.md` before editing under a subdirectory.
  The closer file carries the local build, test, and contract guidance for that
  area.
- Read referenced docs before changing the related behavior. Do not rely on this
  root file as the full project specification.

## Repository map

- `devices/unit/mcu/`: stock Zephyr C firmware for the current `unit` device type
  MCU.
- `rig/`: Raspberry Pi 5 rig runtime for AWS IoT MQTT and BLE communication.
- `devices/common/board/`: the single board-side implementation (Go daemon, KVS
  worker, hardware worker) shared by every board device type; the device type is
  a build input.
- `devices/cloud-mcu/`: AWS-hosted cloud rig and cloud MCU runtime support.
- `shared/aws/`: shared AWS CLI helpers, CloudFormation, registry utilities,
  and admin Lambda packaging.
- `witness/`: Sparkplug-to-shadow projection Lambda source and tests.
- `office/`: React/Vite admin SPA for Thing Shadow management.
- `www/`: static public web site for `txing.dev`.

Treat the repo as a monorepo. Keep changes scoped to the relevant subproject
unless a shared contract or consistency issue requires coordinated updates.

## Required references

- Spec-driven planning and Backlog.md workflow:
  `docs/agent-guidance/spec-driven-development.md`
- Extracted component editing boundaries from project docs:
  `docs/agent-guidance/editing-boundaries.md`
- Repository-wide development, safety, deployment, tooling, and release
  constraints: `docs/agent-guidance/editing-boundaries.md`
- Board OS baseline (Alpine only, Debian frozen, no Debian build paths):
  `docs/components/board.md#operating-system-baseline`
- Unit device contracts, ownership, board video, power terminology, and runtime
  reliability: `docs/contracts/unit-device-contracts.md`
- MCU shared stack invariant and firmware reference: `docs/components/mcu.md`
- AWS Lambda language boundary: `docs/aws-lambda-boundary.md`
- Sparkplug lifecycle design: `docs/sparkplug-lifecycle.md`
- Current rig-era shadow plus BLE compatibility contract:
  `devices/unit/docs/device-rig-shadow-spec.md`
- Current unit Thing Shadow schemas: `devices/unit/aws/*-shadow.schema.json`

## Planning and goals

- During `/plan architecture`, inspect the repo, identify affected contracts,
  capture risks and non-goals, and produce planning artifacts. Do not implement
  code during architecture planning.
- Plan Mode must end with durable planning output, not implementation. When the
  user leaves Plan Mode, presses Implement, or otherwise approves a plan, create
  or update one Backlog.md milestone doc for the approved plan and create
  separate goal-oriented Backlog.md tasks for the plan's implementation steps
  under that single milestone, then stop.
- Tasks must describe outcomes and acceptance criteria, not implementation
  steps. If meaningful ambiguity remains, ask for clarification instead of
  creating speculative tasks.
- Implementation starts only when the user invokes `/goal <milestone>` or
  explicitly asks to implement a specific Backlog task. During `/goal`, execute
  exactly one milestone at a time. Stop after milestone completion and wait for
  the user to choose or approve the next milestone.
- If a goal or prompt names a Backlog task ID, load that task first with
  `backlog task <id> --plain`. Do not search the repository to discover what
  the Backlog task means.

## Backlog CLI in sandboxed environments

- Create and update milestones, tasks, and acceptance criteria only through the
  `backlog` CLI. Never create, edit, or delete Backlog lock or mirror files
  directly, including anything under `.git`.
- If a Backlog operation fails because its Git-backed lock cannot be created,
  temporarily run `backlog config set filesystemOnly true`, perform the single
  required Backlog CLI operation, then restore `backlog config set filesystemOnly false`
  and `backlog config set checkActiveBranches true`.
- Treat restoration of those settings as mandatory before completing the task.

## Non-negotiable gates

- Do not perform `git commit` automatically. Create commits only when explicitly
  requested by the user.
- Do not run AWS commands that create, update, or delete cloud resources.
  Read-only AWS inspection commands are allowed only when needed.
- Do not implement a planned feature directly from the chat plan or the Plan
  Mode Implement action. That action closes planning by creating Backlog.md
  milestone/task records; it does not authorize code changes unless the user
  explicitly says to skip Backlog and implement immediately.
- Do not run firmware flashing/programming steps. Prepare artifacts and commands
  for the user to run manually.
- Do not read from, copy from, execute from, or depend on files outside this
  repository unless the user explicitly provides the content or asks to vendor it
  into the repository.
- After any code, firmware, infrastructure, or configuration change, include
  deployment or rollout steps in the final response, including manual steps.

## Documentation placement

- Keep root `AGENTS.md` limited to routing, workflow, and critical gates.
- Put durable technical contracts in `docs/contracts/`.
- Put operational and tooling constraints in `docs/constraints/`.
- Put active planning artifacts created during Plan Mode in Backlog.md docs
  unless they should become permanent repository documentation.
- Use nested `AGENTS.md` files only for local instructions an agent must know
  before editing that subtree.
