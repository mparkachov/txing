import { useEffect, useEffectEvent, useMemo, useRef, useState } from 'react'
import {
  beginSignIn,
  clearAuthState,
  getAuthUser,
  refreshTokensIfNeeded,
  signOut,
  type AuthUser,
} from './auth'
import {
  extractReportedBoardPower,
  extractReportedBoardVideo,
  extractReportedBoardWifiOnline,
  extractReportedMcuBatteryMv,
  extractReportedMcuBleOnline,
  extractReportedMcuOnline,
  extractReportedMcuPower,
} from './app-model'
import { appConfig } from './config'
import { createShadowSession, type ShadowConnectionState, type ShadowSession } from './shadow-api'
import VideoPage from './VideoPage'

type SessionStatus = 'loading' | 'authenticating' | 'signed_out' | 'signed_in'
type AppProps = {
  initialAuthError?: string
}
type TxingSwitchTarget = 'on' | 'off' | null
type BatteryCurvePoint = readonly [mv: number, percent: number]
type ShadowSnapshotView = {
  json: string
  updatedAtMs: number
}
type CameraGlyphProps = {
  crossed: boolean
}

const formatJson = (value: unknown): string => JSON.stringify(value, null, 2)
const boardOfflineTimeoutMs = 45_000
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

const createShadowSnapshotView = (shadow: unknown): ShadowSnapshotView => ({
  json: formatJson(shadow),
  updatedAtMs: Date.now(),
})

const formatShadowUpdateTime = (updatedAtMs: number | null): string =>
  updatedAtMs === null
    ? '--:--:--'
    : new Date(updatedAtMs).toLocaleTimeString([], {
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
      })

