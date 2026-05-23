# Spec-driven development workflow

This repo uses a milestone-oriented, spec-driven workflow. The goal is to make
architecture, constraints, milestones, and implementation tasks explicit before
code changes begin.

## Planning flow

1. `/plan architecture`: inspect the repository, identify affected contracts,
   restate the goal, risks, non-goals, and validation strategy. Do not start
   implementation during architecture planning.
2. Refine the plan into a design document. Capture intended behavior, ownership
   boundaries, alternatives considered, operational impact, and rollout notes.
3. Create milestone documents. Each milestone should describe one outcome, scope
   boundaries, dependencies, validation, and exit criteria.
4. Create or update a constraints/rules document. Keep durable constraints,
   terminology, safety rules, and cross-cutting decisions there instead of
   burying them in tasks.
5. `/goal <one milestone>`: execute exactly one milestone at a time. Stay within
   the selected milestone and do not continue into later milestones without the
   user's explicit instruction.
6. Review the completed milestone with the user. Summarize changes, risks,
   unresolved questions, validation, deployment implications, and manual rollout
   steps.
7. Continue only after the user selects or approves the next milestone.

## Planning artifacts

- Use Backlog.md docs for active planning artifacts created during Plan Mode.
  Useful paths are `architecture/<topic>`, `milestones/<milestone>`, and
  `constraints/<topic>`.
- Promote planning content into repository docs under `docs/` when it becomes a
  durable project contract, operational rule, or design reference.
- Keep architecture docs goal-oriented. Avoid turning them into implementation
  logs.

## End of Plan Mode

Plan Mode ends with durable planning output, not code.

When the user approves the architecture/design direction, presses Implement, or
otherwise asks to implement an approved plan:

- Create Backlog.md tasks for the selected milestone or milestone set.
- Make each task goal-oriented, atomic, and verifiable.
- Use outcome-based acceptance criteria. Avoid criteria that merely name a
  function, file, class, or implementation technique.
- Link each task to relevant design, milestone, and constraints docs with
  `--doc`; link important source files or external references with `--ref`.
- Do not add an implementation plan during task creation. Implementation plans
  are added only after a task is selected for execution.
- If ambiguity remains, ask for clarification instead of creating speculative
  tasks.

## Plan-to-implementation gate

Do not implement a planned feature directly from the chat plan. The chat plan is
not a substitute for Backlog.md.

Before the first code, firmware, infrastructure, or configuration change for a
planned feature:

1. Check whether Backlog.md already has task coverage for the approved plan or
   selected milestone.
2. If suitable tasks do not exist, create them with the `backlog` CLI.
3. Report the created or selected task IDs.
4. Start exactly one task by moving it to `In Progress`, assigning it to
   yourself, and adding its implementation plan.
5. Implement only that task's acceptance criteria.

If the Backlog.md CLI is unavailable or task creation fails, stop and report the
blocker instead of continuing from the chat plan. The only exception is an
explicit user instruction such as "skip Backlog for this change".

## Backlog.md rules

- Use the `backlog` CLI for all Backlog.md task, draft, document, decision, and
  milestone operations. Do not manually edit files under `backlog/tasks/`,
  `backlog/drafts/`, `backlog/docs/`, or `backlog/decisions/`.
- Use `--plain` when reading tasks or search output for agent consumption:
  `backlog task <id> --plain`, `backlog task list --plain`, and
  `backlog search "topic" --plain`.
- Express dependencies only on existing tasks. Do not reference future task IDs.

Typical Plan Mode closeout shape:

```sh
backlog doc create "Unit video architecture" -p architecture/unit-video -t specification
backlog doc update doc-1 --content "..."
backlog doc create "Milestone: board video readiness" -p milestones/board-video-readiness -t guide
backlog doc create "Constraints: board video" -p constraints/board-video -t guide
backlog task create "Publish board video readiness status" \
  -m "board video readiness" \
  --doc backlog/docs/milestones/board-video-readiness.md \
  --doc backlog/docs/constraints/board-video.md \
  --ac "Rig can derive REDCON state from retained video readiness topics" \
  --ac "Status publication tolerates transient sender failures without resource churn"
```

## Implementing Backlog tasks

When implementing an existing task:

1. Read it with `backlog task <id> --plain`.
2. Move it to `In Progress` and assign it to yourself:
   `backlog task edit <id> -s "In Progress" -a @<agent>`.
3. Review its references and documentation.
4. Add the implementation plan with `backlog task edit <id> --plan "..."`.
5. Share the plan with the user and wait for approval unless the user has
   explicitly asked to skip plan review.
6. Append progress notes with `--append-notes` as decisions, blockers, or
   meaningful implementation steps occur.
7. Mark acceptance criteria and Definition of Done items complete via the CLI.
8. Add a PR-quality final summary with `--final-summary`.
9. Set the task to `Done` only after validation is complete.
