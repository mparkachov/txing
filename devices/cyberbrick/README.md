# Cyberbrick Device

`cyberbrick` is a `raspi`-rig device type with the full Sparkplug, BLE, power,
board, MCP, and video capability set. Its declared REDCON ladder is:

| REDCON | Required capabilities |
| --- | --- |
| 4 | Sparkplug, BLE |
| 3 | Sparkplug, BLE, power |
| 2 | Sparkplug, BLE, power, board, MCP |
| 1 | Sparkplug, BLE, power, board, MCP, video |

The canonical device declaration is [manifest.toml](manifest.toml). It owns the
Cyberbrick shadow schemas and defaults under [aws/](aws/), and its Office
adapter under [web/](web/).

## Board runtime

Cyberbrick runs on a supported Raspberry Pi board host using Alpine Linux,
OpenRC services, and the `cyberbrick-v*` release stream. Its board runtime is
the `txing-cyberbrick-daemon`, `txing-cyberbrick-kvs-master`, and
`txing-cyberbrick-hardware-worker` binaries. The static
`txing-cyberbrick-ardupilot` ArduRover binary is an optional fourth component;
it manually replaces the hardware worker as the PWM owner. The shared board
implementation is in [../common/board/README.md](../common/board/README.md).

## References

- [Cyberbrick board installation](../../docs/installation.md#cyberbrick-board-host)
- [Cyberbrick release artifacts](../../docs/artifacts.md#cyberbrick-board)
- [Cyberbrick board video contract](docs/board-video.md)
- [Shared board contract](../../docs/components/board.md)
