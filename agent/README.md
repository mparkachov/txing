# Agent

The shared C++ AI operator is planned and in progress under
[milestone 10](https://github.com/mparkachov/txing/milestone/10).
The superseded TBot Go controller/runtime, separate native viewer and worker
IPC, Fargate stack, and container build have been removed. No replacement
runtime or cloud deployment is available yet.

The authoritative [agent design](../docs/components/agent.md) separates device
sessions, operator behavior, and hosting. It specifies timestamped encoded video
delivery to the operator, observation by default, and explicit session-owned
control across arm/disarm cycles. Follow the
[agent constraints](../docs/constraints/agent.md) and
[cloud shadow contract](../docs/contracts/agent-shadow.md).

`just agent::test` currently checks the replacement shadow schema, defaults, and
fixtures. The other public commands in the design are target interfaces for
later issues, not available commands. Shared SDK pin/build resources remain in
`devices/common/kvs/`; deployed board protocols and board/rig/Office connection
fixes remain in their owning components.

Before initial replacement, follow the
[manual retirement and rollout instructions](../docs/constraints/agent-rollout.md).
Removing repository source does not disable deployed triggers or stop tasks.
