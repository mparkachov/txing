import { describe, expect, test } from 'bun:test'
import {
  formatCatalogDetailLine,
  getRouteDetailPanelOpenState,
  shouldRenderRouteCatalogPanel,
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

  test('shows town and rig catalog detail panels only when reported redcon is 1', () => {
    expect(
      shouldRenderRouteCatalogPanel({
        thingTypeName: 'town',
        reportedRedcon: 1,
      }),
    ).toBe(true)
    expect(
      shouldRenderRouteCatalogPanel({
        thingTypeName: 'rig',
        reportedRedcon: 1,
      }),
    ).toBe(true)
    expect(
      shouldRenderRouteCatalogPanel({
        thingTypeName: 'town',
        reportedRedcon: null,
      }),
    ).toBe(false)
    expect(
      shouldRenderRouteCatalogPanel({
        thingTypeName: 'rig',
        reportedRedcon: 4,
      }),
    ).toBe(false)
    expect(
      shouldRenderRouteCatalogPanel({
        thingTypeName: 'unit',
        reportedRedcon: 1,
      }),
    ).toBe(false)
  })

  test('formats catalog detail lines as short-id then name when available', () => {
    expect(formatCatalogDetailLine('a1', 'alpha')).toBe('a1: alpha')
    expect(formatCatalogDetailLine(null, 'alpha')).toBe('alpha')
  })
})
