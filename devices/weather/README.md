# Weather Txing

`weather` is a BLE-advertised txing type for an outside weather node:

- MCU: Seeed Studio XIAO nRF54L15
- Sensor: BME280 on I2C, powered by XIAO D1 only during samples
- Device name default: `outside`
- Rig type: `raspi`
- Capabilities: `sparkplug`, `ble`, `power`, `weather`

The device is registered through the existing AWS device flow. During manual NVE
programming, the AWS Thing ID is stored as REDCON factory data. Firmware
advertises that Thing ID as its BLE local name, and the Raspberry Pi 5 rig uses
that local name as the presence identity.

Weather is REDCON 4 only. It has no REDCON 3 mode. While connected in REDCON 4,
the MCU reports battery voltage and BME280 measurements every 60 seconds. A
REDCON 3 command is rejected by the rig before BLE write and by firmware if sent
directly. A REDCON 4 GATT command is sent as write-without-response and is
treated as successful by the rig only after a GATT state read confirms REDCON 4;
measurement sampling and notifications run after the firmware accepts the
idempotent idle target. Advertisement-only sightings refresh local scanner
identity/freshness inside the rig and trigger GATT connection attempts, but they
do not update Thing Shadows. Sparkplug `capability.ble`, `capability.power`, and
`capability.weather` become active only after a successful REDCON 4 GATT state
read. Individual BME280 measurement reads may fail without changing the REDCON
4 availability contract.

The weather implementation does not use Matter, Thread, `chip-tool`, online
provisioning, MCP, video, or a weather-specific Python rig stack.
