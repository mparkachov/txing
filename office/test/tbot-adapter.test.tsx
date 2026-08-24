import { describe, expect, test } from 'bun:test'
import { renderToStaticMarkup } from 'react-dom/server'
import tbotDeviceAdapter from '../../devices/tbot/web/tbot-adapter'

describe('tbot adapter', () => {
  test('retains bot controls while presenting Thread watch-link state', () => {
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
        mcpTransport: 'mqtt-jsonrpc',
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
        shadow: {},
        videoChannelName: 'tbot-a1-board-video',
      }),
    )

    expect(tbotDeviceAdapter.type).toBe('tbot')
    expect(tbotDeviceAdapter.canUseDriveControl(2)).toBe(true)
    expect(tbotDeviceAdapter.canUseBoardVideo(1)).toBe(true)
    expect(markup).toContain('TBOT')
    expect(markup).toContain('aria-label="Thread online"')
    expect(markup).toContain('data-drive-mode="mqtt-jsonrpc"')
  })
})
