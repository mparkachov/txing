import { useMemo } from 'react'
import {
  describeRedcon,
  getTrackIndicatorPresentation,
  getTxingRedconToneClass,
} from './app-model'
import VideoPanel from '../../../web/src/VideoPanel'

type TxingPanelProps = {
  canUseBoardVideo: boolean
  isBoardVideoExpanded: boolean
  isDebugEnabled: boolean
  isTxingSwitchDisabled: boolean
  isTxingSwitchPending: boolean
  reportedBoardLeftTrackSpeed: number | null
  reportedBoardOnline: boolean | null
  reportedBoardRightTrackSpeed: number | null
  reportedBatteryMv: number | null
  reportedMcuOnline: boolean | null
  reportedRedcon: number | null
  txingSwitchChecked: boolean
  videoChannelName: string
  resolveIdToken: () => Promise<string>
  onBoardVideoRuntimeError: (message: string) => void
  onToggleBoardVideo: () => void
  onTxingSwitchChange: (checked: boolean) => void
}

type BatteryCurvePoint = readonly [mv: number, percent: number]
type TrackGaugeProps = {
  side: 'Left' | 'Right'
  speed: number | null
}
type RedconLevel = 1 | 2 | 3 | 4

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
const leftRedconLevels: readonly RedconLevel[] = [4, 3]
const rightRedconLevels: readonly RedconLevel[] = [2, 1]
const getRedconDotClass = (level: RedconLevel, activeRedcon: number | null): string =>
  `status-redcon-dot ${
    activeRedcon === level
      ? `status-redcon-dot-active ${getTxingRedconToneClass(level)}`
      : 'status-redcon-dot-inactive'
  }`
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

const getBoardWifiToneClass = (boardWifiOnline: boolean | null): string => {
  if (boardWifiOnline === true) {
    return 'status-wifi-online'
  }
  if (boardWifiOnline === false) {
    return 'status-wifi-offline'
  }
  return 'status-wifi-unknown'
}

const getBleSignalToneClass = (bleStatusOnline: boolean | null): string =>
  bleStatusOnline === true ? 'status-signal-online' : 'status-signal-offline'

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

