# Unit Hardware Worker Contract

`txing-unit-hardware-worker` is the root-owned board-local hardware adapter for
the current `unit` device type. It runs as a subordinate systemd service under
`txing-unit.target` and communicates with `txing-unit-daemon` over a Unix
domain socket.

## Ownership Boundary

- `txing-unit-daemon` owns MCP sessions, active-control leases, REDCON policy,
  MQTT/cloud publication, board shadow state, and public actuator
  authorization.
- `txing-unit-hardware-worker` owns local hardware devices, motor calibration,
  PWM/GPIO/I2C/CAN/vendor SDK access, command application, local hardware
  readiness, and local failsafe neutralization.
- The worker API must not include MCP session IDs, actors, active-control
  epochs, REDCON values, MQTT topics, cloud identities, or Thing Shadow state.
- The daemon treats worker unavailability or non-ready status as actuator
  unavailable and rejects motion tools after MCP active-control validation.

## gRPC API

The canonical API is `txing.unit.hardware.v1.UnitHardware` in
`devices/unit/proto/txing/unit/hardware/v1/unit_hardware.proto`.

RPCs:

- `GetStatus(GetStatusRequest) -> HardwareStatus`
- `ApplyVelocity(ApplyVelocityRequest) -> ApplyVelocityResponse`
- `Stop(StopRequest) -> StopResponse`

`ApplyVelocityRequest` carries a strict ROS `Twist` shape:

- `linear.x/y/z` are meters per second.
- `angular.x/y/z` are radians per second.
- v1 accepts only `linear.x` and `angular.z`.
- non-zero unsupported axes are rejected.
- every command includes canonical `deadline_unix_ms`; the worker may clamp it
  to its configured watchdog window.
- `command_id` is for logs and observability only, not authorization.

`HardwareStatus` reports local readiness and motion only:

- `state`: `STARTING`, `READY`, `DEGRADED`, `ERROR`, or `STOPPED`
- `actuator_ready`
- `last_error`
- `motion.leftSpeed`, `motion.rightSpeed`, and `motion.sequence`
- `active_deadline_unix_ms`
- `worker_version`

## Safety Behavior

Systemd supervision is not a motion-control safety mechanism. The worker must
neutralize motors locally on:

- command deadline expiry
- explicit `Stop`
- SIGINT or SIGTERM
- normal shutdown
- hardware write/open errors
- daemon disconnect detection when the transport exposes it

The daemon also sends `Stop` when active control is released, taken over,
expires, when REDCON reaches `4`, when MCP transport changes, when sessions
close, and during daemon shutdown. If the worker crashes, the daemon marks
actuators unavailable and rejects future motion commands until `GetStatus`
reports readiness again.

## Future Sensors

The worker naming and package layout reserve room for future ROS-style
IMU/6DOF semantics. This contract does not define IMU publishing, 6DOF APIs, or
sensor fusion yet.
