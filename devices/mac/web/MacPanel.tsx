import VideoControlOverlay, { VideoOverlayRow } from '../../../office/src/VideoControlOverlay'
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
  const controlOverlay = <VideoControlOverlay link={{ protocol: 'MCP', transport: mcpTransport }} />
  const videoOverlay = (
    <VideoOverlayRow
      debug={shouldRenderBoardVideo ? { enabled: isDebugEnabled, toggle: onToggleDebug } : undefined}
      controls={controlOverlay}
      center={(
        <div className="status-video-overlay-lockup">
          <div className="status-name status-txing-name status-video-overlay-name" aria-hidden="true">
            MAC
          </div>
        </div>
      )}
      indicators={(
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
      )}
    />
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
