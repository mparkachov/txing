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
    expect(unitAdapter?.type).toBe('unit')
    expect(unitAdapter?.buildVideoChannelName('unit-a1')).toBe('unit-a1-board-video')
    expect(weatherAdapter?.type).toBe('weather')
    expect(powerAdapter?.type).toBe('power')
    expect(powerAdapter?.canUseBoardVideo(1)).toBe(false)
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
        routeKind: 'device',
        hasActiveSession: true,
        previousRedcon: 2,
        nextRedcon: 1,
      }),
    ).toEqual({
      isDetailPanelOpen: true,
      isBoardVideoExpanded: true,
    })

    expect(
      unitAdapter?.getAutoOpenState({
        routeKind: 'device_video',
        hasActiveSession: true,
        previousRedcon: 2,
        nextRedcon: 1,
      }),
    ).toBeNull()
  })
})
