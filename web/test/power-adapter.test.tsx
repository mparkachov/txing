import { describe, expect, test } from 'bun:test'
import powerDeviceAdapter from '../../devices/power/web/power-adapter'
import { extractPowerReportedState } from '../../devices/power/web/power-model'

describe('power adapter', () => {
  test('extracts battery metrics from power shadow', () => {
    const shadow = {
      namedShadows: {
        power: {
          state: {
            reported: {
              batteryMv: 3512,
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

  test('auto-opens detail panel at the lowest commandable power REDCON', () => {
    expect(
      powerDeviceAdapter.getAutoOpenState({
        detailRedcon: 3,
        routeKind: 'device',
        hasActiveSession: true,
        nextRedcon: 3,
      }),
    ).toEqual({
      isDetailPanelOpen: true,
      isBoardVideoExpanded: false,
    })
    expect(
      powerDeviceAdapter.getAutoOpenState({
        detailRedcon: 3,
        routeKind: 'device',
        hasActiveSession: true,
        nextRedcon: 2,
      }),
    ).toBeNull()
    expect(
      powerDeviceAdapter.getAutoOpenState({
        detailRedcon: 3,
        routeKind: 'device',
        hasActiveSession: true,
        nextRedcon: 4,
      }),
    ).toBeNull()
    expect(
      powerDeviceAdapter.getAutoOpenState({
        detailRedcon: 3,
        routeKind: 'device_video',
        hasActiveSession: true,
        nextRedcon: 3,
      }),
    ).toBeNull()
  })

  test('closes detail panel away from the lowest commandable power REDCON', () => {
    expect(
      powerDeviceAdapter.shouldCloseDetail({ detailRedcon: 3, reportedRedcon: 3 }),
    ).toBe(false)
    expect(
      powerDeviceAdapter.shouldCloseDetail({ detailRedcon: 3, reportedRedcon: 4 }),
    ).toBe(true)
    expect(
      powerDeviceAdapter.shouldCloseDetail({ detailRedcon: 3, reportedRedcon: null }),
    ).toBe(true)
    expect(
      powerDeviceAdapter.shouldCloseDetail({ detailRedcon: null, reportedRedcon: 3 }),
    ).toBe(true)
  })
})
