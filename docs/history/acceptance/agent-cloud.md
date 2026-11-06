# Released Agent acceptance record

These are dated observations. Use the [Agent guide](../../components/agent.md)
for current operation, deployment, and validation.

## Released cloud operation, November 2026

The physical and fault cases exercised agent 0.1.1, image 4.0 in the original
image inventory, on TBot with QGroundControl 5.1.5. The operator secured and
lifted the device. Both launch gates were disabled after the tests.
[Cloud acceptance tracking](https://github.com/mparkachov/txing/issues/170)

| Case | Observed result |
| --- | --- |
| Observation and control | Telemetry and encoded video arrived before attachment. Explicit attachment control supported parameter retrieval and arm, drive, stop, disarm, re-arm and final disarm. Client inactivity, attachment exit, Office takeover and a bounded UDP fault released control. Recovery required a new explicit acquisition. |
| Activation budget | A 600-second test preserved the original deadline across VM replacement. Replayed lifecycle hints did not change the run or extend the activation. At expiry, with actual REDCON 1 unchanged, no run or endpoint remained and attachment refused. A later observed inactive-to-active transition started a fresh activation using the restored 3000-second setting. |
| Verification loss | Actual REDCON stayed at 1 during a timed registry denial. Runtime samples bracketed fencing 14.961–15.285 seconds after the last successful verification. The board was sampled disarmed and unowned after release. The stale WebSocket upgraded, then closed before any command was sent. The replacement observed both streams under the original activation and deadline. The Scheduler migration occurred after fencing and before replacement. |
| Independent video | Camera loss produced actual REDCON 2 and stopped video while telemetry kept its peer and VM. With the camera unavailable, restoring MAVLink after an inactive interval started a fresh data-only run at actual 2. A separate test restored the video configuration socket. Encoded frames resumed at actual 1 with the same KVS process, MAVLink peer, cloud run and deadline. |
| Independent witness | With the controller isolated, the orphan reached terminal state at 124.245 seconds of age. Separate assigned fixtures reached terminal state 136.976 seconds after the first off timestamp and 160.919 seconds after activation expiry. Each beat its independent 600-second hosting cap. Witness preserved the assigned VMs during grace and the test left real device history intact. |
| Whole-device death | On November 5 the operator switched off both TBot processors and left the rig powered. Actual DDEATH was observed about 33 seconds later. The VM was terminal about 34 seconds after power-off and 2719 seconds before its deadline. A check about 148 seconds later still showed zero nonterminal VMs, no assignment/endpoint and no replacement. |

The cutoff bracket measures sampled runtime state. Board release was sampled
every five seconds, and the physical off time had second resolution.

## Findings tracked separately

- **MAVLink/control stall.** On November 3 control timed out before any registry
  fault was applied. Actual REDCON stayed 1 and the board stayed disarmed. For a
  roughly ten-second window the board completed 632 SDK telemetry sends while
  the cloud peer stopped receiving. The old peer's ICE/data counters froze, and
  a fresh peer restored telemetry without an automatic control grant. The SDK
  counters establish call completion. Packet delivery and the cause remain
  unresolved. [Transport follow-up](https://github.com/mparkachov/txing/issues/172)
- **Camera cleanup.** The camera fault logged `closing_video` and
  `releasing_camera` without a `camera_released` marker. A read-only snapshot
  showed the worker waiting in a futex. The later configuration-socket test
  exercised independent video recovery through a different path. The exact
  camera cleanup wait remains unresolved. [Camera follow-up](https://github.com/mparkachov/txing/issues/173)
- **Board credential renewal.** In the October 22 MicroVM probe, board role
  assumptions were 3300 seconds apart on 3600-second credentials. Renewal
  coincided with KVS session recreation and a peer disconnect on the same
  board boot. The agent subsequently reported an inactive/dead stop. The
  intermediate capability/REDCON states are inferred from source. This finding
  informs the 3000-second operating ceiling. [Renewal follow-up](https://github.com/mparkachov/txing/issues/174)

## Release retention, November 2026

Three fresh publications after the storage reset retained one, then two, then
two versions. The third removed image 1.0 before deleting its 0.1.0 bundle.
The audit confirmed that the new bucket had no versioning status and the
retired versioned bucket was gone. All 18 retained object checksums matched.
Release 0.1.2/image 3.0 was selected and 0.1.1/image 2.0 remained available.
Both launch gates were disabled, both repair schedules enabled, and zero VMs
were nonterminal. [Retention audit](https://github.com/mparkachov/txing/issues/175#issuecomment-6679113411)
