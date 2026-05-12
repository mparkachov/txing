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

  test('opens weather detail at REDCON 4 when that is the lowest commandable level', () => {
    expect(
      weatherDeviceAdapter.getAutoOpenState({
        detailRedcon: 4,
        routeKind: 'device',
        hasActiveSession: true,
        nextRedcon: 4,
      }),
    ).toEqual({
      isDetailPanelOpen: true,
      isBoardVideoExpanded: false,
    })
    expect(
      weatherDeviceAdapter.getAutoOpenState({
        detailRedcon: 4,
        routeKind: 'device',
        hasActiveSession: true,
        nextRedcon: 4,
      }),
    ).toEqual({
      isDetailPanelOpen: true,
      isBoardVideoExpanded: false,
    })
    expect(
      weatherDeviceAdapter.getAutoOpenState({
        detailRedcon: 4,
        routeKind: 'device_video',
        hasActiveSession: true,
        nextRedcon: 4,
      }),
    ).toBeNull()
    expect(
      weatherDeviceAdapter.shouldCloseDetail({
        detailRedcon: 4,
        reportedRedcon: 4,
      }),
    ).toBe(false)
    expect(
      weatherDeviceAdapter.shouldCloseDetail({
        detailRedcon: 4,
        reportedRedcon: null,
      }),
    ).toBe(true)
  })
})
