import { describe, expect, test } from 'bun:test'
import { renderToStaticMarkup } from 'react-dom/server'
import TxingPanel from '../../devices/unit/web/TxingPanel'

describe('txing panel', () => {
  test('renders device-specific gauges and connectivity indicators without sparkplug controls', () => {
    const markup = renderToStaticMarkup(
      <TxingPanel
        isBoardVideoExpanded={true}
        isDebugEnabled={false}
        mcpTransport="webrtc-datachannel"
        onToggleDebug={() => {}}
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
    expect(markup).toContain('status-video-debug-button')
    expect(markup).toContain('status-mcp-transport-webrtc')
    expect(markup).toContain('data-mcp-transport="webrtc-datachannel"')
    expect(markup).toContain('aria-label="MCP over WebRTC data channel"')
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
    expect(markup).not.toContain('status-redcon-dot')
    expect(markup).not.toContain('status-switch-track')
  })
})
