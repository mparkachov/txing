# Weather Txing

`weather` is a BLE connected-idle txing type for an outside weather node:

- MCU: Seeed Studio XIAO nRF54L15
- Sensor: Grove BME280 on I2C
- Device name default: `outside`
- Rig type: `raspi`
- Capability: `sparkplug`

The device is registered in AWS through the existing AWS device flow. During
manual flashing, `weather::mcu::flash <aws-thing-id>` stores that Thing ID in
MCU factory data. Firmware advertises the Thing ID as its BLE local name, and
the Raspberry Pi 5 rig connects over its built-in BLE adapter.

Sparkplug behavior:

- BLE connected idle publishes DBIRTH/DDATA with `redcon=4`.
- `DCMD.redcon=3`, `2`, or `1` wakes active mode and reports actual `redcon=3`.
- Active mode turns the LED on and reports BME280 data every second.
- Returning to `DCMD.redcon=4` stops telemetry and keeps the BLE connection idle.

The weather implementation does not use Matter, Thread, `chip-tool`, online
provisioning, MCP, or video.