function TxingPanel({
  canUseBoardVideo,
  isBoardVideoExpanded,
  isDebugEnabled,
  isTxingSwitchDisabled,
  isTxingSwitchPending,
  reportedBoardLeftTrackSpeed,
  reportedBoardOnline,
  reportedBoardRightTrackSpeed,
  reportedBatteryMv,
  reportedMcuOnline,
  reportedRedcon,
  txingSwitchChecked,
  videoChannelName,
  resolveIdToken,
  onBoardVideoRuntimeError,
  onToggleBoardVideo,
  onTxingSwitchChange,
}: TxingPanelProps) {
  const batteryPercent = useMemo(() => getBatteryPercent(reportedBatteryMv), [reportedBatteryMv])
  const batteryToneClass = getBatteryToneClass(batteryPercent)
  const boardWifiToneClass = getBoardWifiToneClass(reportedBoardOnline)
  const bleSignalToneClass = getBleSignalToneClass(reportedMcuOnline)
  const txingRedconLabel = describeRedcon(reportedRedcon)

  return (
    <section className="status-hero status-hero-dashboard" aria-label="Bot status">
      <div className="shadow-diagram">
        <div
          className={`status-node status-node-txing ${
            isBoardVideoExpanded && canUseBoardVideo ? 'status-node-txing-expanded' : ''
          }`}
        >
          <div className="status-txing-header">
            <div className="status-txing-header-side status-txing-header-side-start">
              <label
                className={`status-switch ${isTxingSwitchPending ? 'status-switch-pending' : ''}`}
                aria-label="Wake or sleep bot"
              >
                <input
                  type="checkbox"
                  checked={txingSwitchChecked}
                  disabled={isTxingSwitchDisabled}
                  onChange={(event) => {
                    onTxingSwitchChange(event.target.checked)
                  }}
                />
                <span className="status-switch-track" aria-hidden="true">
                  <span className="status-switch-thumb" />
                </span>
              </label>
            </div>
            <div
              className="status-txing-title-group"
              role="group"
              aria-label={txingRedconLabel}
              title={txingRedconLabel}
            >
              <div className="status-redcon-cluster status-redcon-cluster-left" aria-hidden="true">
                <span
                  className={getRedconDotClass(leftRedconLevels[0], reportedRedcon)}
                  data-redcon-level={leftRedconLevels[0]}
                />
                <span className="status-redcon-connector" aria-hidden="true" />
                <span
                  className={getRedconDotClass(leftRedconLevels[1], reportedRedcon)}
                  data-redcon-level={leftRedconLevels[1]}
                />
              </div>
              <TrackGauge side="Left" speed={reportedBoardLeftTrackSpeed} />
              <div className="status-name status-txing-name" aria-hidden="true">
                BOT
              </div>
              <TrackGauge side="Right" speed={reportedBoardRightTrackSpeed} />
              <div className="status-redcon-cluster status-redcon-cluster-right" aria-hidden="true">
                <span
                  className={getRedconDotClass(rightRedconLevels[0], reportedRedcon)}
                  data-redcon-level={rightRedconLevels[0]}
                />
                <span className="status-redcon-connector" aria-hidden="true" />
                <span
                  className={getRedconDotClass(rightRedconLevels[1], reportedRedcon)}
                  data-redcon-level={rightRedconLevels[1]}
                />
              </div>
            </div>
            <div className="status-txing-header-side status-txing-header-side-end">
              <div className="status-connect-control">
                <button
                  type="button"
                  className={`status-connect-button ${
                    !canUseBoardVideo
                      ? 'status-connect-button-idle'
                      : isBoardVideoExpanded
                        ? 'status-connect-button-live'
                        : 'status-connect-button-ready'
                  }`}
                  aria-label={
                    canUseBoardVideo
                      ? isBoardVideoExpanded
                        ? 'Disconnect from board video'
                        : 'Connect to board video'
                      : 'Board connection unavailable'
                  }
                  title={
                    canUseBoardVideo
                      ? isBoardVideoExpanded
                        ? 'Disconnect from board video panel'
                        : 'Connect to board video panel'
                      : 'Board connection is unavailable'
                  }
                  onClick={onToggleBoardVideo}
                  disabled={!canUseBoardVideo}
                >
                  {isBoardVideoExpanded ? 'Disconnect' : 'Connect'}
                </button>
              </div>
              <div
                className={`status-signal ${bleSignalToneClass}`}
                role="img"
                aria-label={
                  reportedMcuOnline === true
                    ? 'BLE online'
                    : reportedMcuOnline === false
                      ? 'BLE offline'
                      : 'BLE status unavailable'
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
              <div
                className={`status-battery ${batteryToneClass}`}
                role="img"
                aria-label={
                  reportedBatteryMv === null || batteryPercent === null
                    ? 'Battery level unavailable'
                    : `Battery ${Math.round(batteryPercent)} percent at ${reportedBatteryMv} millivolts`
                }
                title={
                  reportedBatteryMv === null || batteryPercent === null
                    ? 'Battery unavailable'
                    : `${reportedBatteryMv} mV`
                }
              >
                <span className="status-battery-shell" aria-hidden="true">
                  <span
                    className="status-battery-fill"
                    style={{ width: `${Math.max(0, Math.min(100, batteryPercent ?? 0))}%` }}
                  />
                </span>
                <span className="status-battery-cap" aria-hidden="true" />
              </div>
            </div>
          </div>
          {isBoardVideoExpanded && canUseBoardVideo ? (
            <VideoPanel
              channelName={videoChannelName}
              debugEnabled={isDebugEnabled}
              onRuntimeError={onBoardVideoRuntimeError}
              resolveIdToken={resolveIdToken}
            />
          ) : null}
        </div>
      </div>
    </section>
  )
}

export default TxingPanel
