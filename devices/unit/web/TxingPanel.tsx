import { getTrackIndicatorPresentation } from './app-model'
import VideoControlOverlay, { VideoOverlayRow } from '../../../office/src/VideoControlOverlay'
import VideoPanel from '../../../office/src/VideoPanel'
import type { McpTransportKind } from '../../../office/src/mcp-descriptor'
import type { RobotControlState } from '../../../office/src/shadow-api'

type TxingPanelProps = {
  isBoardVideoExpanded: boolean
  isDebugEnabled: boolean
  isShadowConnected: boolean
  isTakeControlPending: boolean
  mcpTransport: McpTransportKind | null
  onTakeControl: () => void
  reportedBatteryMv: number | null
  reportedBoardLeftTrackSpeed: number | null
  reportedBoardOnline: boolean | null
  reportedBoardRightTrackSpeed: number | null
  reportedRedcon: number | null
  reportedMcuOnline: boolean | null
  robotControl: RobotControlState | null
  onToggleDebug: () => void
  videoChannelName: string
  resolveIdToken: () => Promise<string>
  onBoardVideoRuntimeError: (message: string) => void
  watchTransport?: 'BLE' | 'Thread'
  deviceLabel?: string
}

type TrackGaugeProps = {
  side: 'Left' | 'Right'
  speed: number | null
}
type ActiveControlOwnership = 'unknown' | 'none' | 'current' | 'other'
type BatteryCurvePoint = readonly [mv: number, percent: number]

const batterySocCurve: readonly BatteryCurvePoint[] = [
  [3300, 0],
  [3600, 10],
  [3700, 20],
  [3800, 40],
  [3900, 60],
  [4000, 80],
  [4100, 92],
  [4200, 100],
]

const getTrackGaugeAngle = (speed: number | null): number =>
  speed === null ? 0 : Math.max(-78, Math.min(78, speed * 0.78))
