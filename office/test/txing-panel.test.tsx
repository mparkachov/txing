import { describe, expect, test } from 'bun:test'
import { renderToStaticMarkup } from 'react-dom/server'
import TxingPanel from '../../devices/unit/web/TxingPanel'

describe('txing panel', () => {
  test('renders device-specific gauges and connectivity indicators without sparkplug controls', () => {
    const markup = renderToStaticMarkup(
      <TxingPanel
        isBoardVideoExpanded={true}
        isDebugEnabled={false}
        isShadowConnected={true}
        isTakeControlPending={false}
        mcpTransport="webrtc-datachannel"
        onTakeControl={() => {}}
        onToggleDebug={() => {}}
        robotControl={null}
        reportedRedcon={1}
        reportedBatteryMv={3960}
        reportedBoardLeftTrackSpeed={60}
        reportedBoardOnline={true}
        reportedBoardRightTrackSpeed={-30}
        reportedMcuOnline={true}
        videoChannelName="unit-local-board-video"
        resolveIdToken={async () => 'token'}
        onBoardVideoRuntimeError={() => {}}
      />,
    )

    expect(markup).toContain('BOT')
    expect(markup).toContain('status-video-overlay')
    expect(markup).toContain('class="video-overlay-icon" aria-label="Enable Debug"')
    expect(markup).toContain('video-control-overlay')
    expect(markup).toContain('data-control-owner="unknown"')
    expect(markup).toContain('MCP active-control status pending')
    expect(markup).toContain('MCP over WebRTC data channel')
    expect(markup).toContain('aria-label="Enable Debug"')
    expect(markup).toContain('data-track-side="left"')
    expect(markup).toContain('data-track-speed="60"')
    expect(markup).toContain('aria-label="Left track forward 60 percent"')
    expect(markup).toContain('data-track-side="right"')
    expect(markup).toContain('data-track-speed="-30"')
    expect(markup).toContain('aria-label="Right track reverse 30 percent"')
    expect(markup).toContain('status-track-gauge-needle status-track-forward')
    expect(markup).toContain('status-track-gauge-needle status-track-reverse')
    expect(markup).toContain('status-battery-shell')
    expect(markup).toContain('Battery 72 percent at 3960 millivolts')
    expect(markup).toContain('aria-label="BLE online"')
    expect(markup).toContain('aria-label="Board Wi-Fi online"')
    expect(markup).not.toContain('Load Shadow')
    expect(markup).not.toContain('Connect')
    expect(markup).not.toContain('aria-label="Take control"')
    expect(markup).not.toContain('status-redcon-dot')
    expect(markup).not.toContain('status-switch-track')
  })

  test('renders a REDCON 2 MQTT drive panel without board video', () => {
    const markup = renderToStaticMarkup(
      <TxingPanel
        isBoardVideoExpanded={true}
        isDebugEnabled={false}
        isShadowConnected={true}
        isTakeControlPending={false}
        mcpTransport="mqtt-jsonrpc"
        onTakeControl={() => {}}
        onToggleDebug={() => {}}
        robotControl={null}
        reportedRedcon={2}
        reportedBatteryMv={3960}
        reportedBoardLeftTrackSpeed={25}
        reportedBoardOnline={true}
        reportedBoardRightTrackSpeed={25}
        reportedMcuOnline={true}
        videoChannelName="unit-local-board-video"
        resolveIdToken={async () => 'token'}
        onBoardVideoRuntimeError={() => {}}
      />,
    )

    expect(markup).toContain('status-video-offline-surface')
    expect(markup).toContain('data-drive-mode="mqtt-jsonrpc"')
    expect(markup).toContain('MCP over MQTT JSON-RPC')
    expect(markup).toContain('video-control-overlay')
    expect(markup).toContain('data-control-owner="unknown"')
    expect(markup).toContain('data-track-side="left"')
    expect(markup).toContain('data-track-side="right"')
    expect(markup).not.toContain('aria-label="Enable Debug"')
    expect(markup).not.toContain('txing-video-panel')
  })

  test('renders no active MCP owner as an actionable take-control affordance', () => {
    const markup = renderToStaticMarkup(
      <TxingPanel
        isBoardVideoExpanded={true}
        isDebugEnabled={false}
        isShadowConnected={true}
        isTakeControlPending={false}
        mcpTransport="webrtc-datachannel"
        onTakeControl={() => {}}
        onToggleDebug={() => {}}
        robotControl={{
          activeRequired: true,
          activeTtlMs: 5000,
          activeHeldByCaller: false,
          activeOwnerSessionId: null,
          activeExpiresAtMs: null,
          activeEpoch: null,
          activeControl: null,
        }}
        reportedRedcon={1}
        reportedBatteryMv={3960}
        reportedBoardLeftTrackSpeed={0}
        reportedBoardOnline={true}
        reportedBoardRightTrackSpeed={0}
        reportedMcuOnline={true}
        videoChannelName="unit-local-board-video"
        resolveIdToken={async () => 'token'}
        onBoardVideoRuntimeError={() => {}}
      />,
    )

    expect(markup).toContain('aria-label="Take control"')
    expect(markup).toContain('aria-description="MCP over WebRTC data channel · View only"')
    expect(markup).toContain('data-control-owner="none"')
  })

  test('renders current-browser active MCP ownership without a takeover affordance', () => {
    const markup = renderToStaticMarkup(
      <TxingPanel
        isBoardVideoExpanded={true}
        isDebugEnabled={false}
        isShadowConnected={true}
        isTakeControlPending={false}
        mcpTransport="webrtc-datachannel"
        onTakeControl={() => {}}
        onToggleDebug={() => {}}
        robotControl={{
          activeRequired: true,
          activeTtlMs: 5000,
          activeHeldByCaller: true,
          activeOwnerSessionId: 'session-b',
          activeExpiresAtMs: 10000,
          activeEpoch: 8,
          activeControl: {
            sessionId: 'session-b',
            actor: 'operator-b',
            transport: 'webrtc-datachannel',
            sinceMs: 5000,
            expiresAtMs: 10000,
            epoch: 8,
          },
        }}
        reportedRedcon={1}
        reportedBatteryMv={3960}
        reportedBoardLeftTrackSpeed={0}
        reportedBoardOnline={true}
        reportedBoardRightTrackSpeed={0}
        reportedMcuOnline={true}
        videoChannelName="unit-local-board-video"
        resolveIdToken={async () => 'token'}
        onBoardVideoRuntimeError={() => {}}
      />,
    )

    expect(markup).toContain('aria-label="MCP over WebRTC data channel · You have active control"')
    expect(markup).toContain('data-control-owner="current"')
    expect(markup).not.toContain('aria-label="Take control"')
  })

  test('renders an explicit active-control takeover button when another session owns control', () => {
    const markup = renderToStaticMarkup(
      <TxingPanel
        isBoardVideoExpanded={true}
        isDebugEnabled={false}
        isShadowConnected={true}
        isTakeControlPending={false}
        mcpTransport="webrtc-datachannel"
        onTakeControl={() => {}}
        onToggleDebug={() => {}}
        robotControl={{
          activeRequired: true,
          activeTtlMs: 5000,
          activeHeldByCaller: false,
          activeOwnerSessionId: 'session-a',
          activeExpiresAtMs: 10000,
          activeEpoch: 7,
          activeControl: {
            sessionId: 'session-a',
            actor: 'operator-a',
            transport: 'webrtc-datachannel',
            sinceMs: 5000,
            expiresAtMs: 10000,
            epoch: 7,
          },
        }}
        reportedRedcon={1}
        reportedBatteryMv={3960}
        reportedBoardLeftTrackSpeed={0}
        reportedBoardOnline={true}
        reportedBoardRightTrackSpeed={0}
        reportedMcuOnline={true}
        videoChannelName="unit-local-board-video"
        resolveIdToken={async () => 'token'}
        onBoardVideoRuntimeError={() => {}}
      />,
    )

    expect(markup).toContain('aria-label="Take over control"')
    expect(markup).toContain('aria-description="MCP over WebRTC data channel · Active control held by operator-a"')
    expect(markup).toContain('data-control-owner="other"')
  })
})
