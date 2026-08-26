# Spec-driven development workflow

This repo uses a milestone-oriented, spec-driven workflow. The goal is to make
architecture, constraints, one milestone, and implementation tasks explicit before
code changes begin.

## Planning flow

1. `/plan architecture`: inspect the repository, identify affected contracts,
   restate the goal, risks, non-goals, and validation strategy. Do not start
   implementation during architecture planning.
2. Refine the plan into a design document. Capture intended behavior, ownership
   boundaries, alternatives considered, operational impact, and rollout notes.
3. Create one GitHub Milestone for the approved plan. Its description holds the
   high-level plan overview: one outcome, scope boundaries, dependencies,
   validation strategy, risks, non-goals, and exit criteria. Do not set a due
   date.
4. Create or update a constraints/rules document. Keep durable constraints,
   terminology, safety rules, and cross-cutting decisions there instead of
   burying them in tasks.
5. End Plan Mode by materializing the plan into the undated GitHub Milestone
   and implementation-step GitHub Issues assigned to it. After the Issues
   exist, add their explicit dependency-ordered implementation sequence to the
   Milestone description, then stop.
6. `/goal <one milestone>`: execute exactly one milestone at a time. Stay within
   the selected milestone and do not continue into later milestones without the
   user's explicit instruction.
7. Review the completed milestone with the user. Summarize changes, risks,
   unresolved questions, validation, deployment implications, and manual rollout
   steps.
8. Continue only after the user selects or approves the next milestone.

## Planning artifacts

- Promote planning content into repository docs under `docs/` when it becomes a
  durable project contract, operational rule, or design reference.
- Keep architecture docs goal-oriented. Avoid turning them into implementation
  logs.
- Keep the high-level approved plan in the GitHub Milestone description; do not
  duplicate it in an active tracker document.

## End of Plan Mode

Plan Mode ends with durable planning output, not code.

When the user approves the architecture/design direction, presses Implement, or
otherwise approves a plan:

- Create or update the architecture/design doc.
- Create exactly one GitHub Milestone for the approved plan, leaving its due
  date unset. Its description must contain the high-level plan overview:
  outcome, scope, dependencies, validation strategy, risks, non-goals, and exit
  criteria.
- Create separate goal-oriented GitHub Issues assigned to that Milestone for the
  plan's implementation steps. If an implementation step is too large for one
  reviewable change, split it into smaller follow-up Issues under the same
  Milestone. Use native sub-issues where a parent/child relationship clarifies
  the work breakdown.
- After all Issues exist, update the Milestone description with an
  `Implementation order` section that lists every Issue by number in the order
  it should be executed. Derive the order from dependencies, put final
  integration or acceptance work after its prerequisites, and update the list
  whenever the Milestone's Issue set or dependencies change.
- Make each Issue atomic and verifiable.
- Use outcome-based acceptance criteria in each Issue description. Avoid criteria that merely name a
  function, file, class, or implementation technique.
- Link each Issue to relevant design and constraints docs in its description,
  with direct links to important source files or external references where
  useful.
- Do not add an implementation plan during Issue creation. Implementation plans
  are added only after an Issue is selected for execution.
- Do not use priority labels, priority fields, or priority metadata.
- If ambiguity remains, ask for clarification instead of creating speculative
  Issues.
- After creating the Milestone and Issues, report their numbers,
  then stop. Do not start code changes from the Plan Mode Implement action.

## Goal-to-implementation gate

Do not implement a planned feature directly from the chat plan or from the Plan
Mode Implement action. The chat plan is not a substitute for the GitHub
Milestone and Issues, and
Implement is treated as a planning closeout signal in this repository.

Before the first code, firmware, infrastructure, or configuration change for a
planned feature:

1. Confirm the user invoked `/goal <milestone>` or explicitly asked to implement
   a specific GitHub Issue.
2. If the user named a GitHub Issue number, run
   `gh issue view <number> --comments` before any repository-wide search. Treat
   the Issue description and comments as the starting context.
3. Check whether the selected GitHub Milestone already has Issue coverage for
   that work.
4. If suitable Issues do not exist, stop and create the missing Issues instead of
   implementing.
5. Report the selected Issue number.
6. Start exactly one Issue by assigning it to yourself and adding its
   implementation plan as a comment.
7. Implement only that Issue's acceptance criteria.

If `gh` is unavailable or unauthorized, or GitHub Issue or Milestone creation
fails, stop and report the blocker instead of continuing from the chat plan. The
only exception is an explicit user instruction to implement the change directly.

## GitHub Issue rules

- The GitHub CLI (`gh`) is installed, authenticated, and authorized to create
  and maintain Issues and Milestones for this repository. Use it for all tracker
  operations.
- Create and maintain Issues with `gh issue`. Read a named Issue directly with
  `gh issue view <number> --comments` rather than inferring it from repository
  search.
- Create and maintain Milestones with `gh api`; omit the `due_on` field when
  creating or updating a Milestone. Express the approved high-level plan in its
  description.
- Assign every implementation Issue to exactly one current Milestone. Express
  dependencies only on existing Issues; do not reference future Issue numbers.
- Do not use priority labels, priority fields, or priority metadata.

Typical Plan Mode closeout shape:

```sh
REPO="$(gh repo view --json nameWithOwner --jq .nameWithOwner)"

# Omit due_on: this Milestone intentionally has no finish date.
gh api --method POST "repos/$REPO/milestones" \
  -f title="Board video readiness" \
  -f description="High-level plan: outcome, scope, dependencies, validation, risks, non-goals, and exit criteria."

gh issue create --repo "$REPO" \
  --title "Publish board video readiness status" \
  --milestone "Board video readiness" \
  --body "## Outcome
...

## Acceptance criteria
- [ ] Status publication tolerates transient sender failures without resource churn.

## References
- docs/contracts/board-video-bridge.md"
```

## Implementing GitHub Issues

When implementing an existing Issue:

1. Read it with `gh issue view <number> --comments`.
2. Assign it to yourself: `gh issue edit <number> --add-assignee @me`.
3. Review its references, description, and comments.
4. Add the implementation plan with
   `gh issue comment <number> --body "Implementation plan: ..."`.
5. Share the plan with the user and wait for approval unless the user has
   explicitly asked to skip plan review.
6. Add progress comments as decisions, blockers, or
   meaningful implementation steps occur.
7. Update acceptance criteria in the Issue description as they are satisfied.
8. Add a PR-quality final summary as an Issue comment.
9. Close the Issue only after validation is complete.