const formatTrackGaugeValue = (speed: number | null): string => {
  if (speed === null) {
    return '--'
  }
  if (speed === 0) {
    return '0'
  }
  return `${speed > 0 ? '+' : ''}${speed}`
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

const getWatchSignalToneClass = (watchStatusOnline: boolean | null): string =>
  watchStatusOnline === true ? 'status-signal-online' : 'status-signal-offline'

const getBatteryPercent = (batteryMv: number | null): number | null => {
  if (batteryMv === null || Number.isNaN(batteryMv)) {
    return null
  }

  const firstPoint = batterySocCurve[0]
  const lastPoint = batterySocCurve[batterySocCurve.length - 1]
  if (batteryMv <= firstPoint[0]) {
    return firstPoint[1]
  }
  if (batteryMv >= lastPoint[0]) {
    return lastPoint[1]
  }

  for (let index = 1; index < batterySocCurve.length; index += 1) {
    const previousPoint = batterySocCurve[index - 1]
    const nextPoint = batterySocCurve[index]
    if (batteryMv > nextPoint[0]) {
      continue
    }

    const pointSpan = nextPoint[0] - previousPoint[0]
    const percentSpan = nextPoint[1] - previousPoint[1]
    const mvOffset = batteryMv - previousPoint[0]
    return previousPoint[1] + (mvOffset / pointSpan) * percentSpan
  }

  return null
}

const getBatteryToneClass = (batteryPercent: number | null): string => {
  if (batteryPercent === null) {
    return 'status-battery-unknown'
  }
  if (batteryPercent >= 55) {
    return 'status-battery-good'
  }
  if (batteryPercent >= 20) {
    return 'status-battery-warn'
  }
  return 'status-battery-low'
}

function TrackGauge({ side, speed }: TrackGaugeProps) {
  const presentation = getTrackIndicatorPresentation(speed, side)
  const angle = getTrackGaugeAngle(speed)
  const valueLabel = formatTrackGaugeValue(speed)

  return (
    <div
      className="status-track-gauge"
      role="img"
      aria-label={presentation.ariaLabel}
      title={`${side} track ${valueLabel === '--' ? 'unavailable' : `${valueLabel}%`}`}
      data-track-side={side.toLowerCase()}
      data-track-speed={speed === null ? 'null' : String(speed)}
    >
      <span className="status-track-gauge-arc" aria-hidden="true" />
      <span className="status-track-gauge-mark status-track-gauge-mark-minus" aria-hidden="true">
        -
      </span>
      <span className="status-track-gauge-mark status-track-gauge-mark-plus" aria-hidden="true">
        +
      </span>
      <span className="status-track-gauge-zero" aria-hidden="true" />
      <span
        className={`status-track-gauge-needle ${presentation.toneClass}`}
        aria-hidden="true"
        style={{ transform: `translateX(-50%) rotate(${angle}deg)` }}
      />
      <span className="status-track-gauge-pivot" aria-hidden="true" />
      <span className="status-track-gauge-value" aria-hidden="true">
        {valueLabel}
      </span>
    </div>
  )
}

function BatteryMetric({ batteryMv }: { batteryMv: number | null }) {
  const batteryPercent = getBatteryPercent(batteryMv)
  const batteryToneClass = getBatteryToneClass(batteryPercent)
  const title =
    batteryMv === null || batteryPercent === null
      ? 'Battery unavailable'
      : `Battery ${Math.round(batteryPercent)} percent at ${batteryMv} millivolts`

  return (
    <div className="txing-panel-battery" role="img" aria-label={title} title={title}>
      <div className={`status-battery ${batteryToneClass}`}>
        <span className="status-battery-shell" aria-hidden="true">
          <span
            className="status-battery-fill"
            style={{ width: `${Math.max(0, Math.min(100, batteryPercent ?? 0))}%` }}
          />
        </span>
        <span className="status-battery-cap" aria-hidden="true" />
      </div>
    </div>
  )
}

const getActiveControlOwnership = (
  robotControl: RobotControlState | null,
): ActiveControlOwnership => {
  if (!robotControl) {
    return 'unknown'
  }
  if (robotControl.activeOwnerSessionId === null) {
    return 'none'
  }
  return robotControl.activeHeldByCaller ? 'current' : 'other'
}

function TxingPanel({
  isBoardVideoExpanded,
  isDebugEnabled,
  isShadowConnected,
  isTakeControlPending,
  mcpTransport,
  onTakeControl,
  reportedBatteryMv,
  reportedBoardLeftTrackSpeed,
  reportedBoardOnline,
  reportedBoardRightTrackSpeed,
  reportedRedcon,
  reportedMcuOnline,
  robotControl,
  onToggleDebug,
  videoChannelName,
  resolveIdToken,
  onBoardVideoRuntimeError,
  watchTransport = 'BLE',
  deviceLabel = 'BOT',
}: TxingPanelProps) {
  const boardWifiToneClass = getBoardWifiToneClass(reportedBoardOnline)
  const watchSignalToneClass = getWatchSignalToneClass(reportedMcuOnline)
  const shouldRenderBoardVideo = isBoardVideoExpanded && reportedRedcon === 1
  const activeControlOwnership = getActiveControlOwnership(robotControl)
  const activeControlActor = robotControl?.activeControl?.actor
  const shouldRenderTakeControlButton =
    activeControlOwnership === 'none' || activeControlOwnership === 'other'
  const activeControlLabel = activeControlOwnership === 'current' ? 'You have active control'
    : activeControlOwnership === 'other' ? `Active control held by ${activeControlActor ?? 'another session'}`
      : activeControlOwnership === 'none' ? 'View only' : 'MCP active-control status pending'
  const controlOverlay = (
    <VideoControlOverlay link={{ protocol: 'MCP', transport: mcpTransport }}
      authority={{
        state: activeControlOwnership,
        label: activeControlLabel,
        action: shouldRenderTakeControlButton ? {
          label: activeControlOwnership === 'other' ? 'Take over control' : 'Take control',
          disabled: !isShadowConnected || isTakeControlPending,
          run: onTakeControl,
        } : undefined,
      }} />
  )
  const videoOverlay = (
    <VideoOverlayRow
      debug={shouldRenderBoardVideo ? { enabled: isDebugEnabled, toggle: onToggleDebug } : undefined}
      controls={controlOverlay}
      center={(
        <div className="status-video-overlay-lockup">
          <div className="status-txing-title-group" role="group" aria-label={`${deviceLabel} drive indicators`}>
            <TrackGauge side="Left" speed={reportedBoardLeftTrackSpeed} />
            <div className="status-name status-txing-name status-video-overlay-name" aria-hidden="true">
              {deviceLabel}
            </div>
            <TrackGauge side="Right" speed={reportedBoardRightTrackSpeed} />
          </div>
        </div>
      )}
      indicators={(
        <div className="status-video-overlay-side status-video-overlay-side-end">
          <div className="status-video-overlay-metrics" aria-label={`${deviceLabel} connectivity indicators`}>
            <div
              className={`status-signal ${watchSignalToneClass}`}
              role="img"
              aria-label={
                reportedMcuOnline === true
                  ? `${watchTransport} online`
                  : reportedMcuOnline === false
                    ? `${watchTransport} offline`
                    : `${watchTransport} status unavailable`
              }
            >
              <span className="status-signal-bar status-signal-bar-1" aria-hidden="true" />
              <span className="status-signal-bar status-signal-bar-2" aria-hidden="true" />
              <span className="status-signal-bar status-signal-bar-3" aria-hidden="true" />
              <span className="status-signal-bar status-signal-bar-4" aria-hidden="true" />
            </div>
            <div
              className={`status-wifi ${boardWifiToneClass}`}
              role="img"
              aria-label={
                reportedBoardOnline === true
                  ? 'Board Wi-Fi online'
                  : reportedBoardOnline === false
                    ? 'Board Wi-Fi offline'
                    : 'Board Wi-Fi status unavailable'
              }
            >
              <span className="status-wifi-arc status-wifi-arc-large" aria-hidden="true" />
              <span className="status-wifi-arc status-wifi-arc-medium" aria-hidden="true" />
              <span className="status-wifi-arc status-wifi-arc-small" aria-hidden="true" />
              <span className="status-wifi-dot" aria-hidden="true" />
            </div>
            <BatteryMetric batteryMv={reportedBatteryMv} />
          </div>
        </div>
      )}
    />
  )

  return (
    <section className="status-hero status-hero-dashboard" aria-label="Bot status">
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
              aria-label="Bot drive status"
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

export default TxingPanel
