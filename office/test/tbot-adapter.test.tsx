import { describe, expect, test } from 'bun:test'
import { renderToStaticMarkup } from 'react-dom/server'
import { MavlinkControlProvider } from '../../devices/cyberbrick/web/MavlinkControlPanel'
import tbotDeviceAdapter from '../../devices/tbot/web/tbot-adapter'

describe('tbot adapter', () => {
  test('uses the independent MAVLink control peer and shows Thread connectivity without a drive gauge group', () => {
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
    expect(markup).not.toContain('TBOT')
    expect(markup).not.toContain('status-track-gauge')
    expect(markup).toContain('aria-label="Thread online"')
    expect(markup).toContain('data-drive-mode="mavlink"')
    expect(markup).not.toContain('ArduPilot / MAVLink')
    expect(markup).not.toContain('status-mavlink-transport')
    expect(markup).not.toContain('MCP')

    const renderedVideo = tbotDeviceAdapter.renderVideo({
      debugEnabled: false,
      onRuntimeError: () => {},
      resolveIdToken: async () => 'token',
      videoChannelName: 'tbot-a1-board-video',
    }) as { props: { channelName: string } }
    expect(renderedVideo.props.channelName).toBe('tbot-a1-board-video')
  })

  test('uses the standard device control action while keeping ArduPilot details in debug', () => {
    const providerProps = {
      actor: 'operator@example.test',
      channelName: 'tbot-a1-mavlink',
      enabled: true,
      initialTarget: { systemId: 1, componentId: 1 },
      onRuntimeError: () => {},
      region: 'eu-central-1',
      resolveIdToken: async () => 'token',
    }
    const normalMarkup = renderToStaticMarkup(
      <MavlinkControlProvider {...providerProps}>
        {tbotDeviceAdapter.renderDetail({
          callMcpTool: async () => null,
          isBoardVideoExpanded: true,
          isDebugEnabled: false,
          isShadowConnected: true,
          isTakeControlPending: false,
          mavlinkActor: providerProps.actor,
          mavlinkChannelName: providerProps.channelName,
          mavlinkRegion: providerProps.region,
          mcpTransport: null,
          onBoardVideoRuntimeError: () => {},
          onTakeControl: () => {},
          onToggleDebug: () => {},
          reportedBatteryMv: 3960,
          reportedBoardLeftTrackSpeed: 0,
          reportedBoardOnline: true,
          reportedBoardRightTrackSpeed: 0,
          reportedMcuOnline: true,
          reportedRedcon: 1,
          resolveIdToken: providerProps.resolveIdToken,
          robotControl: null,
          shadow: {},
          videoChannelName: 'tbot-a1-board-video',
        })}
      </MavlinkControlProvider>,
    )
    const debugMarkup = renderToStaticMarkup(
      <MavlinkControlProvider {...providerProps}>
        {tbotDeviceAdapter.renderDebug?.()}
      </MavlinkControlProvider>,
    )

    expect(normalMarkup).toContain('class="video-overlay-icon" aria-label="Enable Debug"')
    expect(normalMarkup).toContain('aria-label="Take control"')
    expect(normalMarkup).toContain('aria-label="On-screen controller"')
    expect(normalMarkup).toContain('aria-label="Thread online"')
    expect(normalMarkup).toContain('aria-label="Board Wi-Fi online"')
    expect(normalMarkup).toContain('status-battery-shell')
    expect(normalMarkup).not.toContain('status-video-overlay-lockup')
    expect(normalMarkup).toContain('aria-expanded="false"')
    expect(normalMarkup).toContain('class="mavlink-controller" aria-label="TBot controller" hidden=""')
    expect(normalMarkup.indexOf('video-control-overlay')).toBeLessThan(normalMarkup.indexOf('class="mavlink-controller"'))
    expect(normalMarkup).not.toContain('ArduPilot / MAVLink')
    expect(debugMarkup).toContain('ArduPilot / MAVLink')
    expect(debugMarkup).not.toContain('video-control-overlay')
  })
})
