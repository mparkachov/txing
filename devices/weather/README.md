# Weather Txing

`weather` is a BLE-advertised txing type for an outside weather node:

- MCU: Seeed Studio XIAO nRF54L15
- Sensor: Grove BME280 on I2C
- Device name default: `outside`
- Rig type: `raspi`
- Capability: `sparkplug`

The device is registered in AWS through the existing AWS device flow. During
manual flashing, `weather::mcu::flash <aws-thing-id>` stores that Thing ID in
MCU factory data. Firmware advertises the Thing ID as its BLE local name, and
the Raspberry Pi 5 rig uses that local name as the presence identity.

Sparkplug behavior:

- Fresh Thing-name advertisements publish DBIRTH/DDATA with `redcon=4`.
- Missing advertisements publish DDEATH after the presence timeout.
- Weather measurements and REDCON commands are modeled through the weather BLE
  GATT contract, but this device type is currently parked while BLE behavior is
  rebuilt separately.

The weather implementation does not use Matter, Thread, `chip-tool`, online
provisioning, MCP, or video.
