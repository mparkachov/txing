import { describe, expect, test } from 'bun:test'
import powerNrfDeviceAdapter from '../../devices/power-nrf/web/power-nrf-adapter'

describe('power-nrf adapter', () => {
  test('reuses power detail behavior for power-nrf battery telemetry', () => {
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

    expect(powerNrfDeviceAdapter.type).toBe('power-nrf')
    expect(powerNrfDeviceAdapter.displayName).toBe('Power nRF')
    expect(powerNrfDeviceAdapter.extractTelemetry(shadow).reportedBatteryMv).toBe(3512)
    expect(powerNrfDeviceAdapter.canUseBoardVideo(1)).toBe(false)
    expect(powerNrfDeviceAdapter.canUseDriveControl(1)).toBe(false)
  })

  test('uses the power REDCON detail open and close behavior', () => {
    expect(
      powerNrfDeviceAdapter.getAutoOpenState({
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
      powerNrfDeviceAdapter.shouldCloseDetail({ detailRedcon: 3, reportedRedcon: 4 }),
    ).toBe(true)
  })
})
