import { useEffect, useMemo, useRef, useState } from 'react'
import type { AuthUser } from '../../../web/src/auth'
import {
  describeRedcon,
  getTrackIndicatorPresentation,
  getTxingRedconToneClass,
} from './app-model'
import VideoPanel from '../../../web/src/VideoPanel'

type TxingPanelProps = {
  authUser: AuthUser | null
  canLoadShadow: boolean
  canUseBoardVideo: boolean
  isBoardVideoExpanded: boolean
  isDebugEnabled: boolean
  isSessionLogVisible: boolean
  isTxingSwitchDisabled: boolean
  isTxingSwitchPending: boolean
  lastShadowUpdateAtMs: number | null
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
  onLoadShadow: () => void
  onSignOff: () => void
  onToggleBoardVideo: () => void
  onToggleDebug: () => void
  onToggleSessionLog: () => void
  onTxingSwitchChange: (checked: boolean) => void
}

type BatteryCurvePoint = readonly [mv: number, percent: number]
type CameraGlyphProps = {
  crossed: boolean
}
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

const formatShadowUpdateTime = (updatedAtMs: number | null): string =>
  updatedAtMs === null
    ? '--:--:--'
    : new Date(updatedAtMs).toLocaleTimeString([], {
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
      })

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

function CameraGlyph({ crossed }: CameraGlyphProps) {
  return (
    <svg
      className="status-camera-glyph"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      <path d="M4.5 7.5h8.2l1.8-2.1h2.5a2.5 2.5 0 0 1 2.5 2.5v8.2a2.5 2.5 0 0 1-2.5 2.5H6.5A2.5 2.5 0 0 1 4 16.1V8a.5.5 0 0 1 .5-.5Z" />
      <path d="m14.8 10.4 4.7-2.2v7.5l-4.7-2.2" />
      {crossed ? <path d="M5 19 19 5" /> : null}
    </svg>
  )
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

function TxingPanel({
  authUser,
  canLoadShadow,
  canUseBoardVideo,
  isBoardVideoExpanded,
  isDebugEnabled,
  isSessionLogVisible,
  isTxingSwitchDisabled,
  isTxingSwitchPending,
  lastShadowUpdateAtMs,
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
  onLoadShadow,
  onSignOff,
  onToggleBoardVideo,
  onToggleDebug,
  onToggleSessionLog,
  onTxingSwitchChange,
}: TxingPanelProps) {
  const [isUserMenuOpen, setIsUserMenuOpen] = useState(false)
  const userMenuRef = useRef<HTMLDivElement | null>(null)

  const batteryPercent = useMemo(() => getBatteryPercent(reportedBatteryMv), [reportedBatteryMv])
  const batteryToneClass = getBatteryToneClass(batteryPercent)
  const boardWifiToneClass = getBoardWifiToneClass(reportedBoardOnline)
  const bleSignalToneClass = getBleSignalToneClass(reportedMcuOnline)
  const txingRedconLabel = describeRedcon(reportedRedcon)
  const userMenuIdentity = authUser?.email ?? authUser?.name ?? authUser?.sub ?? 'User'
  const userMenuInitial = userMenuIdentity.trim().charAt(0).toUpperCase() || 'U'
  const lastShadowUpdateLabel = formatShadowUpdateTime(lastShadowUpdateAtMs)
  const lastShadowUpdateTitle =
    lastShadowUpdateAtMs === null
      ? 'Last shadow update unavailable'
      : `Last shadow update ${new Date(lastShadowUpdateAtMs).toLocaleString()}`

  useEffect(() => {
    if (!isUserMenuOpen) {
      return
    }

    const handlePointerDown = (event: MouseEvent) => {
      if (!userMenuRef.current?.contains(event.target as Node)) {
        setIsUserMenuOpen(false)
      }
    }

    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setIsUserMenuOpen(false)
      }
    }

    document.addEventListener('mousedown', handlePointerDown)
    document.addEventListener('keydown', handleEscape)
    return () => {
      document.removeEventListener('mousedown', handlePointerDown)
      document.removeEventListener('keydown', handleEscape)
    }
  }, [isUserMenuOpen])

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
              <div className="user-menu" ref={userMenuRef}>
                <button
                  type="button"
                  className="user-menu-trigger"
                  aria-label="Open user menu"
                  aria-haspopup="menu"
                  aria-expanded={isUserMenuOpen}
                  onClick={() => {
                    setIsUserMenuOpen((currentValue) => !currentValue)
                  }}
                >
                  <span className="user-avatar" aria-hidden="true">
                    {userMenuInitial}
                  </span>
                </button>
                {isUserMenuOpen && (
                  <div className="user-menu-popover" role="menu" aria-label="User actions">
                    <div className="user-menu-header">
                      <span className="user-avatar user-avatar-large" aria-hidden="true">
                        {userMenuInitial}
                      </span>
                      <div className="user-menu-identity">
                        <p className="user-menu-name">{authUser?.name ?? 'Signed in'}</p>
                        <p className="user-menu-email">
                          {authUser?.email ?? authUser?.sub ?? 'Unknown user'}
                        </p>
                      </div>
                    </div>
                    <button
                      type="button"
                      className="user-menu-item"
                      role="menuitem"
                      disabled={!canLoadShadow}
                      onClick={() => {
                        onLoadShadow()
                        setIsUserMenuOpen(false)
                      }}
                    >
                      Load Shadow
                    </button>
                    <button
                      type="button"
                      className="user-menu-item"
                      role="menuitem"
                      onClick={() => {
                        onToggleDebug()
                        setIsUserMenuOpen(false)
                      }}
                    >
                      {isDebugEnabled ? 'Disable Debug' : 'Enable Debug'}
                    </button>
                    <button
                      type="button"
                      className="user-menu-item"
                      role="menuitem"
                      onClick={() => {
                        onToggleSessionLog()
                        setIsUserMenuOpen(false)
                      }}
                    >
                      {isSessionLogVisible ? 'Hide Session Log' : 'Show Session Log'}
                    </button>
                    <button
                      type="button"
                      className="user-menu-item user-menu-item-danger"
                      role="menuitem"
                      onClick={() => {
                        setIsUserMenuOpen(false)
                        onSignOff()
                      }}
                    >
                      Sign Off
                    </button>
                  </div>
                )}
              </div>
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
              <time
                className="status-last-shadow-update"
                dateTime={
                  lastShadowUpdateAtMs === null
                    ? undefined
                    : new Date(lastShadowUpdateAtMs).toISOString()
                }
                title={lastShadowUpdateTitle}
              >
                {lastShadowUpdateLabel}
              </time>
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
              <button
                type="button"
                className={`status-icon-button status-camera-button ${
                  !canUseBoardVideo
                    ? 'status-camera-button-idle'
                    : isBoardVideoExpanded
                      ? 'status-camera-button-live'
                      : 'status-camera-button-ready'
                }`}
                aria-label={
                  canUseBoardVideo
                    ? isBoardVideoExpanded
                      ? 'Hide board video'
                      : 'Show board video'
                    : 'Board video unavailable'
                }
                title={
                  canUseBoardVideo
                    ? isBoardVideoExpanded
                      ? 'Hide board video panel'
                      : 'Show board video panel'
                    : 'Board video is not ready'
                }
                onClick={onToggleBoardVideo}
                disabled={!canUseBoardVideo}
              >
                <CameraGlyph crossed={!canUseBoardVideo} />
              </button>
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
