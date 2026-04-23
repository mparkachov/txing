import { describe, expect, test } from 'bun:test'
import {
  formatCatalogDetailLine,
  getAutoOpenDeviceDetailPanelState,
  getRouteDetailPanelOpenState,
} from '../src/level-detail-panel'

describe('level detail panel helpers', () => {
  test('auto-opens the matching catalog detail panel for town and rig routes', () => {
    expect(getRouteDetailPanelOpenState({ kind: 'town', town: 'berlin' })).toEqual({
      isTownPanelOpen: true,
      isRigPanelOpen: false,
    })
    expect(getRouteDetailPanelOpenState({ kind: 'rig', town: 'berlin', rig: 'alpha' })).toEqual({
      isTownPanelOpen: false,
      isRigPanelOpen: true,
    })
    expect(
      getRouteDetailPanelOpenState({ kind: 'device', town: 'berlin', rig: 'alpha', device: 'unit-a1' }),
    ).toEqual({
      isTownPanelOpen: false,
      isRigPanelOpen: false,
    })
  })

  test('auto-opens the device detail panel and board video only when the active device reaches redcon 1', () => {
    expect(
      getAutoOpenDeviceDetailPanelState({
        route: { kind: 'device', town: 'berlin', rig: 'alpha', device: 'unit-a1' },
        hasActiveSession: true,
        previousRedcon: 2,
        nextRedcon: 1,
      }),
    ).toEqual({
      isBotPanelOpen: true,
      isBoardVideoExpanded: true,
    })

    expect(
      getAutoOpenDeviceDetailPanelState({
        route: { kind: 'device', town: 'berlin', rig: 'alpha', device: 'unit-a1' },
        hasActiveSession: true,
        previousRedcon: 1,
        nextRedcon: 1,
      }),
    ).toBeNull()

    expect(
      getAutoOpenDeviceDetailPanelState({
        route: { kind: 'device_video', town: 'berlin', rig: 'alpha', device: 'unit-a1' },
        hasActiveSession: true,
        previousRedcon: 2,
        nextRedcon: 1,
      }),
    ).toBeNull()

    expect(
      getAutoOpenDeviceDetailPanelState({
        route: { kind: 'device', town: 'berlin', rig: 'alpha', device: 'unit-a1' },
        hasActiveSession: false,
        previousRedcon: 2,
        nextRedcon: 1,
      }),
    ).toBeNull()
  })

  test('formats catalog detail lines as short-id then name when available', () => {
    expect(formatCatalogDetailLine('a1', 'alpha')).toBe('a1: alpha')
    expect(formatCatalogDetailLine(null, 'alpha')).toBe('alpha')
  })
})
