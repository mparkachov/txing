# Cyberbrick Device

`cyberbrick` is a `raspi`-rig device type with the full Sparkplug, BLE, power,
board, MAVLink, and video capability set. Its declared REDCON ladder is:

| REDCON | Required capabilities |
| --- | --- |
| 4 | Sparkplug, BLE |
| 3 | Sparkplug, BLE, power |
| 2 | Sparkplug, BLE, power, board, MAVLink |
| 1 | Sparkplug, BLE, power, board, MAVLink, and video |

The canonical device declaration is [manifest.toml](manifest.toml). It owns the
Cyberbrick shadow schemas and defaults under [aws/](aws/), and its Office
adapter under [web/](web/).

## Board runtime

Cyberbrick runs on a supported Raspberry Pi board host using Alpine Linux,
OpenRC services, and the `cyberbrick-v*` release stream. Its MAVLink contract
adds `txing-cyberbrick-mavlink` alongside the daemon and KVS master; ArduPilot
is the PWM owner. Runtime implementation and release cutover are tracked
separately from this contract work. The shared board implementation is in
[../common/board/README.md](../common/board/README.md).

## References

- [Cyberbrick board installation](../../docs/installation.md#cyberbrick-board-host)
- [Cyberbrick release artifacts](../../docs/artifacts.md#cyberbrick-board)
- [Shared board video contract](../../docs/components/board-video.md)
- [Cyberbrick MAVLink contract](../../docs/contracts/cyberbrick-mavlink.md)
- [Shared board contract](../../docs/components/board.md)
