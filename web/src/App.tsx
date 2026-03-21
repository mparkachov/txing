import { useEffect, useMemo, useRef, useState } from 'react'
import {
  beginSignIn,
  clearAuthState,
  getAuthUser,
  refreshTokensIfNeeded,
  signOut,
  type AuthUser,
} from './auth'
import { appConfig } from './config'
import { getThingShadow, updateThingShadow } from './shadow-api'

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
type BoardVideoStatus = 'idle' | 'connecting' | 'streaming' | 'error'
type BoardVideoRuntime = {
  ready: boolean
  status: 'starting' | 'ready' | 'error' | null
  viewerUrl: string | null
  streamPath: string | null
  lastError: string | null
}

const formatJson = (value: unknown): string => JSON.stringify(value, null, 2)
const shadowPollIntervalMs = 1000
const boardOfflineTimeoutMs = 45000
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

const delay = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms))
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

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null

const extractReportedMcu = (shadow: unknown): Record<string, unknown> | null => {
  if (!isRecord(shadow)) {
    return null
  }
  const state = shadow.state
  if (!isRecord(state)) {
    return null
  }
  const reported = state.reported
  if (!isRecord(reported)) {
    return null
  }
  const mcu = reported.mcu
  return isRecord(mcu) ? mcu : null
}

const extractReportedBoard = (shadow: unknown): Record<string, unknown> | null => {
  if (!isRecord(shadow)) {
    return null
  }
  const state = shadow.state
  if (!isRecord(state)) {
    return null
  }
  const reported = state.reported
  if (!isRecord(reported)) {
    return null
  }
  const board = reported.board
  return isRecord(board) ? board : null
}

const extractReportedBoardPower = (shadow: unknown): boolean | null => {
  const board = extractReportedBoard(shadow)
  if (!board) {
    return null
  }
  return typeof board.power === 'boolean' ? board.power : null
}

const extractReportedMcuPower = (shadow: unknown): boolean | null => {
  const mcu = extractReportedMcu(shadow)
  if (!mcu) {
    return null
  }
  return typeof mcu.power === 'boolean' ? mcu.power : null
}

const extractReportedMcuOnline = (shadow: unknown): boolean | null => {
  const mcu = extractReportedMcu(shadow)
  if (!mcu) {
    return null
  }
  if (typeof mcu.online === 'boolean') {
    return mcu.online
  }
  const ble = mcu.ble
  if (!isRecord(ble)) {
    return null
  }
  return typeof ble.online === 'boolean' ? ble.online : null
}

const extractReportedMcuBleOnline = (shadow: unknown): boolean | null => {
  const mcu = extractReportedMcu(shadow)
  if (!mcu) {
    return null
  }
  const ble = mcu.ble
  return isRecord(ble) && typeof ble.online === 'boolean' ? ble.online : null
}

const extractReportedMcuBatteryMv = (shadow: unknown): number | null => {
  const mcu = extractReportedMcu(shadow)
  if (!mcu) {
    return null
  }
  return typeof mcu.batteryMv === 'number' ? mcu.batteryMv : null
}

const extractReportedBoardWifiOnline = (shadow: unknown): boolean | null => {
  const board = extractReportedBoard(shadow)
  if (!board) {
    return null
  }
  const wifi = board.wifi
  return isRecord(wifi) && typeof wifi.online === 'boolean' ? wifi.online : null
}

const extractReportedBoardVideo = (shadow: unknown): BoardVideoRuntime => {
  const board = extractReportedBoard(shadow)
  if (!board) {
    return {
      ready: false,
      status: null,
      viewerUrl: null,
      streamPath: null,
      lastError: null,
    }
  }

  const video = board.video
  if (!isRecord(video)) {
    return {
      ready: false,
      status: null,
      viewerUrl: null,
      streamPath: null,
      lastError: null,
    }
  }

  const local = video.local
  const localRecord = isRecord(local) ? local : null
  const status = video.status

  return {
    ready: video.ready === true,
    status:
      status === 'starting' || status === 'ready' || status === 'error'
        ? status
        : null,
    viewerUrl:
      localRecord && typeof localRecord.viewerUrl === 'string' && localRecord.viewerUrl.trim()
        ? localRecord.viewerUrl.trim()
        : null,
    streamPath:
      localRecord && typeof localRecord.streamPath === 'string' && localRecord.streamPath.trim()
        ? localRecord.streamPath.trim()
        : null,
    lastError: typeof video.lastError === 'string' && video.lastError.trim() ? video.lastError : null,
  }
}

