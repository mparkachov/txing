---
id: doc-47
title: TBot cloud companion for QGroundControl architecture
type: specification
created_date: '2026-09-26 00:00'
updated_date: '2026-09-26 00:00'
tags:
  - tbot
  - cloud
  - mavlink
  - webrtc
  - qgroundcontrol
---

# TBot cloud companion for QGroundControl

## Outcome

Run one cloud companion task for each TBot whose projected Sparkplug state is
born at REDCON 2 or 1. The task joins the existing `<thing>-mavlink` KVS
signaling channel as a viewer and exposes its MAVLink 2 stream on public UDP
port 14550. At REDCON 1 it also joins `<thing>-board-video` as a receive-only
viewer; received media is discarded. No task runs at REDCON 3, REDCON 4, or
device death. This design applies only to TBot.

## Ownership and data flow

- The raspi rig and witness retain ownership of Sparkplug state and its named
  shadow projection. The board daemon retains peer identity and the five-second
  MAVLink active-control lease. The companion is a viewer peer; it does not
  change board, rig, or WebRTC wire contracts.
- A dedicated Go controller Lambda receives completed `sparkplug` named-shadow
  updates and reconciles the TBot's reported message type and REDCON with ECS.
  A one-minute EventBridge reconciliation scans TBot things and active tasks to
  recover missed events, failed starts, and duplicate tasks. Processing is
  idempotent: select one task per thing, stop duplicates, and reject stale
  updates from a superseded task. The Lambda verifies the thing type before any
  task action.
- The companion runs as a separately versioned `linux/arm64` container on
  Fargate. It uses the repository-pinned AWS KVS WebRTC C SDK in viewer mode for
  two independent peer connections. MAVLink starts at REDCON 2 and stays up at
  REDCON 1. Video is attempted only while the projected state is REDCON 1;
  video loss never closes MAVLink. The task reads its own projected state to
  close video at REDCON 2 and exit when REDCON falls below 2 or becomes dead,
  while the controller independently stops the ECS task.
- Provision a dedicated ECS cluster and public dual-stack VPC/subnets with an
  internet gateway. A task receives dynamic public IPv4 and IPv6 addresses;
  there is no load balancer, static address, or idle compute task. Inbound UDP
  14550 is open to all sources on both families. QGroundControl uses IPv4
  because its current UDP link binds an IPv4 socket. The container image is
  published to ECR under a versioned release and the task definition references
  an immutable digest.

## UDP and control behavior

Each WebRTC binary data-channel message is one complete MAVLink 2 frame.
Downlink sends one frame per UDP datagram to the selected QGroundControl source;
uplink splits datagrams into complete frames and sends each frame unchanged.
Reject incomplete or malformed framing; preserve valid signed and unfamiliar
frames byte-for-byte. Only one UDP source address and port is selected at a
time, by its first valid MAVLink datagram. Five seconds of inactivity frees that
source. Telemetry flows to the selected source before it owns control.

Before activation, the companion does not forward QGroundControl uplink,
including parameter requests. It recognizes an arm request from a complete,
CRC-valid MAVLink 2 `COMMAND_LONG` or `COMMAND_INT` carrying
`MAV_CMD_COMPONENT_ARM_DISARM` with arm parameter 1. It asks the board for
`control.activate` with `takeover=false` and forwards the original arm frame
only after success. A busy board leaves the client observing telemetry; it
never triggers takeover. While active, the companion renews the five-second
lease and forwards all complete frames from that same UDP source without
rewriting IDs, command fields, signatures, or payloads.

On a disarm request, the companion forwards the disarm frame and releases the
lease after its acknowledgment or a bounded one-second wait. It also releases
on five seconds of UDP inactivity, WebRTC loss, or task shutdown. Board-side
lease expiry and safe-state behavior remain the final control boundary. A
new arm request is required to regain control after release.

## Shadow and Office contract

The controller and companion own a separate TBot `agent` named shadow. Its
reported state distinguishes `stopped`, `starting`, `ready`, and `error` task
states; has nullable IPv4 and IPv6 addresses plus UDP port 14550; carries
MAVLink and video connection states and a nullable last error. The controller
owns lifecycle and endpoint fields; the task owns connection fields. Updates
are fenced by task identity and version-conditional shadow writes, with a fresh
identity check after a version conflict, so an old task cannot restore an endpoint after
replacement. `ready` requires a running task, bound UDP listener, and open
MAVLink data channel. Stopping, task failure, or lost readiness clears the
published endpoint. The controller reconciles stale shadow state on every
event and minute tick.

Office loads this named shadow only for TBot's Debug panel and displays the
document as diagnostic JSON. It does not expose the endpoint in normal device
controls, add `agent` to REDCON capability rules, or infer device readiness
from companion state. Absence of the optional shadow before first deployment
must not block the normal Office shadow session.

## Rollout and validation

Create the ECR repository and companion infrastructure through forward-only
CloudFormation. Publish a versioned image, set the task definition to its
digest, provision the optional `agent` shadow, and only then enable the
shadow-update trigger. Deploy the Go controller as a release-built runtime
Lambda. Do not issue AWS mutation commands as part of agent validation; the
operator performs the documented deployment. No board or firmware flash is
required by this design.

Automated acceptance covers lifecycle transitions, event replay, duplicate and
failed tasks, endpoint cleanup, frame boundaries, signed frame preservation,
arm detection, no-takeover lease behavior, disarm/idle release, and independent
video reconnection. Operator acceptance on a secured lifted TBot verifies
QGroundControl telemetry, arm, motion, disarm, link loss, and Office lease
contention through the live public IPv4 endpoint. If QGroundControl cannot
emit an arm command under the strict pre-arm rule, stop and revisit that
approved rule rather than silently acquiring control earlier.

The public UDP endpoint has no authentication. Anyone who reaches it can
observe telemetry and, if the board lease is free, request arm and gain
control. Dynamic addresses reduce idle infrastructure but are not an access
control. Cyberbrick, Unit, video forwarding or storage, stable DNS, and a
local QGroundControl bridge are outside this milestone.

## References

- [Board MAVLink capability contract](../../contracts/board-mavlink.md)
- [Sparkplug lifecycle](../../sparkplug-lifecycle.md)
- [AWS Fargate task networking](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/fargate-task-networking.html)
- [QGroundControl UDP implementation](https://raw.githubusercontent.com/mavlink/qgroundcontrol/master/src/Comms/UDPLink.cc)