const getPowerNodeClass = (power: boolean | null): string => {
  if (power === true) {
    return 'status-node-awake'
  }
  if (power === false) {
    return 'status-node-asleep'
  }
  return 'status-node-unknown'
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

function App({ initialAuthError = '' }: AppProps) {
  const [status, setStatus] = useState<SessionStatus>('loading')
  const [authUser, setAuthUser] = useState<AuthUser | null>(null)
  const [shadowJson, setShadowJson] = useState<string>('{}')
  const [lastShadowUpdateAtMs, setLastShadowUpdateAtMs] = useState<number | null>(null)
  const [isLoadingShadow, setIsLoadingShadow] = useState(false)
  const [isUpdatingShadow, setIsUpdatingShadow] = useState(false)
  const [isDebugEnabled, setIsDebugEnabled] = useState(false)
  const [isBoardVideoExpanded, setIsBoardVideoExpanded] = useState(false)
  const [isUserMenuOpen, setIsUserMenuOpen] = useState(false)
  const [txingSwitchTarget, setTxingSwitchTarget] = useState<TxingSwitchTarget>(null)
  const [feedback, setFeedback] = useState<string>('')
  const [error, setError] = useState<string>(initialAuthError)
  const [shadowConnectionState, setShadowConnectionState] =
    useState<ShadowConnectionState>('idle')
  const shadowSessionRef = useRef<ShadowSession | null>(null)
  const userMenuRef = useRef<HTMLDivElement | null>(null)

  const hasConfigErrors = appConfig.errors.length > 0

  const adminEmailMismatch = useMemo(() => {
    if (!appConfig.adminEmail || !authUser?.email) {
      return false
    }
    return authUser.email.toLowerCase() !== appConfig.adminEmail
  }, [authUser?.email])

  const shadowDocument = useMemo<unknown>(() => {
    try {
      return JSON.parse(shadowJson)
    } catch {
      return null
    }
  }, [shadowJson])

  const reportedMcuPower = useMemo(
    () => extractReportedMcuPower(shadowDocument),
    [shadowDocument],
  )
  const reportedMcuOnline = useMemo(
    () => extractReportedMcuOnline(shadowDocument),
    [shadowDocument],
  )
  const reportedMcuBleOnline = useMemo(
    () => extractReportedMcuBleOnline(shadowDocument),
    [shadowDocument],
  )
  const reportedMcuBatteryMv = useMemo(
    () => extractReportedMcuBatteryMv(shadowDocument),
    [shadowDocument],
  )
  const reportedBoardPower = useMemo(
    () => extractReportedBoardPower(shadowDocument),
    [shadowDocument],
  )
  const reportedBoardOnline = useMemo(
    () => extractReportedBoardWifiOnline(shadowDocument),
    [shadowDocument],
  )
  const reportedBoardVideo = useMemo(
    () => extractReportedBoardVideo(shadowDocument),
    [shadowDocument],
  )

  const boardOnline = reportedBoardOnline === true
  const batteryPercent = useMemo(() => getBatteryPercent(reportedMcuBatteryMv), [reportedMcuBatteryMv])
  const batteryToneClass = getBatteryToneClass(batteryPercent)
  const boardWifiToneClass = getBoardWifiToneClass(reportedBoardOnline)
  const bleSignalToneClass = getBleSignalToneClass(reportedMcuBleOnline)
  const txingPowerToneClass = getTxingPowerToneClass(reportedMcuPower, reportedBoardPower)
  const canWake = reportedMcuPower === false && reportedMcuOnline === true
  const canSleep = reportedMcuPower === true || reportedBoardPower === true || reportedBoardOnline === true
  const isShadowConnected = shadowConnectionState === 'connected'
  const txingSwitchChecked =
    txingSwitchTarget === 'on' ? true : txingSwitchTarget === 'off' ? false : boardOnline
  const isTxingSwitchPending = txingSwitchTarget !== null
  const canToggleTxingSwitch = (txingSwitchChecked ? canSleep : canWake) && isShadowConnected
  const userMenuIdentity = authUser?.email ?? authUser?.name ?? authUser?.sub ?? 'User'
  const userMenuInitial = userMenuIdentity.trim().charAt(0).toUpperCase() || 'U'
  const lastShadowUpdateLabel = formatShadowUpdateTime(lastShadowUpdateAtMs)
  const lastShadowUpdateTitle =
    lastShadowUpdateAtMs === null
      ? 'Last shadow update unavailable'
      : `Last shadow update ${new Date(lastShadowUpdateAtMs).toLocaleString()}`
  const boardVideoReady =
    reportedBoardVideo.transport === 'aws-webrtc' &&
    reportedBoardVideo.ready &&
    reportedBoardVideo.status === 'ready' &&
    reportedBoardVideo.channelName !== null
  const boardVideoReachable =
    txingSwitchTarget !== 'off' && boardOnline && reportedBoardPower !== false
  const canUseBoardVideo = boardVideoReachable && boardVideoReady

  const applyShadowSnapshot = useEffectEvent((shadow: unknown, feedbackMessage?: string): void => {
    const snapshotView = createShadowSnapshotView(shadow)
    setShadowJson(snapshotView.json)
    setLastShadowUpdateAtMs(snapshotView.updatedAtMs)
    if (feedbackMessage) {
      setFeedback(feedbackMessage)
    }
  })

  const resolveSessionIdToken = useEffectEvent(async (): Promise<string> => {
    const refreshedTokens = await refreshTokensIfNeeded()
    if (!refreshedTokens) {
      clearAuthState()
      setAuthUser(null)
      setStatus('signed_out')
      throw new Error('Session expired. Sign in again.')
    }

    setAuthUser(getAuthUser(refreshedTokens))
    return refreshedTokens.idToken
  })

  const getShadowSession = (): ShadowSession => {
    const shadowSession = shadowSessionRef.current
    if (!shadowSession || !isShadowConnected) {
      throw new Error('Shadow connection is not ready')
    }
    return shadowSession
  }

  useEffect(() => {
    if (hasConfigErrors) {
      setStatus('signed_out')
      return
    }

    const hydrateSession = async () => {
      setFeedback('')
      if (!initialAuthError) {
        setError('')
      }

      try {
        const restoredTokens = await refreshTokensIfNeeded()
        if (!restoredTokens) {
          setStatus('signed_out')
          return
        }

        setAuthUser(getAuthUser(restoredTokens))
        setError('')
        setStatus('signed_in')
      } catch (caughtError) {
        clearAuthState()
        setStatus('signed_out')
        setError(caughtError instanceof Error ? caughtError.message : 'Authentication failed')
      }
    }

    void hydrateSession()
  }, [hasConfigErrors, initialAuthError])

  useEffect(() => {
    if (status !== 'signed_in') {
      return
    }
    if (!adminEmailMismatch) {
      return
    }

    clearAuthState()
    setStatus('signed_out')
    setError(`Signed-in user is not allowed. Expected: ${appConfig.adminEmail}`)
  }, [adminEmailMismatch, status])

  useEffect(() => {
    if (status !== 'signed_in' || adminEmailMismatch) {
      shadowSessionRef.current?.close()
      shadowSessionRef.current = null
      setShadowConnectionState('idle')
      setIsLoadingShadow(false)
      return
    }

    let cancelled = false
    const shadowSession = createShadowSession({
      thingName: appConfig.thingName,
      iotDataEndpoint: appConfig.iotDataEndpoint,
      awsRegion: appConfig.awsRegion,
      resolveIdToken: resolveSessionIdToken,
      onShadowDocument: (shadow) => {
        if (cancelled) {
          return
        }
        applyShadowSnapshot(shadow)
        setIsLoadingShadow(false)
        setError('')
      },
      onConnectionStateChange: (nextState) => {
        if (!cancelled) {
          setShadowConnectionState(nextState)
        }
      },
      onError: (message) => {
        if (!cancelled) {
          setError(message)
        }
      },
    })

    shadowSessionRef.current = shadowSession
    setIsLoadingShadow(true)
    setShadowConnectionState('connecting')
    setError('')
    setFeedback('')

    void shadowSession.start().catch((caughtError) => {
      if (cancelled) {
        return
      }
      setIsLoadingShadow(false)
      setError(
        caughtError instanceof Error ? caughtError.message : 'Unable to open Thing Shadow session',
      )
    })

    return () => {
      cancelled = true
      if (shadowSessionRef.current === shadowSession) {
        shadowSessionRef.current = null
      }
      shadowSession.close()
    }
  }, [adminEmailMismatch, status])

  useEffect(() => {
    if (txingSwitchTarget === 'on' && boardOnline) {
      setTxingSwitchTarget(null)
      return
    }
    if (txingSwitchTarget === 'off' && reportedBoardOnline === false) {
      setTxingSwitchTarget(null)
    }
  }, [boardOnline, reportedBoardOnline, txingSwitchTarget])

  useEffect(() => {
    if (!canUseBoardVideo && isBoardVideoExpanded) {
      setIsBoardVideoExpanded(false)
    }
  }, [canUseBoardVideo, isBoardVideoExpanded])

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

  const loadShadow = async (): Promise<void> => {
    setIsLoadingShadow(true)
    setError('')
    setFeedback('')

    try {
      const shadowSession = getShadowSession()
      const shadowResponse = await shadowSession.requestSnapshot()
      applyShadowSnapshot(shadowResponse)
    } catch (caughtError) {
      setError(caughtError instanceof Error ? caughtError.message : 'Unable to load shadow')
    } finally {
      setIsLoadingShadow(false)
    }
  }

  const updateDesiredPower = async (power: boolean): Promise<boolean> => {
    setIsUpdatingShadow(true)
    setError('')
    setFeedback('')

    try {
      const shadowSession = getShadowSession()
      const shadowResponse = await shadowSession.updateShadow({
        state: {
          desired: {
            mcu: {
              power,
            },
          },
        },
      })
      applyShadowSnapshot(
        shadowResponse,
        `desired.mcu.power -> ${power} at ${new Date().toLocaleTimeString()}`,
      )
      return true
    } catch (caughtError) {
      setError(caughtError instanceof Error ? caughtError.message : 'Unable to update desired power')
      return false
    } finally {
      setIsUpdatingShadow(false)
    }
  }

  const requestSleep = async (): Promise<boolean> => {
    setIsUpdatingShadow(true)
    setError('')
    setFeedback('')

    try {
      const shadowSession = getShadowSession()
      await shadowSession.updateShadow({
        state: {
          desired: {
            board: {
              power: false,
            },
          },
        },
      })

      setFeedback('Waiting for reported.board.power=false...')

      await shadowSession.waitForSnapshot(
        (shadow) => extractReportedBoardPower(shadow) === false,
        boardOfflineTimeoutMs,
      )

      const boardPowerClearedShadow = await shadowSession.updateShadow({
        state: {
          desired: {
            board: {
              power: null,
            },
          },
        },
      })
      applyShadowSnapshot(boardPowerClearedShadow)

      const mcuPowerUpdatedShadow = await shadowSession.updateShadow({
        state: {
          desired: {
            mcu: {
              power: false,
            },
          },
        },
      })
      applyShadowSnapshot(
        mcuPowerUpdatedShadow,
        `Sleep requested at ${new Date().toLocaleTimeString()}`,
      )
      return true
    } catch (caughtError) {
      setError(caughtError instanceof Error ? caughtError.message : 'Unable to request sleep')
      return false
    } finally {
      setIsUpdatingShadow(false)
    }
  }

  const handleTxingSwitchChange = async (checked: boolean): Promise<void> => {
    if (isTxingSwitchPending) {
      return
    }

    if (checked) {
      if (!canWake) {
        return
      }
      setTxingSwitchTarget('on')
      const woke = await updateDesiredPower(true)
      if (!woke) {
        setTxingSwitchTarget(null)
      }
      return
    }

    if (!canSleep) {
      return
    }

    setTxingSwitchTarget('off')
    const slept = await requestSleep()
    if (!slept) {
      setTxingSwitchTarget(null)
    }
  }

  const handleSignOff = (): void => {
    setIsUserMenuOpen(false)
    shadowSessionRef.current?.close()
    shadowSessionRef.current = null
    setShadowConnectionState('idle')
    signOut()
  }

  const handleOpenBoardVideo = (): void => {
    if (!canUseBoardVideo) {
      return
    }
    setIsBoardVideoExpanded((currentValue) => !currentValue)
  }

  if (hasConfigErrors) {
    return (
      <main className="page">
        <section className="card">
          <h1>Txing Shadow Admin</h1>
          <p>App configuration is incomplete.</p>
          <ul className="error-list">
            {appConfig.errors.map((cfgError) => (
              <li key={cfgError}>{cfgError}</li>
            ))}
          </ul>
        </section>
      </main>
    )
  }

  if (status === 'loading' || status === 'authenticating') {
    return (
      <main className="page">
        <section className="card">
          <h1>Txing Shadow Admin</h1>
          <p>{status === 'authenticating' ? 'Finishing sign-in...' : 'Loading session...'}</p>
        </section>
      </main>
    )
  }

  if (status === 'signed_out') {
    return (
      <main className="page page-signed-in">
        <section className="status-hero status-hero-auth" aria-label="Txing sign in">
          <div className="shadow-diagram">
            <div className="status-node status-node-txing">
              <div className="status-txing-header status-auth-header">
                <div
                  className="status-txing-header-side status-txing-header-side-start status-auth-spacer"
                  aria-hidden="true"
                />
                <div className="status-name status-txing-name status-auth-name">Txing</div>
                <div className="status-txing-header-side status-txing-header-side-end">
                  <button type="button" onClick={() => void beginSignIn()} className="primary">
                    Sign in
                  </button>
                </div>
              </div>
            </div>
          </div>
        </section>
        {error && <p className="error status-inline-error">{error}</p>}
      </main>
    )
  }

  return (
    <main className="page page-signed-in">
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
                        disabled={isLoadingShadow || shadowConnectionState !== 'connected'}
                        onClick={() => {
                          void loadShadow()
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
                          setIsUserMenuOpen(false)
                          setIsDebugEnabled((currentValue) => !currentValue)
                        }}
                      >
                        {isDebugEnabled ? 'Disable Debug' : 'Enable Debug'}
                      </button>
                      <button
                        type="button"
                        className="user-menu-item user-menu-item-danger"
                        role="menuitem"
                        onClick={handleSignOff}
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
                    disabled={
                      isLoadingShadow || isUpdatingShadow || isTxingSwitchPending || !canToggleTxingSwitch
                    }
                    onChange={(event) => {
                      void handleTxingSwitchChange(event.target.checked)
                    }}
                  />
                  <span className="status-switch-track" aria-hidden="true">
                    <span className="status-switch-thumb" />
                  </span>
                </label>
                <time
                  className="status-last-shadow-update"
                  dateTime={
                    lastShadowUpdateAtMs === null ? undefined : new Date(lastShadowUpdateAtMs).toISOString()
                  }
                  title={lastShadowUpdateTitle}
                >
                  {lastShadowUpdateLabel}
                </time>
              </div>
              <div className={`status-name status-txing-name ${txingPowerToneClass}`}>Txing</div>
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
                  onClick={handleOpenBoardVideo}
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
              <VideoPage
                authUser={authUser}
                channelName={reportedBoardVideo.channelName}
                debugEnabled={isDebugEnabled}
                embedded
                resolveIdToken={resolveSessionIdToken}
              />
            ) : null}
          </div>
        </div>
      </section>

      {feedback && <p className="feedback status-inline-feedback">{feedback}</p>}
      {reportedBoardVideo.lastError && !error ? (
        <p className="error status-inline-error">{reportedBoardVideo.lastError}</p>
      ) : null}
      {error && <p className="error status-inline-error">{error}</p>}

      {isDebugEnabled && (
        <section className="card debug-panel">
          <div className="status-devices">
            <div className={`status-device ${getPowerNodeClass(reportedMcuPower)}`}>
              <pre className="status-glyph status-glyph-chip" aria-hidden="true">
                {'╭┄┄╮\n┆▣▣┆\n╰┄┄╯'}
              </pre>
              <div className="status-device-label">MCU</div>
            </div>
            <div className={`status-device ${getPowerNodeClass(reportedBoardPower)}`}>
              <pre className="status-glyph status-glyph-board" aria-hidden="true">
                {'┏━╍━┓\n┃▣╋▣┃\n┗┳━┳┛\n◖▂▂◗'}
              </pre>
              <div className="status-device-label">Board</div>
            </div>
          </div>

          <label htmlFor="shadow-json" className="editor-label">
            Current shadow JSON
          </label>
          <textarea
            id="shadow-json"
            className="editor"
            value={shadowJson}
            readOnly
            spellCheck={false}
          />
        </section>
      )}
    </main>
  )
}

export default App
