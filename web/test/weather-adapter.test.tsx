import { describe, expect, test } from 'bun:test'
import weatherDeviceAdapter from '../../devices/weather/web/weather-adapter'
import { extractWeatherReportedState } from '../../devices/weather/web/weather-model'

describe('weather adapter', () => {
  test('extracts weather metrics from sparkplug shadow', () => {
    const shadow = {
      namedShadows: {
        sparkplug: {
          state: {
            reported: {
              payload: {
                metrics: {
                  redcon: 4,
                  batteryMv: 3512,
                  measuredTemperature: 21.625,
                  measuredPressure: 100.8,
                  measuredHumidity: 44.5,
                },
              },
            },
          },
        },
      },
    }

    expect(extractWeatherReportedState(shadow)).toEqual({
      batteryMv: 3512,
      measuredTemperature: 21.625,
      measuredPressure: 100.8,
      measuredHumidity: 44.5,
    })
    expect(weatherDeviceAdapter.extractTelemetry(shadow).reportedBatteryMv).toBe(3512)
  })
})
