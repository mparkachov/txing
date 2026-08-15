import { describe, expect, test } from 'bun:test'
import { renderToStaticMarkup } from 'react-dom/server'
import cyberbrickDeviceAdapter from '../../devices/cyberbrick/web/cyberbrick-adapter'

describe('cyberbrick adapter', () => {
  test('uses an independent MAVLink control path and the existing video REDCON gate', () => {
    expect(cyberbrickDeviceAdapter.type).toBe('cyberbrick')
    expect(cyberbrickDeviceAdapter.displayName).toBe('Cyberbrick')
    expect(cyberbrickDeviceAdapter.buildVideoChannelName('cyberbrick-a1')).toBe(
      'cyberbrick-a1-board-video',
    )
    expect(cyberbrickDeviceAdapter.canUseBoardVideo(1)).toBe(true)
    expect(cyberbrickDeviceAdapter.canUseBoardVideo(2)).toBe(false)
    expect(cyberbrickDeviceAdapter.canUseBoardVideo(null)).toBe(false)
    expect(cyberbrickDeviceAdapter.buildMavlinkChannelName?.('cyberbrick-a1')).toBe(
      'cyberbrick-a1-mavlink',
    )
    expect(cyberbrickDeviceAdapter.canUseDriveControl(1)).toBe(false)
    expect(cyberbrickDeviceAdapter.canUseDriveControl(2)).toBe(false)
    expect(cyberbrickDeviceAdapter.canUseDriveControl(3)).toBe(false)

    const renderedVideo = cyberbrickDeviceAdapter.renderVideo({
      debugEnabled: false,
      onRuntimeError: () => {},
      resolveIdToken: async () => 'token',
      videoChannelName: 'cyberbrick-a1-board-video',
    }) as { props: { channelName: string } }
    expect(renderedVideo.props.channelName).toBe('cyberbrick-a1-board-video')
  })

  test('extracts unit-shaped board, battery, and MCU telemetry', () => {
    const shadow = {
      namedShadows: {
        sparkplug: {
          state: {
            reported: {
              topic: {
                deviceId: 'cyberbrick-a1',
                messageType: 'DDATA',
              },
              payload: {
                metrics: {
                  capability: {
                    ble: true,
                    power: true,
                  },
                  redcon: 2,
                },
              },
            },
          },
        },
        power: { state: { reported: { batteryMv: 3980 } } },
        board: {
          state: {
            reported: {
              power: true,
              wifi: { online: true, ipv4: '192.0.2.10', ipv6: null },
            },
          },
        },
      },
    }

    expect(cyberbrickDeviceAdapter.extractTelemetry(shadow)).toEqual({
      reportedBatteryMv: 3980,
      reportedBoardPower: true,
      reportedBoardOnline: true,
      reportedMcuOnline: true,
      reportedMcuPower: true,
    })
  })

  test('matches unit detail auto-open and close behavior', () => {
    expect(
      cyberbrickDeviceAdapter.getAutoOpenState({
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
      cyberbrickDeviceAdapter.getAutoOpenState({
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
      cyberbrickDeviceAdapter.shouldCloseDetail({
        detailRedcon: 2,
        reportedRedcon: 3,
      }),
    ).toBe(true)
    expect(
      cyberbrickDeviceAdapter.shouldCloseDetail({
        detailRedcon: 1,
        reportedRedcon: 1,
      }),
    ).toBe(false)
  })

  test('renders the Cyberbrick MAVLink control panel without an MCP affordance', () => {
    const rendered = renderToStaticMarkup(
      cyberbrickDeviceAdapter.renderDetail({
        callMcpTool: async () => null,
        isBoardVideoExpanded: false,
        isDebugEnabled: false,
        mavlinkActor: 'operator@example.test',
        mavlinkChannelName: 'cyberbrick-a1-mavlink',
        mavlinkRegion: 'eu-central-1',
        isShadowConnected: true,
        isTakeControlPending: false,
        mcpTransport: 'mqtt-jsonrpc',
        onBoardVideoRuntimeError: () => {},
        onTakeControl: () => {},
        onToggleDebug: () => {},
        reportedBatteryMv: 3980,
        reportedBoardLeftTrackSpeed: 0,
        reportedBoardOnline: true,
        reportedBoardRightTrackSpeed: 0,
        reportedMcuOnline: true,
        reportedRedcon: 2,
        resolveIdToken: async () => 'token',
        robotControl: {
          activeRequired: true,
          activeTtlMs: 30_000,
          activeHeldByCaller: false,
          activeOwnerSessionId: null,
          activeExpiresAtMs: null,
          activeEpoch: null,
          activeControl: null,
        },
        shadow: {},
        videoChannelName: 'cyberbrick-a1-board-video',
      }),
    )

    expect(rendered).toContain('Cyberbrick status')
    expect(rendered).toContain('CYBERBRICK')
    expect(rendered).toContain('MAVLink control')
    expect(rendered).toContain('Acquire control')
    expect(rendered).toContain('MAVLink over an independent WebRTC data channel')
    expect(rendered).not.toContain('MCP')
  })
})
