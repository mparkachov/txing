# Weather Txing

`weather` is a watch-only txing type for an outside weather node:

- MCU: Seeed Studio XIAO nRF54L15
- Sensor: Grove BME280 on I2C
- Device name default: `outside`
- Rig type: `raspi`
- Capability: `sparkplug`

The board exposes Matter clusters over Thread. The rig observes an already
commissioned Matter node and publishes Sparkplug B metrics:

- `redcon`: fixed at `4`
- `batteryMv`: projection of Matter `PowerSource.BatVoltage` in mV
- `measuredTemperature`: Celsius
- `measuredPressure`: kPa
- `measuredHumidity`: percent relative humidity

The MCU firmware exposes standard Matter clusters only:

- `TemperatureMeasurement.MeasuredValue`
- `RelativeHumidityMeasurement.MeasuredValue`
- `PressureMeasurement.MeasuredValue`
- `PowerSource.BatVoltage`

Sparkplug metric names are rig-side aliases, not custom Matter attributes.

The first version does not support MCP, video, BLE control, or Sparkplug DCMD
commands. Commission the Matter device manually, then deploy the raspi rig with
the weather thing name and Matter node id.
