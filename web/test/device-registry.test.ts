import { describe, expect, test } from 'bun:test'
import { getDeviceWebAdapter, listDeviceWebAdapters } from '../src/device-registry'

describe('device web adapter registry', () => {
  test('registers installed device detail adapters and returns null for unknown device types', () => {
    const timeAdapter = getDeviceWebAdapter('time')
    const unitAdapter = getDeviceWebAdapter('unit')
    const weatherAdapter = getDeviceWebAdapter('weather')
    const powerAdapter = getDeviceWebAdapter('power')

    expect(timeAdapter?.type).toBe('time')
    expect(timeAdapter?.canUseBoardVideo(1)).toBe(false)
    expect(timeAdapter?.canUseDriveControl(1)).toBe(false)
    expect(unitAdapter?.type).toBe('unit')
    expect(unitAdapter?.buildVideoChannelName('unit-a1')).toBe('unit-a1-board-video')
    expect(unitAdapter?.canUseBoardVideo(1)).toBe(true)
    expect(unitAdapter?.canUseBoardVideo(2)).toBe(false)
    expect(unitAdapter?.canUseDriveControl(1)).toBe(true)
    expect(unitAdapter?.canUseDriveControl(2)).toBe(true)
    expect(unitAdapter?.canUseDriveControl(3)).toBe(false)
    expect(weatherAdapter?.type).toBe('weather')
    expect(weatherAdapter?.canUseDriveControl(1)).toBe(false)
    expect(powerAdapter?.type).toBe('power')
    expect(powerAdapter?.canUseBoardVideo(1)).toBe(false)
    expect(powerAdapter?.canUseDriveControl(1)).toBe(false)
    expect(getDeviceWebAdapter('sensor')).toBeNull()
    expect(listDeviceWebAdapters().map((adapter) => adapter.type)).toEqual([
      'time',
      'unit',
      'weather',
      'power',
    ])
  })

  test('keeps unit auto-open behavior behind the adapter', () => {
    const unitAdapter = getDeviceWebAdapter('unit')

    expect(
      unitAdapter?.getAutoOpenState({
        detailRedcon: 1,
        routeKind: 'device',
        hasActiveSession: true,
        nextRedcon: 1,
      }),
    ).toEqual({
      isDetailPanelOpen: true,
      isBoardVideoExpanded: true,
    })

    expect(
      unitAdapter?.getAutoOpenState({
        detailRedcon: 2,
        routeKind: 'device',
        hasActiveSession: true,
        nextRedcon: 2,
      }),
    ).toEqual({
      isDetailPanelOpen: true,
      isBoardVideoExpanded: false,
    })

    expect(
      unitAdapter?.getAutoOpenState({
        detailRedcon: 1,
        routeKind: 'device_video',
        hasActiveSession: true,
        nextRedcon: 1,
      }),
    ).toBeNull()
  })
})