function App({ initialAuthError = '' }: AppProps) {
  const [status, setStatus] = useState<SessionStatus>('loading')
  const [authUser, setAuthUser] = useState<AuthUser | null>(null)
  const [shadowJson, setShadowJson] = useState<string>('{}')
  const [lastShadowUpdateAtMs, setLastShadowUpdateAtMs] = useState<number | null>(null)
  const [isLoadingShadow, setIsLoadingShadow] = useState(false)
  const [isUpdatingShadow, setIsUpdatingShadow] = useState(false)
  const [isDebugEnabled, setIsDebugEnabled] = useState(false)
  const [isUserMenuOpen, setIsUserMenuOpen] = useState(false)
  const [txingSwitchTarget, setTxingSwitchTarget] = useState<TxingSwitchTarget>(null)
  const [feedback, setFeedback] = useState<string>('')
  const [error, setError] = useState<string>(initialAuthError)
  const [videoStatus, setVideoStatus] = useState<BoardVideoStatus>('idle')
  const [videoMessage, setVideoMessage] = useState<string>('Board video idle')
  const [videoError, setVideoError] = useState<string>('')
  const [isBoardVideoEmbedded, setIsBoardVideoEmbedded] = useState(false)
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
  const batteryPercent = useMemo(
    () => getBatteryPercent(reportedMcuBatteryMv),
    [reportedMcuBatteryMv],
  )
  const batteryToneClass = getBatteryToneClass(batteryPercent)
  const boardWifiToneClass = getBoardWifiToneClass(reportedBoardOnline)
  const bleSignalToneClass = getBleSignalToneClass(reportedMcuBleOnline)
  const txingPowerToneClass = getTxingPowerToneClass(reportedMcuPower, reportedBoardPower)
  const canWake = reportedMcuPower === false && reportedMcuOnline === true
  const canSleep = reportedMcuPower === true || reportedBoardPower === true || reportedBoardOnline === true
  const txingSwitchChecked =
    txingSwitchTarget === 'on' ? true : txingSwitchTarget === 'off' ? false : boardOnline
  const isTxingSwitchPending = txingSwitchTarget !== null
  const canToggleTxingSwitch = txingSwitchChecked ? canSleep : canWake
  const userMenuIdentity = authUser?.email ?? authUser?.name ?? authUser?.sub ?? 'User'
  const userMenuInitial = userMenuIdentity.trim().charAt(0).toUpperCase() || 'U'
  const lastShadowUpdateLabel = formatShadowUpdateTime(lastShadowUpdateAtMs)
  const lastShadowUpdateTitle =
    lastShadowUpdateAtMs === null
      ? 'Last shadow update unavailable'
      : `Last shadow update ${new Date(lastShadowUpdateAtMs).toLocaleString()}`
  const boardVideoReady =
    reportedBoardVideo.ready &&
    reportedBoardVideo.status === 'ready' &&
    reportedBoardVideo.viewerUrl !== null &&
    reportedBoardVideo.streamPath !== null
  const isBoardVideoConnecting = videoStatus === 'connecting'
  const isBoardVideoStreaming = videoStatus === 'streaming'
  const boardVideoPillTone: BoardVideoStatus = isBoardVideoStreaming
    ? 'streaming'
    : isBoardVideoConnecting
      ? 'connecting'
      : videoStatus === 'error' || reportedBoardVideo.status === 'error'
        ? 'error'
        : 'idle'
  const boardVideoPillLabel = isBoardVideoStreaming
    ? 'Live'
    : isBoardVideoConnecting
      ? 'Connecting'
      : videoStatus === 'error'
        ? 'Error'
        : reportedBoardVideo.status === 'ready'
          ? 'Ready'
          : reportedBoardVideo.status === 'error'
            ? 'Error'
            : 'Starting'

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

        const user = getAuthUser(restoredTokens)
        setAuthUser(user)
        setError('')
        setStatus('signed_in')
        setIsLoadingShadow(true)
        try {
          const shadowResponse = await getThingShadow(restoredTokens.idToken)
          const snapshotView = createShadowSnapshotView(shadowResponse)
          setShadowJson(snapshotView.json)
          setLastShadowUpdateAtMs(snapshotView.updatedAtMs)
        } catch (caughtError) {
          setError(caughtError instanceof Error ? caughtError.message : 'Unable to load shadow')
        } finally {
          setIsLoadingShadow(false)
        }
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
      setIsBoardVideoEmbedded(false)
      setVideoStatus('idle')
      setVideoMessage('Board video idle')
      setVideoError('')
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
    if (txingSwitchTarget === 'on' && boardOnline) {
      setTxingSwitchTarget(null)
      return
    }
    if (txingSwitchTarget === 'off' && reportedBoardOnline === false) {
      setTxingSwitchTarget(null)
    }
  }, [boardOnline, reportedBoardOnline, txingSwitchTarget])

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

  useEffect(() => {
    if (!isBoardVideoEmbedded || boardVideoReady) {
      return
    }

    setIsBoardVideoEmbedded(false)
    if (reportedBoardVideo.status === 'error' && reportedBoardVideo.lastError) {
      setVideoStatus('error')
      setVideoMessage(reportedBoardVideo.lastError)
      setVideoError(reportedBoardVideo.lastError)
      return
    }

    setVideoStatus('idle')
    setVideoMessage('Board video unavailable')
    setVideoError('')
  }, [
    boardVideoReady,
    isBoardVideoEmbedded,
    reportedBoardVideo.lastError,
    reportedBoardVideo.status,
  ])

  useEffect(() => {
    if (status !== 'signed_in' || adminEmailMismatch) {
      return
    }

    let cancelled = false
    let timeoutId: number | undefined

    const scheduleNextPoll = () => {
      if (cancelled) {
        return
      }
      timeoutId = window.setTimeout(() => {
        void pollShadow()
      }, shadowPollIntervalMs)
    }

    const pollShadow = async () => {
      if (cancelled) {
        return
      }
      if (isLoadingShadow || isUpdatingShadow) {
        scheduleNextPoll()
        return
      }

      try {
        const refreshedTokens = await refreshTokensIfNeeded()
        if (cancelled) {
          return
        }
        if (!refreshedTokens) {
          clearAuthState()
          setAuthUser(null)
          setStatus('signed_out')
          setError('Session expired. Sign in again.')
          return
        }

        setAuthUser(getAuthUser(refreshedTokens))
        const shadowResponse = await getThingShadow(refreshedTokens.idToken)
        if (cancelled) {
          return
        }
        const snapshotView = createShadowSnapshotView(shadowResponse)
        setShadowJson(snapshotView.json)
        setLastShadowUpdateAtMs(snapshotView.updatedAtMs)
        setError('')
      } catch (caughtError) {
        if (cancelled) {
          return
        }
        setError(caughtError instanceof Error ? caughtError.message : 'Unable to load shadow')
      } finally {
        scheduleNextPoll()
      }
    }

    scheduleNextPoll()

    return () => {
      cancelled = true
      if (timeoutId !== undefined) {
        window.clearTimeout(timeoutId)
      }
    }
  }, [adminEmailMismatch, isLoadingShadow, isUpdatingShadow, status])

  const withApiToken = async (): Promise<string> => {
    const refreshedTokens = await refreshTokensIfNeeded()
    if (!refreshedTokens) {
      clearAuthState()
      setAuthUser(null)
      setStatus('signed_out')
      throw new Error('Session expired. Sign in again.')
    }

    setAuthUser(getAuthUser(refreshedTokens))
    // The identity pool exchanges the user pool ID token for temporary AWS credentials.
    return refreshedTokens.idToken
  }

  const loadShadowWithToken = async (token: string, feedbackMessage?: string): Promise<void> => {
    const response = await getThingShadow(token)
    const snapshotView = createShadowSnapshotView(response)
    setShadowJson(snapshotView.json)
    setLastShadowUpdateAtMs(snapshotView.updatedAtMs)
    if (feedbackMessage) {
      setFeedback(feedbackMessage)
    }
  }

  const loadShadow = async (): Promise<void> => {
    setIsLoadingShadow(true)
    setError('')
    setFeedback('')

    try {
      const token = await withApiToken()
      await loadShadowWithToken(token)
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
      const token = await withApiToken()
      const payload = {
        state: {
          desired: {
            mcu: {
              power,
            },
          },
        },
      }
      await updateThingShadow(token, payload)
      await loadShadowWithToken(
        token,
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
      const token = await withApiToken()
      await updateThingShadow(token, {
        state: {
          desired: {
            board: {
              power: false,
            },
          },
        },
      })

      setFeedback('Waiting for reported.board.power=false...')

      let boardOfflineShadow: unknown | null = null
      const deadline = Date.now() + boardOfflineTimeoutMs
      while (Date.now() < deadline) {
        const shadowResponse = await getThingShadow(token)
        const snapshotView = createShadowSnapshotView(shadowResponse)
        setShadowJson(snapshotView.json)
        setLastShadowUpdateAtMs(snapshotView.updatedAtMs)
        boardOfflineShadow = shadowResponse
        if (extractReportedBoardPower(shadowResponse) === false) {
          break
        }
        await delay(shadowPollIntervalMs)
      }

      if (extractReportedBoardPower(boardOfflineShadow) !== false) {
        throw new Error('Timed out waiting for reported.board.power=false before sleeping MCU')
      }

      await updateThingShadow(token, {
        state: {
          desired: {
            board: {
              power: null,
            },
          },
        },
      })

      await updateThingShadow(token, {
        state: {
          desired: {
            mcu: {
              power: false,
            },
          },
        },
      })
      await loadShadowWithToken(
        token,
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

  const handleMenuLoadShadow = async (): Promise<void> => {
    setIsUserMenuOpen(false)
    await loadShadow()
  }

  const handleToggleDebug = (): void => {
    setIsUserMenuOpen(false)
    setIsDebugEnabled((currentValue) => !currentValue)
  }

  const handleSignOff = (): void => {
    setIsUserMenuOpen(false)
    signOut()
  }

  const handleConnectBoardVideo = (): void => {
    if (!boardVideoReady || !reportedBoardVideo.viewerUrl || !reportedBoardVideo.streamPath) {
      return
    }

    setIsBoardVideoEmbedded(true)
    setVideoStatus('connecting')
    setVideoMessage(`Loading ${reportedBoardVideo.viewerUrl}`)
    setVideoError('')
  }

  const handleDisconnectBoardVideo = (): void => {
    setIsBoardVideoEmbedded(false)
    setVideoStatus('idle')
    setVideoMessage('Board video idle')
    setVideoError('')
  }

  const handleBoardVideoFrameLoad = (): void => {
    if (!isBoardVideoEmbedded) {
      return
    }
    setVideoStatus('streaming')
    setVideoMessage(`Streaming ${reportedBoardVideo.streamPath ?? 'board-cam'}`)
    setVideoError('')
  }

  const handleBoardVideoFrameError = (): void => {
    if (!isBoardVideoEmbedded) {
      return
    }
    setVideoStatus('error')
    setVideoMessage('Board video viewer failed to load')
    setVideoError('Unable to load the MediaMTX viewer page from the board')
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
        <section className="status-hero" aria-label="Txing sign in">
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
      <section className="status-hero" aria-label="Txing status">
        <div className="shadow-diagram">
          <div className="status-node status-node-txing">
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
                        onClick={() => {
                          void handleMenuLoadShadow()
                        }}
                      >
                        Load Shadow
                      </button>
                      <button
                        type="button"
                        className="user-menu-item"
                        role="menuitem"
                        onClick={handleToggleDebug}
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
          </div>
        </div>
      </section>

      <section className="card video-panel" aria-label="Board video">
        <div className="video-panel-header">
          <div>
            <h2 className="video-panel-title">Board Video</h2>
            <p className="video-panel-subtitle">
              {reportedBoardVideo.status === 'error' && reportedBoardVideo.lastError
                ? reportedBoardVideo.lastError
                : reportedBoardVideo.viewerUrl ?? 'Waiting for board media service'}
            </p>
          </div>
          <div className="video-panel-actions">
            <span className={`video-status-pill video-status-${boardVideoPillTone}`}>{boardVideoPillLabel}</span>
            {isBoardVideoEmbedded ? (
              <button type="button" onClick={handleDisconnectBoardVideo}>
                {isBoardVideoStreaming ? 'Disconnect Video' : 'Cancel Video'}
              </button>
            ) : (
              <button
                type="button"
                className="primary"
                onClick={() => {
                  void handleConnectBoardVideo()
                }}
                disabled={!boardVideoReady || isBoardVideoConnecting}
              >
                Connect Video
              </button>
            )}
          </div>
        </div>

        <div className="video-stage">
          {isBoardVideoEmbedded && reportedBoardVideo.viewerUrl ? (
            <iframe
              key={reportedBoardVideo.viewerUrl}
              className="video-preview"
              title="Board video viewer"
              src={reportedBoardVideo.viewerUrl}
              allow="autoplay; fullscreen"
              onLoad={handleBoardVideoFrameLoad}
              onError={handleBoardVideoFrameError}
            />
          ) : (
            <p className="video-placeholder">
              {boardVideoReady
                ? 'Connect video to open the board-local MediaMTX viewer.'
                : 'Board video is not ready yet.'}
            </p>
          )}
        </div>
        {reportedBoardVideo.viewerUrl && (
          <p className="video-message">
            Viewer URL:{' '}
            <a href={reportedBoardVideo.viewerUrl} target="_blank" rel="noreferrer">
              {reportedBoardVideo.viewerUrl}
            </a>
          </p>
        )}
        <p className="video-message">{videoMessage}</p>
        {videoError && <p className="error video-error">{videoError}</p>}
      </section>

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

          {feedback && <p className="feedback">{feedback}</p>}
          {error && <p className="error">{error}</p>}

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

      {!isDebugEnabled && error && <p className="error status-inline-error">{error}</p>}
    </main>
  )
}

export default App
