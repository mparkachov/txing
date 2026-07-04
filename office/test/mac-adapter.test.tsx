import { describe, expect, test } from 'bun:test'
import macDeviceAdapter from '../../devices/mac/web/mac-adapter'

describe('mac adapter', () => {
  test('gates video to REDCON 1 and never offers drive control', () => {
    expect(macDeviceAdapter.type).toBe('mac')
    expect(macDeviceAdapter.displayName).toBe('Mac')
    expect(macDeviceAdapter.buildVideoChannelName('mac-a1')).toBe('mac-a1-board-video')
    expect(macDeviceAdapter.canUseBoardVideo(1)).toBe(true)
    expect(macDeviceAdapter.canUseBoardVideo(2)).toBe(false)
    expect(macDeviceAdapter.canUseBoardVideo(null)).toBe(false)
    expect(macDeviceAdapter.canUseDriveControl(1)).toBe(false)
    expect(macDeviceAdapter.canUseDriveControl(2)).toBe(false)
  })

  test('extracts board telemetry and reports no battery or MCU signals', () => {
    const shadow = {
      namedShadows: {
        board: {
          state: {
            reported: {
              power: true,
              wifi: {
                online: true,
                ipv4: '192.0.2.10',
                ipv6: null,
              },
            },
          },
        },
      },
    }

    expect(macDeviceAdapter.extractTelemetry(shadow)).toEqual({
      reportedBatteryMv: null,
      reportedBoardPower: true,
      reportedBoardOnline: true,
      reportedMcuOnline: null,
      reportedMcuPower: null,
    })
    expect(macDeviceAdapter.extractTelemetry({})).toEqual({
      reportedBatteryMv: null,
      reportedBoardPower: null,
      reportedBoardOnline: null,
      reportedMcuOnline: null,
      reportedMcuPower: null,
    })
  })

  test('auto-opens the detail panel for REDCON 1 and 2 with video expanded only at 1', () => {
    expect(
      macDeviceAdapter.getAutoOpenState({
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
      macDeviceAdapter.getAutoOpenState({
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
      macDeviceAdapter.getAutoOpenState({
        detailRedcon: 3,
        routeKind: 'device',
        hasActiveSession: true,
        nextRedcon: 3,
      }),
    ).toBeNull()
    expect(
      macDeviceAdapter.getAutoOpenState({
        detailRedcon: 1,
        routeKind: 'device_video',
        hasActiveSession: true,
        nextRedcon: 1,
      }),
    ).toBeNull()
  })

  test('closes the detail panel when the device leaves REDCON 1 and 2', () => {
    expect(
      macDeviceAdapter.shouldCloseDetail({ detailRedcon: 1, reportedRedcon: 3 }),
    ).toBe(true)
    expect(
      macDeviceAdapter.shouldCloseDetail({ detailRedcon: 2, reportedRedcon: 2 }),
    ).toBe(false)
    expect(
      macDeviceAdapter.shouldCloseDetail({ detailRedcon: null, reportedRedcon: 1 }),
    ).toBe(true)
  })

  test('renders a view-only detail panel without drive controls', () => {
    const rendered = collectRenderedText(
      macDeviceAdapter.renderDetail({
        callMcpTool: async () => null,
        isBoardVideoExpanded: false,
        isDebugEnabled: false,
        isShadowConnected: true,
        isTakeControlPending: false,
        mcpTransport: 'mqtt-jsonrpc',
        onBoardVideoRuntimeError: () => {},
        onTakeControl: () => {},
        onToggleDebug: () => {},
        reportedBatteryMv: null,
        reportedBoardLeftTrackSpeed: null,
        reportedBoardOnline: true,
        reportedBoardRightTrackSpeed: null,
        reportedMcuOnline: null,
        reportedRedcon: 2,
        resolveIdToken: async () => 'token',
        robotControl: null,
        shadow: {},
        videoChannelName: 'mac-a1-board-video',
      }),
    )

    expect(rendered).toContain('MAC')
    expect(rendered).toContain('MCP over MQTT JSON-RPC')
    expect(rendered).not.toContain('Take active control')
    expect(rendered).not.toContain('cmd_vel')
  })
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
