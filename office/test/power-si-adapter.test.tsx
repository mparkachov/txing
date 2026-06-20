import { describe, expect, test } from 'bun:test'
import powerSiDeviceAdapter from '../../devices/power-si/web/power-si-adapter'

describe('power-si adapter', () => {
  test('reuses power detail behavior for power-si battery telemetry', () => {
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

    expect(powerSiDeviceAdapter.type).toBe('power-si')
    expect(powerSiDeviceAdapter.displayName).toBe('Power SI')
    expect(powerSiDeviceAdapter.extractTelemetry(shadow).reportedBatteryMv).toBe(3512)
    expect(powerSiDeviceAdapter.canUseBoardVideo(1)).toBe(false)
    expect(powerSiDeviceAdapter.canUseDriveControl(1)).toBe(false)
  })

  test('uses the power REDCON detail open and close behavior', () => {
    expect(
      powerSiDeviceAdapter.getAutoOpenState({
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
      powerSiDeviceAdapter.shouldCloseDetail({ detailRedcon: 3, reportedRedcon: 4 }),
    ).toBe(true)
  })
})
