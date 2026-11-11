# txing agent guide

This is the root routing guide for agents working in the `txing` monorepo.
Keep it short: durable technical details live in focused docs and subproject
`AGENTS.md` files. User instructions override this file.

## Start here

- Follow `POLICY.md` for execution policy, ambiguity handling, escalation,
  approval gates, milestone discipline, and completion behavior.
- For live troubleshooting and manual operator work, follow [Interactive work
  in chat](POLICY.md#interactive-work-in-chat). Give the next action directly in
  chat and use the user's result to choose the next step.
- Read the nearest subproject `AGENTS.md` before editing under a subdirectory.
  The closer file carries the local build, test, and contract guidance for that
  area.
- Read referenced docs before changing the related behavior. Do not rely on this
  root file as the full project specification.
- Use `nerdctl.lima` with the existing Lima engine for local container builds;
  see `docs/agent-guidance/editing-boundaries.md` for tooling guidance.

## Repository map

- `devices/unit/mcu/`: stock Zephyr C firmware for the current `unit` device type
  MCU.
- `rig/`: Raspberry Pi 5 rig runtime for AWS IoT MQTT and BLE communication.
- `agent/`: shared C++ AI operator runtime for macOS and AWS MicroVMs. See
  `docs/components/agent.md` for operation, deployment, and publication.
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

- Spec-driven planning and GitHub Issues workflow:
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
- Agent architecture and operational constraints: `docs/components/agent.md`
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
  exactly one GitHub Milestone with no due date. Put the high-level plan overview
  in that milestone's description, then create separate goal-oriented GitHub
  Issues for the implementation steps and assign them to that milestone. Stop
  after creating the tracking items.
- Issues must describe outcomes and acceptance criteria, not implementation
  steps. Do not set priority fields or add priority labels. If meaningful
  ambiguity remains, ask for clarification instead of creating speculative
  issues.
- Implementation starts only when the user invokes `/goal <milestone>` or
  explicitly asks to implement a specific GitHub Issue. During `/goal`, execute
  exactly one milestone at a time. Stop after milestone completion and wait for
  the user to choose or approve the next milestone.
- Selecting a goal authorizes unattended implementation within its scope.
  Record Issue implementation plans as comments and continue without asking for
  plan approval again. For a milestone goal, complete its Issues in dependency
  order, with one active Issue at a time, without approval at Issue boundaries.
  Ask only for missing information or a material departure from the approved
  scope; preserve the explicit operational gates below.
- If a goal or prompt names a GitHub Issue number, load it first with
  `gh issue view <number> --comments`. Do not search the repository to discover
  what the Issue means.

## GitHub Issue workflow

- The GitHub CLI (`gh`) is installed, authenticated, and authorized to create
  and maintain Issues and Milestones for this repository. Use it for all tracker
  operations.
- Create Milestones without a due date. Their descriptions hold the approved
  plan's outcome, scope, dependencies, validation strategy, risks, non-goals,
  and exit criteria.
- After creating the Milestone's Issues, update its description with an
  explicit implementation order that lists every Issue by number. Order the
  Issues by dependency and keep the list current if the Issue set changes.
- Assign every implementation Issue to its Milestone. Use native sub-issues when
  a parent/child relationship improves the work breakdown; keep both Issues in
  the same Milestone.
- Do not create priority labels, priority fields, or other priority metadata.

## Non-negotiable gates

- Do not perform `git commit` automatically. Create commits only when explicitly
  requested by the user.
- Do not run AWS commands that create, update, or delete cloud resources.
  Read-only AWS inspection commands are allowed only when needed.
- Do not implement a planned feature directly from the chat plan or the Plan
  Mode Implement action. That action closes planning by creating the GitHub
  Milestone and Issues; it does not authorize code changes unless the user
  explicitly says to implement immediately.
- Do not run firmware flashing/programming steps. Prepare artifacts and commands
  for the user to run manually.
- Do not read from, copy from, execute from, or depend on files outside this
  repository unless the user explicitly provides the content or asks to vendor it
  into the repository.
- After a code, firmware, infrastructure, or configuration change, include
  applicable deployment or rollout guidance in chat. During a live session,
  give manual steps one at a time.

## Documentation placement

- Keep root `AGENTS.md` limited to routing, workflow, and critical gates.
- Keep documentation aligned with the current implementation. Update the
  owning guide and links when the change affects a durable contract or a
  repeatable procedure. Keep session-specific troubleshooting in chat.
- Keep one canonical guide per functionality. Extend the owning guide and
  link to it from related docs. Record test results and intermediate steps in
  GitHub Issues, CI, or clearly marked history when retention is needed.
- Treat `tmp/` as disposable. A fresh clone with an empty `tmp/` must be
  enough to resume an open Issue using tracked files and its Issue record.
  Before closing, preserve findings, required evidence, and reusable
  procedures in durable locations.
- Put durable technical contracts in `docs/contracts/`.
- Put operational constraints in the guide that owns the functionality. Use
  `docs/agent-guidance/` for cross-repository tooling and editing rules.
- Treat historical constraints as context. Verify them against current code,
  configuration, and contracts before carrying them into an active guide.
- Put durable planning artifacts in `docs/`; keep the approved plan overview in
  the GitHub Milestone description rather than duplicating it in a tracker doc.
- Use nested `AGENTS.md` files only for local instructions an agent must know
  before editing that subtree.
