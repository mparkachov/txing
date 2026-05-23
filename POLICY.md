# Agent Execution Policy

## Primary Objective

Prioritize correctness of intent, operational safety, and architectural consistency over forward progress or task completion speed.

The agent must avoid silently making meaningful product, architecture, infrastructure, or operational decisions under ambiguity.

---

# Execution Model

The repository uses a milestone-oriented execution model.

The agent should:
1. understand the current milestone
2. constrain work to the active milestone only
3. avoid speculative future work
4. avoid unrelated refactors
5. stop after milestone completion and summarize results

The agent must not continue into future milestones automatically unless explicitly instructed.

---

# Plan Closeout Gate

When work starts from a completed Plan Mode discussion, an approved architecture
plan, or the user's Implement action, the agent must not begin code, firmware,
infrastructure, or configuration changes directly from the chat plan.

In this repository, the Plan Mode Implement action is a planning closeout
signal. It means:
1. create or update the architecture/design doc
2. create one Backlog.md milestone doc per planned milestone
3. create one separate goal-oriented Backlog.md task per milestone, plus smaller
   child or follow-up implementation tasks when a milestone is too large for one
   reviewable change
4. report the milestone docs and task IDs
5. stop without changing code

Implementation may begin only after the user invokes `/goal <milestone>` or
explicitly asks to implement a specific Backlog task. Before implementation,
the agent must set exactly one task to `In Progress`, assign it to itself, and
record an implementation plan in the task.

If Backlog.md is unavailable, task creation fails, or the selected milestone is
ambiguous, the agent must stop and ask for confirmation. The only exception is
an explicit user instruction to skip Backlog and implement immediately.

---

# Ambiguity Policy

Do not silently resolve meaningful ambiguity.

If multiple interpretations are plausible:
1. stop implementation
2. explain the ambiguity
3. provide at most 3 options
4. summarize tradeoffs briefly
5. recommend one option
6. wait for user confirmation

Do not optimize for forward progress over correctness of intent.

Lack of explicit rejection is not approval for architectural or behavioral changes.

---

# Escalation Requirements

The agent must ask for confirmation before:

- changing public APIs
- changing persistence or shadow schemas
- changing MQTT topic contracts
- changing BLE protocol behavior
- changing auth/security behavior
- introducing new dependencies
- changing operational semantics
- changing deployment topology
- changing rollout behavior
- changing failure semantics or retry behavior
- removing backward compatibility
- changing device wake/sleep behavior
- introducing background daemons or supervisors
- changing ownership boundaries between rig, board, daemon, MCU, or cloud

The agent must escalate whenever confidence in a decision is below approximately 80%.

---

# Allowed Autonomous Decisions

The agent may autonomously decide:

- local helper structure
- internal naming
- test organization
- non-behavioral refactors
- formatting
- lint cleanup
- localized implementation details
- bounded reliability improvements
- small internal abstractions

Autonomous decisions must remain consistent with existing repository architecture and contracts.

---

# Forbidden Autonomous Behavior

The agent must not:

- perform broad speculative refactors
- redesign systems without explicit approval
- silently change operational behavior
- optimize architecture beyond the active milestone
- introduce parallel systems without approval
- replace existing patterns solely for stylistic reasons
- widen scope during execution
- continue implementation after discovering architectural ambiguity

---

# Scope and Architectural Consistency

The agent should preserve architectural consistency, semantic consistency, and implementation coherence across subprojects.

The repository should evolve as a unified system rather than as isolated codebases with divergent terminology or patterns.

Cross-subproject changes are encouraged when they:
- improve architectural consistency
- reduce semantic drift
- align naming or operational concepts
- unify equivalent workflows
- eliminate duplicated concepts
- reinforce shared contracts or patterns
- improve long-term maintainability

The agent should proactively avoid introducing:
- inconsistent terminology for equivalent concepts
- divergent abstractions solving the same problem
- incompatible operational semantics
- duplicated infrastructure patterns
- inconsistent deployment or rollout terminology
- local optimizations that conflict with repository-wide conventions

Example:
If equivalent workflows exist across subprojects, they should generally use aligned terminology and behavior unless there is a clear architectural reason not to.

However, the agent must avoid:
- speculative large-scale rewrites
- unrelated cleanup work
- broad refactors without architectural justification
- introducing abstractions before they are needed
- changing established patterns without clear repository-wide benefit

When making cross-subproject consistency changes, the agent should:
1. explain the architectural reasoning
2. keep changes incremental
3. preserve operational stability
4. avoid unnecessary churnx

---

# Reliability Requirements

Rig, MCU, board, and cloud-facing systems are correctness-critical.

The agent must prioritize:
- deterministic behavior
- bounded retries
- graceful degradation
- operational observability
- rollback safety
- protocol consistency
- state consistency

The agent must avoid:
- hidden retry storms
- unbounded loops
- silent state divergence
- unnecessary concurrency
- resource churn
- fragile timing assumptions

---

# Planning Expectations

Before major implementation work, the agent should:
1. restate the active milestone
2. identify affected components
3. identify risks
4. identify non-goals
5. identify validation strategy

For risky changes, the agent should propose phased implementation.

---

# Implementation Discipline

Implementation should proceed incrementally.

Preferred order:
1. interfaces/contracts
2. state model
3. core logic
4. integration
5. observability
6. tests
7. rollout notes

The agent should favor simple explicit implementations over abstraction-heavy designs unless abstraction is clearly justified.

---

# Validation Requirements

Before considering a milestone complete, the agent should:

- run relevant tests where possible
- verify contract consistency
- verify shadow/schema consistency
- verify protocol assumptions
- check for operational regressions
- summarize deployment implications
- summarize manual rollout steps

---

# Completion Behavior

At milestone completion, the agent should stop and provide:
- summary of changes
- risks
- unresolved concerns
- deployment implications
- manual rollout steps
- recommended next milestone

The agent should not automatically continue into subsequent milestones.

# Evolution and Compatibility Policy

The repository is currently in a rapid iteration and architectural convergence phase.

At this stage, prioritize:
- architectural clarity
- conceptual consistency
- implementation simplicity
- removal of obsolete patterns
- fast iteration velocity

over:
- backward compatibility
- migration layers
- compatibility adapters
- transitional abstractions
- automated cleanup tooling

The agent should prefer direct replacement over compatibility preservation unless the user explicitly requests backward compatibility.

When replacing an existing pattern or contract:
- update the repository to the new model directly
- remove obsolete paths instead of preserving them
- avoid introducing temporary compatibility shims
- avoid maintaining parallel implementations
- avoid deprecation scaffolding unless explicitly requested

Do not generate:
- migration frameworks
- rollback frameworks
- compatibility wrappers
- cleanup scripts
- transitional feature flags
- temporary dual-write logic
- legacy compatibility abstractions

unless explicitly requested by the user.

Prefer:
- straightforward repository-wide updates
- explicit manual rollout notes
- concise manual cleanup instructions for the user

When cleanup of old resources, infrastructure, configuration, or generated artifacts is required:
- explain the required manual cleanup steps clearly
- do not generate automated cleanup systems unless explicitly requested

Compatibility preservation is required only for:
- explicitly versioned protocols
- externally deployed device contracts
- protocol compatibility explicitly identified by the repository documentation
