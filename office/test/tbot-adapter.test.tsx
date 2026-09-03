import { describe, expect, test } from 'bun:test'
import { renderToStaticMarkup } from 'react-dom/server'
import tbotDeviceAdapter from '../../devices/tbot/web/tbot-adapter'

describe('tbot adapter', () => {
  test('uses the independent MAVLink control peer while retaining TBot and Thread presentation', () => {
    const markup = renderToStaticMarkup(
      tbotDeviceAdapter.renderDetail({
        callMcpTool: async () => null,
        isBoardVideoExpanded: false,
        isDebugEnabled: false,
        isShadowConnected: true,
        isTakeControlPending: false,
        mavlinkActor: '',
        mavlinkChannelName: '',
        mavlinkRegion: '',
        mcpTransport: null,
        onBoardVideoRuntimeError: () => {},
        onTakeControl: () => {},
        onToggleDebug: () => {},
        reportedBatteryMv: 3960,
        reportedBoardLeftTrackSpeed: 0,
        reportedBoardOnline: true,
        reportedBoardRightTrackSpeed: 0,
        reportedMcuOnline: true,
        reportedRedcon: 2,
        resolveIdToken: async () => 'token',
        robotControl: null,
        shadow: {
          namedShadows: {
            mavlink: {
              state: {
                reported: {
                  armed: false,
                  mode: 'hold',
                  target: { systemId: 1, componentId: 1 },
                },
              },
            },
          },
        },
        videoChannelName: 'tbot-a1-board-video',
      }),
    )

    expect(tbotDeviceAdapter.type).toBe('tbot')
    expect(tbotDeviceAdapter.buildMavlinkChannelName?.('tbot-a1')).toBe('tbot-a1-mavlink')
    expect(tbotDeviceAdapter.canUseDriveControl(1)).toBe(false)
    expect(tbotDeviceAdapter.canUseDriveControl(2)).toBe(false)
    expect(tbotDeviceAdapter.canUseBoardVideo(1)).toBe(true)
    expect(markup).toContain('TBOT')
    expect(markup).toContain('aria-label="Thread online"')
    expect(markup).toContain('data-drive-mode="mavlink"')
    expect(markup).toContain('MAVLink control')
    expect(markup).toContain('MAVLink over an independent WebRTC data channel')
    expect(markup).not.toContain('MCP')

    const renderedVideo = tbotDeviceAdapter.renderVideo({
      debugEnabled: false,
      onRuntimeError: () => {},
      resolveIdToken: async () => 'token',
      videoChannelName: 'tbot-a1-board-video',
    }) as { props: { channelName: string } }
    expect(renderedVideo.props.channelName).toBe('tbot-a1-board-video')
  })
})
