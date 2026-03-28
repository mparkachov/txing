import { useEffect, useMemo, useRef, useState } from 'react'
import type { AuthUser } from './auth'
import VideoPanel from './VideoPanel'

type TxingPanelProps = {
  authUser: AuthUser | null
  canLoadShadow: boolean
  canUseBoardVideo: boolean
  isBoardVideoExpanded: boolean
  isDebugEnabled: boolean
  isTxingSwitchDisabled: boolean
  isTxingSwitchPending: boolean
  lastShadowUpdateAtMs: number | null
  reportedBoardOnline: boolean | null
  reportedBoardPower: boolean | null
  reportedMcuBatteryMv: number | null
  reportedMcuBleOnline: boolean | null
  reportedMcuPower: boolean | null
  reportedRedcon: number | null
  txingSwitchChecked: boolean
  videoChannelName: string | null
  resolveIdToken: () => Promise<string>
  onLoadShadow: () => void
  onSignOff: () => void
  onToggleBoardVideo: () => void
  onToggleDebug: () => void
  onTxingSwitchChange: (checked: boolean) => void
}

type BatteryCurvePoint = readonly [mv: number, percent: number]
type CameraGlyphProps = {
  crossed: boolean
}

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

const getTxingPowerToneClass = (mcuPower: boolean | null, boardPower: boolean | null): string => {
  if (mcuPower === true && boardPower === true) {
    return 'status-txing-power-full'
  }
  if (mcuPower === false && boardPower === false) {
    return 'status-txing-power-sleep'
  }
  if (mcuPower === true || boardPower === true) {
    return 'status-txing-power-partial'
  }
  return 'status-txing-power-sleep'
}

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

function TxingPanel({
  authUser,
  canLoadShadow,
  canUseBoardVideo,
  isBoardVideoExpanded,
  isDebugEnabled,
  isTxingSwitchDisabled,
  isTxingSwitchPending,
  lastShadowUpdateAtMs,
  reportedBoardOnline,
  reportedBoardPower,
  reportedMcuBatteryMv,
  reportedMcuBleOnline,
  reportedMcuPower,
  reportedRedcon,
  txingSwitchChecked,
  videoChannelName,
  resolveIdToken,
  onLoadShadow,
  onSignOff,
  onToggleBoardVideo,
  onToggleDebug,
  onTxingSwitchChange,
}: TxingPanelProps) {
  const [isUserMenuOpen, setIsUserMenuOpen] = useState(false)
  const userMenuRef = useRef<HTMLDivElement | null>(null)

  const batteryPercent = useMemo(() => getBatteryPercent(reportedMcuBatteryMv), [reportedMcuBatteryMv])
  const batteryToneClass = getBatteryToneClass(batteryPercent)
  const boardWifiToneClass = getBoardWifiToneClass(reportedBoardOnline)
  const bleSignalToneClass = getBleSignalToneClass(reportedMcuBleOnline)
  const txingPowerToneClass = getTxingPowerToneClass(reportedMcuPower, reportedBoardPower)
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
    <section className="status-hero status-hero-dashboard" aria-label="Txing status">
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
                aria-label="Wake or sleep txing"
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
            <div className={`status-name status-txing-name ${txingPowerToneClass}`}>
              {`TXING - ${reportedRedcon ?? '--'}/4`}
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
                  reportedMcuBleOnline === true
                    ? 'BLE online'
                    : reportedMcuBleOnline === false
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
                  reportedMcuBatteryMv === null || batteryPercent === null
                    ? 'Battery level unavailable'
                    : `Battery ${Math.round(batteryPercent)} percent at ${reportedMcuBatteryMv} millivolts`
                }
                title={
                  reportedMcuBatteryMv === null || batteryPercent === null
                    ? 'Battery unavailable'
                    : `${reportedMcuBatteryMv} mV`
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
              resolveIdToken={resolveIdToken}
            />
          ) : null}
        </div>
      </div>
    </section>
  )
}

export default TxingPanel
