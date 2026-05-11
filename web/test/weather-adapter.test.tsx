import { describe, expect, test } from 'bun:test'
import weatherDeviceAdapter from '../../devices/weather/web/weather-adapter'
import {
  extractWeatherPowerReportedState,
  extractWeatherReportedState,
} from '../../devices/weather/web/weather-model'

describe('weather adapter', () => {
  test('extracts weather metrics from weather shadow', () => {
    const shadow = {
      namedShadows: {
        power: {
          state: {
            reported: {
              batteryMv: 3512,
            },
          },
        },
        weather: {
          state: {
            reported: {
              measuredTemperature: 21.625,
              measuredPressure: 100.8,
              measuredHumidity: 44.5,
            },
          },
        },
      },
    }

    expect(extractWeatherReportedState(shadow)).toEqual({
      measuredTemperature: 21.625,
      measuredPressure: 100.8,
      measuredHumidity: 44.5,
    })
    expect(extractWeatherPowerReportedState(shadow)).toEqual({ batteryMv: 3512 })
    expect(weatherDeviceAdapter.extractTelemetry(shadow).reportedBatteryMv).toBe(3512)
  })
})
