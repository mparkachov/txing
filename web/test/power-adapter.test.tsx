import { describe, expect, test } from 'bun:test'
import powerDeviceAdapter from '../../devices/power/web/power-adapter'
import { extractPowerReportedState } from '../../devices/power/web/power-model'

describe('power adapter', () => {
  test('extracts battery metrics from sparkplug shadow', () => {
    const shadow = {
      namedShadows: {
        sparkplug: {
          state: {
            reported: {
              payload: {
                metrics: {
                  redcon: 4,
                  batteryMv: 3512,
                },
              },
            },
          },
        },
      },
    }

    expect(extractPowerReportedState(shadow)).toEqual({
      batteryMv: 3512,
    })
    expect(powerDeviceAdapter.extractTelemetry(shadow).reportedBatteryMv).toBe(3512)
  })

  test('auto-opens detail panel while power REDCON is below idle', () => {
    expect(
      powerDeviceAdapter.getAutoOpenState({
        routeKind: 'device',
        hasActiveSession: true,
        previousRedcon: null,
        nextRedcon: 3,
      }),
    ).toEqual({
      isDetailPanelOpen: true,
      isBoardVideoExpanded: false,
    })
    expect(
      powerDeviceAdapter.getAutoOpenState({
        routeKind: 'device',
        hasActiveSession: true,
        previousRedcon: 3,
        nextRedcon: 2,
      }),
    ).toBeNull()
    expect(
      powerDeviceAdapter.getAutoOpenState({
        routeKind: 'device',
        hasActiveSession: true,
        previousRedcon: 4,
        nextRedcon: 4,
      }),
    ).toBeNull()
    expect(
      powerDeviceAdapter.getAutoOpenState({
        routeKind: 'device_video',
        hasActiveSession: true,
        previousRedcon: null,
        nextRedcon: 3,
      }),
    ).toBeNull()
  })

  test('closes detail panel when power REDCON is idle or unknown', () => {
    expect(powerDeviceAdapter.shouldCloseDetail(3)).toBe(false)
    expect(powerDeviceAdapter.shouldCloseDetail(4)).toBe(true)
    expect(powerDeviceAdapter.shouldCloseDetail(null)).toBe(true)
  })
})
