import VideoPanel from '../../../office/src/VideoPanel'
import type { McpTransportKind } from '../../../office/src/mcp-descriptor'

type MacPanelProps = {
  isBoardVideoExpanded: boolean
  isDebugEnabled: boolean
  mcpTransport: McpTransportKind | null
  onBoardVideoRuntimeError: (message: string) => void
  onToggleDebug: () => void
  reportedBoardOnline: boolean | null
  reportedRedcon: number | null
  resolveIdToken: () => Promise<string>
  videoChannelName: string
}

const getBoardWifiToneClass = (boardWifiOnline: boolean | null): string => {
  if (boardWifiOnline === true) {
    return 'status-wifi-online'
  }
  if (boardWifiOnline === false) {
    return 'status-wifi-offline'
  }
  return 'status-wifi-unknown'
}

function DebugGlyph() {
  return (
    <svg
      className="status-video-debug-glyph"
      viewBox="0 0 24 24"
      aria-hidden="true"
      focusable="false"
    >
      <path
        d="M9 8.5V7a3 3 0 0 1 6 0v1.5M8 10h8m-7 3h6m-5 3h4M7 8l-2-2m14 2 2-2M8 19l-2 2m10-2 2 2M8.5 8h7a1.5 1.5 0 0 1 1.5 1.5v5a5 5 0 0 1-10 0v-5A1.5 1.5 0 0 1 8.5 8Z"
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="1.8"
      />
    </svg>
  )
}

function McpTransportGlyph({ transport }: { transport: McpTransportKind | null }) {
  const label =
    transport === 'webrtc-datachannel'
      ? 'MCP over WebRTC data channel'
      : transport === 'mqtt-jsonrpc'
        ? 'MCP over MQTT JSON-RPC'
        : 'MCP transport pending'
  const toneClass =
    transport === 'webrtc-datachannel'
      ? 'status-mcp-transport-webrtc'
      : transport === 'mqtt-jsonrpc'
        ? 'status-mcp-transport-mqtt'
        : 'status-mcp-transport-pending'

  return (
    <span
      className={`status-mcp-transport ${toneClass}`}
      role="img"
      aria-label={label}
      title={label}
      data-mcp-transport={transport ?? 'pending'}
    >
      <svg
        className="status-mcp-transport-glyph"
        viewBox="0 0 24 24"
        aria-hidden="true"
        focusable="false"
      >
        {transport === 'mqtt-jsonrpc' ? (
          <>
            <path
              d="M7 9.2a7.5 7.5 0 0 1 10 0M9.7 12a3.8 3.8 0 0 1 4.6 0"
              fill="none"
              stroke="currentColor"
              strokeLinecap="round"
              strokeWidth="2"
            />
            <path d="M12 16.4h.01" fill="none" stroke="currentColor" strokeLinecap="round" strokeWidth="3" />
          </>
        ) : (
          <>
            <path
              d="M8.2 8.4h7.6M8.2 15.6h7.6"
              fill="none"
              stroke="currentColor"
              strokeLinecap="round"
              strokeWidth="2"
            />
            <circle cx="6" cy="8.4" r="1.8" fill="currentColor" />
            <circle cx="18" cy="8.4" r="1.8" fill="currentColor" />
            <circle cx="6" cy="15.6" r="1.8" fill="currentColor" />
            <circle cx="18" cy="15.6" r="1.8" fill="currentColor" />
          </>
        )}
      </svg>
    </span>
  )
}

function MacPanel({
  isBoardVideoExpanded,
  isDebugEnabled,
  mcpTransport,
  onBoardVideoRuntimeError,
  onToggleDebug,
  reportedBoardOnline,
  reportedRedcon,
  resolveIdToken,
  videoChannelName,
}: MacPanelProps) {
  const boardWifiToneClass = getBoardWifiToneClass(reportedBoardOnline)
  const shouldRenderBoardVideo = isBoardVideoExpanded && reportedRedcon === 1
  const videoOverlay = (
    <div className="status-video-overlay-bar">
      <div className="status-video-overlay-side status-video-overlay-side-start">
        {shouldRenderBoardVideo ? (
          <button
            type="button"
            className={`status-video-debug-button ${
              isDebugEnabled
                ? 'status-video-debug-button-active'
                : 'status-video-debug-button-idle'
            }`}
            aria-label={isDebugEnabled ? 'Disable Debug' : 'Enable Debug'}
            aria-pressed={isDebugEnabled}
            title={isDebugEnabled ? 'Disable Debug' : 'Enable Debug'}
            onClick={onToggleDebug}
          >
            <DebugGlyph />
          </button>
        ) : null}
        <McpTransportGlyph transport={mcpTransport} />
      </div>
      <div className="status-video-overlay-lockup">
        <div className="status-name status-txing-name status-video-overlay-name" aria-hidden="true">
          MAC
        </div>
      </div>
      <div className="status-video-overlay-side status-video-overlay-side-end">
        <div className="status-video-overlay-metrics" aria-label="Mac connectivity indicators">
          <div
            className={`status-wifi ${boardWifiToneClass}`}
            role="img"
            aria-label={
              reportedBoardOnline === true
                ? 'Mac network online'
                : reportedBoardOnline === false
                  ? 'Mac network offline'
                  : 'Mac network status unavailable'
            }
          >
            <span className="status-wifi-arc status-wifi-arc-large" aria-hidden="true" />
            <span className="status-wifi-arc status-wifi-arc-medium" aria-hidden="true" />
            <span className="status-wifi-arc status-wifi-arc-small" aria-hidden="true" />
            <span className="status-wifi-dot" aria-hidden="true" />
          </div>
        </div>
      </div>
    </div>
  )

  return (
    <section className="status-hero status-hero-dashboard" aria-label="Mac status">
      <div className="shadow-diagram">
        <div className={`status-node status-node-txing ${shouldRenderBoardVideo ? 'status-node-txing-expanded' : ''}`}>
          {shouldRenderBoardVideo ? (
            <VideoPanel
              channelName={videoChannelName}
              debugEnabled={isDebugEnabled}
              onRuntimeError={onBoardVideoRuntimeError}
              overlay={videoOverlay}
              resolveIdToken={resolveIdToken}
            />
          ) : (
            <div
              className="status-video-offline-surface"
              aria-label="Mac device status"
              data-drive-mode={mcpTransport ?? 'pending'}
            >
              {videoOverlay}
            </div>
          )}
        </div>
      </div>
    </section>
  )
}

export default MacPanel
