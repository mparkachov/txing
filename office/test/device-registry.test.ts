import { describe, expect, test } from 'bun:test'
import type { DeviceDetailRenderProps } from '../src/device-adapter'
import { getDeviceWebAdapter, listDeviceWebAdapters } from '../src/device-registry'

describe('device web adapter registry', () => {
  test('registers installed device detail adapters and returns null for unknown device types', () => {
    const cloudMcuAdapter = getDeviceWebAdapter('cloud-mcu')
    const unitAdapter = getDeviceWebAdapter('unit')
    const weatherAdapter = getDeviceWebAdapter('weather')
    const powerAdapter = getDeviceWebAdapter('power')
    const powerSiAdapter = getDeviceWebAdapter('power-si')

    expect(cloudMcuAdapter?.type).toBe('cloud-mcu')
    expect(cloudMcuAdapter?.canUseBoardVideo(1)).toBe(false)
    expect(cloudMcuAdapter?.canUseDriveControl(1)).toBe(false)
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
    expect(powerSiAdapter?.type).toBe('power-si')
    expect(powerSiAdapter?.displayName).toBe('Power SI')
    expect(powerSiAdapter?.canUseBoardVideo(1)).toBe(false)
    expect(powerSiAdapter?.canUseDriveControl(1)).toBe(false)
    expect(getDeviceWebAdapter('sensor')).toBeNull()
    expect(listDeviceWebAdapters().map((adapter) => adapter.type)).toEqual([
      'cloud-mcu',
      'unit',
      'weather',
      'power',
      'power-si',
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

  test('keeps registered non-mcp device detail panels view-only', () => {
    const nonMcpDevices = [
      {
        type: 'cloud-mcu',
        shadow: {
          namedShadows: {
            power: {
              state: {
                reported: {
                  desiredRedcon: 3,
                  ecsTaskStatus: 'RUNNING',
                  powered: true,
                },
              },
            },
          },
        },
      },
      {
        type: 'weather',
        shadow: {
          namedShadows: {
            power: { state: { reported: { batteryMv: 4100 } } },
            weather: {
              state: {
                reported: {
                  measuredHumidity: 45.5,
                  measuredPressure: 101.2,
                  measuredTemperature: 22.75,
                },
              },
            },
          },
        },
      },
      {
        type: 'power',
        shadow: {
          namedShadows: {
            power: { state: { reported: { batteryMv: 3890 } } },
          },
        },
      },
      {
        type: 'power-si',
        shadow: {
          namedShadows: {
            power: { state: { reported: { batteryMv: 3890 } } },
            thread: { state: { reported: { serviceType: '_txing-coap._udp' } } },
          },
        },
      },
    ]

    for (const { shadow, type } of nonMcpDevices) {
      const adapter = getDeviceWebAdapter(type)

      expect(adapter?.canUseDriveControl(1)).toBe(false)
      expect(adapter?.canUseDriveControl(2)).toBe(false)
      expect(adapter?.canUseBoardVideo(1)).toBe(false)

      const renderedText = collectRenderedText(adapter!.renderDetail(createRenderProps(shadow)))

      expect(renderedText).not.toContain('Take control')
      expect(renderedText).not.toContain('MCP')
      expect(renderedText).not.toContain('cmd_vel')
      expect(renderedText).not.toContain('Board video')
    }
  })
})

const createRenderProps = (shadow: unknown): DeviceDetailRenderProps => ({
  callMcpTool: async () => null,
  isBoardVideoExpanded: false,
  isDebugEnabled: false,
  isShadowConnected: true,
  isTakeControlPending: false,
  mcpTransport: null,
  onBoardVideoRuntimeError: () => {},
  onTakeControl: () => {},
  onToggleDebug: () => {},
  reportedBatteryMv: null,
  reportedBoardLeftTrackSpeed: null,
  reportedBoardOnline: null,
  reportedBoardRightTrackSpeed: null,
  reportedMcuOnline: null,
  reportedRedcon: 1,
  resolveIdToken: async () => 'token',
  robotControl: null,
  shadow,
  videoChannelName: 'test-video',
})

const collectRenderedText = (node: unknown): string => {
  if (
    node === null ||
    node === undefined ||
    typeof node === 'boolean' ||
    typeof node === 'symbol'
  ) {
    return ''
  }
  if (typeof node === 'string' || typeof node === 'number' || typeof node === 'bigint') {
    return String(node)
  }
  if (Array.isArray(node)) {
    return node.map(collectRenderedText).join('')
  }
  if (typeof node !== 'object') {
    return ''
  }

  const element = node as {
    props?: Record<string, unknown>
    type?: unknown
  }
  if (typeof element.type === 'function') {
    return collectRenderedText(element.type(element.props ?? {}))
  }

  const propText = Object.entries(element.props ?? {})
    .filter(([name, value]) => name !== 'children' && typeof value === 'string')
    .map(([, value]) => value)
    .join('')

  return `${propText}${collectRenderedText(element.props?.children)}`
}
