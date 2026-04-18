# txing

> Sleep cold. Wake on call. Action.

`txing` is a design concept for field devices that must stay available for long periods on limited power, but still be able to wake into a far more capable operating mode when needed.

A `txing` system connects a physical device to stronger local or remote processing without assuming the link is always fast, cheap, or continuously available. Most of the time, the device should be able to stay in a very low-power watch posture. When the situation justifies it, the device should be able to wake, bring up more capable processing, and use a stronger connection for live work.

If the short question is "what is txing?", the short answer is this: `txing` is a pattern for physical systems that sleep hard, wake on demand, and scale from minimal signaling to full operation only when the extra energy, bandwidth, and compute are worth spending.

## Core idea

At the conceptual level, `txing` has two layers:

- A watch layer that stays alive on a very tight power budget, remains reachable, and handles minimal sensing or signaling.
- An action layer that wakes only when bandwidth, latency, compute, or interaction are actually needed.

In many implementations, the watch layer is a small always-on controller and the action layer is a more capable processor, radio stack, or sensor stack. But `txing` is not defined by BLE, Wi-Fi, AWS IoT, a gateway, or any specific cloud-control model. Those are implementation choices. The stable part of the idea is the posture change:

- stay cold for long periods
- receive a wake request or emit a tiny report
- enter the wakeup state when something meaningful is needed
- connect the device to stronger processing and richer services

From the concept's point of view, a human is only one example of an operator. A `txing` can be called, steered, or supervised by a person, a cloud workflow, an automated service, or another supervisory node. What matters is not who gives intent, but that the device can stay cheap while idle and become capable when intent arrives.

## The two links

Every `txing` design assumes two classes of connection.

| Link | Role | Characteristics | Examples |
| --- | --- | --- | --- |
| Watch link | Reach the device in the sleep state and move tiny amounts of data | Ultra-low power, sparse payloads, tolerant of delay, built for wake-on-demand and small telemetry | LoRa, narrowband radio, satellite burst links, low-duty-cycle cellular, BLE as a proof of concept |
| Action link | Carry live work once the device is in the wakeup state | Higher bandwidth, lower latency, supports streaming, operator interaction, and heavier processing close to the edge or in the cloud | Wi-Fi, LTE/5G, Ethernet, Starlink |

The watch link is for messages like "wake up", "still alive", or a tiny report such as temperature and humidity every ten minutes. A weather station sending periodic LoRa updates is a clean example of this side of the pattern. In this repository, BLE is only the simplest proof-of-concept implementation of that class of link.

The action link is for live work: richer telemetry, video, operator control, and near-real-time processing on stronger local hardware or in the cloud. In this repository it is Wi-Fi. In a different `txing` device, it could just as naturally be Starlink.

## Operating posture

This README uses military readiness shorthand for the technical posture and plain-language names with a little wasteland flavor for the public voice. `REDCON 4` is the only essential posture in the concept. Higher levels are optional. A simple weather station may live entirely at `REDCON 4`, surfacing only to emit tiny reports over the watch link. Systems with richer local and remote behavior can extend upward through the rest of the ladder.

| Device state | Technical call | UI color | Public name | Meaning |
| --- | --- | --- | --- | --- |
| Sleep state | `REDCON 4` | Green | `Cold Camp` | The device is conserving power. Only the watch layer is truly on watch, and the device can still be reached through the watch link. |
| Booting | `REDCON 3` | Yellow | `Torch-Up` | The action layer has been called up. Power is flowing and services are starting, but the device is still climbing out of its cold posture. |
| On watch | `REDCON 2` | Orange / Amber | `Ember Watch` | Local power and local processing are available. The device can observe, decide, buffer, and operate locally, but the high-bandwidth remote link is not necessarily up. |
| Ready | `REDCON 1` | Red | `Hot Rig` | The device is fully up, the action link is up, and the rig is ready for live interaction, streaming, or cloud-assisted work. |

In this repository's current Thing Shadow contract, the rig runtime derives a single top-level readiness field at `state.reported.redcon` from the reported MCU and board state:

| `state.reported.redcon` | UI color | Meaning | Current derivation |
| --- | --- | --- | --- |
| `4` | Green | Sleep state / `Cold Camp` | `reported.mcu.power=false` |
| `3` | Yellow | Booting / `Torch-Up` | `reported.mcu.power=true`, while the operator video path is not ready yet |
| `2` | Orange / Amber | On watch / `Ember Watch` | `reported.mcu.power=true`, `reported.board.power=true`, `reported.board.wifi.online=true`, `reported.board.video.ready=true`, and `reported.board.video.viewerConnected=false` |
| `1` | Red | Ready / `Hot Rig` | same as `2`, plus `reported.board.video.viewerConnected=true` |

This mapping is intentionally derived from reported state, not desired state. It answers "how far up is the rig right now?" rather than "what was requested?".

## Why this shape exists

The military analogy here is about posture, not purpose. A `txing` device is not necessarily a military device. The useful idea is readiness discipline: conserve, observe, stay reachable, and escalate only when needed.

The point is to let a physical device live cheaply in the world most of the time, while still being able to pull stronger capability close when needed. That stronger capability might be local processing on the device, operator tooling, cloud orchestration, or other remote services. The device does not need to pay for all of that all of the time.

## Hierarchy

`txing` also leaves room for hierarchy. A field device does not have to answer directly to a single person or a single cloud service. Over time, a `txing` network can grow into layers such as field devices, regional coordinators, and higher-level orchestration.

In that kind of system, a human operator is just one sample caller among many. Cloud services, automation, and supervisory nodes can all occupy the same conceptual role: they issue intent, consume reports, and decide when a device should stay cold, stay local, or go fully hot.

Current functional decision:

- `town` is the top-level management namespace and the Sparkplug group id.
- `rig` is the always-on regional coordinator and the Sparkplug edge node.
- `txing` is the field device and the Sparkplug device.
- One physical `txing` includes both the MCU watch layer and the board action layer.
- One `rig` is expected to manage multiple `txing` devices over time.
- In the current implementation, lifecycle intent moves toward Sparkplug `redcon`, while AWS shadow remains a reflected operational store and restart cache.

That means the regional coordinator is not itself a `txing` in the current implementation. It is a separate layer in the hierarchy: the `rig`.

## Sample implementation in this repo

This repository contains one sample implementation of the `txing` concept:

- `mcu/`: the current watch layer
- `board/`: the current action layer
- `rig/`: the current Raspberry Pi support component that acts as the `rig` lifecycle runtime and bridges cloud intent to the watch link
- `web/`: one operator/admin surface
- `docs/`: shared contracts, schema, and Sparkplug lifecycle notes for this implementation

In this implementation, the watch link is BLE and the action link is Wi-Fi. Those are examples, not the definition of `txing`.

For the current Sparkplug lifecycle design around `town`, `rig`, and `txing`, see [docs/sparkplug-lifecycle.md](./docs/sparkplug-lifecycle.md).

For build, deploy, and local development workflows, see [development.md](./development.md).
