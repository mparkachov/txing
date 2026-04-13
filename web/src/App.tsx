import { useCallback, useEffect, useEffectEvent, useMemo, useRef, useState } from 'react'
import {
  beginSignIn,
  clearAuthState,
  getAuthUser,
  refreshTokensIfNeeded,
  signOut,
  type AuthUser,
} from './auth'
import {
  deriveTxingPowerTransitionPending,
  deriveTxingPoweredOn,
  extractDesiredRedcon,
  extractReportedBatteryMv,
  extractReportedBoardPower,
  extractReportedBoardVideo,
  extractReportedBoardWifiOnline,
  extractReportedMcuOnline,
  extractReportedMcuPower,
  extractReportedRedcon,
} from './app-model'
import { appConfig } from './config'
import { CmdVelTeleopController } from './cmd-vel-teleop'
import type { Twist } from './cmd-vel'
import DebugPanel from './DebugPanel'
import NotificationLogPanel from './NotificationLogPanel'
import NotificationTray from './NotificationTray'
import {
  appendNotificationLogEntry,
  deserializeNotificationLog,
  dismissAppNotification,
  enqueueAppNotification,
  expireAppNotifications,
  getNextBoardVideoLastErrorNotification,
  notificationLogSessionStorageKey,
  normalizeRuntimeMessage,
  serializeNotificationLog,
  type AppNotification,
  type AppNotificationInput,
  type AppNotificationLogEntry,
} from './app-notifications'
import { createShadowSession, type ShadowConnectionState, type ShadowSession } from './shadow-api'
import TxingPanel from './TxingPanel'

type SessionStatus = 'loading' | 'authenticating' | 'signed_out' | 'signed_in'
type AppProps = {
  initialAuthError?: string
}
type ShadowSnapshotView = {
  json: string
  updatedAtMs: number
}

const formatJson = (value: unknown): string => JSON.stringify(value, null, 2)
const cmdVelRepeatIntervalMs = 100

const createShadowSnapshotView = (shadow: unknown): ShadowSnapshotView => ({
  json: formatJson(shadow),
  updatedAtMs: Date.now(),
})

function App({ initialAuthError = '' }: AppProps) {
  const [status, setStatus] = useState<SessionStatus>('loading')
  const [authUser, setAuthUser] = useState<AuthUser | null>(null)
  const [shadowJson, setShadowJson] = useState<string>('{}')
  const [lastShadowUpdateAtMs, setLastShadowUpdateAtMs] = useState<number | null>(null)
  const [isLoadingShadow, setIsLoadingShadow] = useState(false)
  const [isUpdatingShadow, setIsUpdatingShadow] = useState(false)
  const [isDebugEnabled, setIsDebugEnabled] = useState(false)
  const [isBoardVideoExpanded, setIsBoardVideoExpanded] = useState(false)
  const [isSessionLogVisible, setIsSessionLogVisible] = useState(false)
  const [blockingError, setBlockingError] = useState<string>(initialAuthError)
  const [notifications, setNotifications] = useState<AppNotification[]>([])
  const [notificationLog, setNotificationLog] = useState<AppNotificationLogEntry[]>(() => {
    if (typeof window === 'undefined') {
      return []
    }
    return deserializeNotificationLog(
      window.sessionStorage.getItem(notificationLogSessionStorageKey),
    )
  })
  const [shadowConnectionState, setShadowConnectionState] =
    useState<ShadowConnectionState>('idle')
  const shadowSessionRef = useRef<ShadowSession | null>(null)
  const nextNotificationIdRef = useRef(0)
  const nextNotificationLogIdRef = useRef(0)
  const lastBoardVideoErrorRef = useRef<string | null>(null)

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
  const reportedBatteryMv = useMemo(
    () => extractReportedBatteryMv(shadowDocument),
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
  const reportedRedcon = useMemo(
    () => extractReportedRedcon(shadowDocument),
    [shadowDocument],
  )
  const desiredRedcon = useMemo(
    () => extractDesiredRedcon(shadowDocument),
    [shadowDocument],
  )

  const boardOnline = reportedBoardOnline === true
  const txingPoweredOn = useMemo(
    () =>
      deriveTxingPoweredOn({
        reportedRedcon,
        reportedMcuPower,
        reportedBoardPower,
        reportedBoardWifiOnline: reportedBoardOnline,
      }),
    [reportedBoardOnline, reportedBoardPower, reportedMcuPower, reportedRedcon],
  )
  const canWake = !txingPoweredOn && reportedMcuOnline === true && desiredRedcon !== 3
  const canSleep = txingPoweredOn && desiredRedcon !== 4
  const isShadowConnected = shadowConnectionState === 'connected'
  const txingSwitchChecked = txingPoweredOn
  const isTxingSwitchPending = useMemo(
    () =>
      deriveTxingPowerTransitionPending({
        desiredRedcon,
        reportedRedcon,
      }),
    [desiredRedcon, reportedRedcon],
  )
  const canToggleTxingSwitch = (txingSwitchChecked ? canSleep : canWake) && isShadowConnected
  const canLoadShadow = !isLoadingShadow && isShadowConnected
  const isTxingSwitchDisabled =
    isLoadingShadow || isUpdatingShadow || isTxingSwitchPending || !canToggleTxingSwitch
  const boardVideoReady =
    reportedBoardVideo.transport === 'aws-webrtc' &&
    reportedBoardVideo.ready &&
    reportedBoardVideo.status === 'ready' &&
    reportedBoardVideo.channelName !== null
  const boardVideoReachable = !isTxingSwitchPending && boardOnline && reportedBoardPower !== false
  const canUseBoardVideo = boardVideoReachable && boardVideoReady

  useEffect(() => {
    window.sessionStorage.setItem(
      notificationLogSessionStorageKey,
      serializeNotificationLog(notificationLog),
    )
  }, [notificationLog])

  const enqueueNotification = useCallback((notification: AppNotificationInput): void => {
    const nowMs = Date.now()
    nextNotificationIdRef.current += 1
    const nextNotificationId = `runtime-notification-${nextNotificationIdRef.current}`
    setNotifications((currentNotifications) =>
      enqueueAppNotification(currentNotifications, notification, nowMs, nextNotificationId),
    )
    nextNotificationLogIdRef.current += 1
    const nextNotificationLogId = `runtime-log-${nowMs}-${nextNotificationLogIdRef.current}`
    setNotificationLog((currentNotificationLog) =>
      appendNotificationLogEntry(currentNotificationLog, notification, nowMs, nextNotificationLogId),
    )
  }, [])

  const dismissNotification = useCallback((notificationId: string): void => {
    setNotifications((currentNotifications) =>
      dismissAppNotification(currentNotifications, notificationId),
    )
  }, [])

  const enqueueRuntimeError = useCallback((message: string, source: string): void => {
    const normalizedMessage = normalizeRuntimeMessage(message)
    if (!normalizedMessage) {
      return
    }
    enqueueNotification({
      tone: 'error',
      message: normalizedMessage,
      dedupeKey: `${source}:${normalizedMessage}`,
    })
  }, [enqueueNotification])

  const applyShadowSnapshot = useCallback((shadow: unknown): void => {
    const snapshotView = createShadowSnapshotView(shadow)
    setShadowJson(snapshotView.json)
    setLastShadowUpdateAtMs(snapshotView.updatedAtMs)
  }, [])

  const resolveSessionIdToken = useCallback(async (): Promise<string> => {
    const refreshedTokens = await refreshTokensIfNeeded()
    if (!refreshedTokens) {
      clearAuthState()
      setAuthUser(null)
      setStatus('signed_out')
      setBlockingError('Session expired. Sign in again.')
      throw new Error('Session expired. Sign in again.')
    }

    setAuthUser(getAuthUser(refreshedTokens))
    return refreshedTokens.idToken
  }, [])

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
      if (!initialAuthError) {
        setBlockingError('')
      }

      try {
        const restoredTokens = await refreshTokensIfNeeded()
        if (!restoredTokens) {
          setStatus('signed_out')
          return
        }

        setAuthUser(getAuthUser(restoredTokens))
        setBlockingError('')
        setStatus('signed_in')
      } catch (caughtError) {
        clearAuthState()
        setStatus('signed_out')
        setBlockingError(caughtError instanceof Error ? caughtError.message : 'Authentication failed')
      }
    }

    void hydrateSession()
  }, [hasConfigErrors, initialAuthError])

  useEffect(() => {
    if (status === 'signed_in') {
      return
    }
    lastBoardVideoErrorRef.current = null
    setNotifications([])
  }, [status])

  useEffect(() => {
    if (notifications.length === 0) {
      return
    }

    const nextExpirationAtMs = Math.min(
      ...notifications.map((notification) => notification.expiresAtMs),
    )
    const timeoutDelayMs = Math.max(0, nextExpirationAtMs - Date.now())
    const timeoutId = window.setTimeout(() => {
      setNotifications((currentNotifications) =>
        expireAppNotifications(currentNotifications, Date.now()),
      )
    }, timeoutDelayMs)

    return () => {
      window.clearTimeout(timeoutId)
    }
  }, [notifications])

  useEffect(() => {
    if (status !== 'signed_in') {
      return
    }
    if (!adminEmailMismatch) {
      return
    }

    clearAuthState()
    setStatus('signed_out')
    setBlockingError(`Signed-in user is not allowed. Expected: ${appConfig.adminEmail}`)
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
      awsRegion: appConfig.awsRegion,
      sparkplugGroupId: appConfig.sparkplugGroupId,
      sparkplugEdgeNodeId: appConfig.sparkplugEdgeNodeId,
      resolveIdToken: resolveSessionIdToken,
      onShadowDocument: (shadow) => {
        if (cancelled) {
          return
        }
        applyShadowSnapshot(shadow)
        setIsLoadingShadow(false)
      },
      onConnectionStateChange: (nextState) => {
        if (!cancelled) {
          setShadowConnectionState(nextState)
        }
      },
      onError: (message) => {
        if (!cancelled) {
          enqueueRuntimeError(message, 'shadow-session')
        }
      },
    })

    shadowSessionRef.current = shadowSession
    setIsLoadingShadow(true)
    setShadowConnectionState('connecting')

    void shadowSession.start().catch((caughtError) => {
      if (cancelled) {
        return
      }
      setIsLoadingShadow(false)
      enqueueRuntimeError(
        caughtError instanceof Error ? caughtError.message : 'Unable to open Thing Shadow session',
        'shadow-session',
      )
    })

    return () => {
      cancelled = true
      if (shadowSessionRef.current === shadowSession) {
        shadowSessionRef.current = null
      }
      shadowSession.close()
    }
  }, [adminEmailMismatch, applyShadowSnapshot, enqueueRuntimeError, resolveSessionIdToken, status])

  const publishCmdVel = useEffectEvent(async (twist: Twist): Promise<void> => {
    const shadowSession = shadowSessionRef.current
    if (!shadowSession || !shadowSession.isConnected()) {
      return
    }

    try {
      await shadowSession.publishCmdVel(twist)
    } catch (caughtError) {
      enqueueRuntimeError(
        caughtError instanceof Error ? caughtError.message : 'Unable to publish board cmd_vel',
        'board-cmd-vel',
      )
    }
  })

  useEffect(() => {
    const nextBoardVideoLastError = normalizeRuntimeMessage(reportedBoardVideo.lastError)
    const nextNotificationMessage = getNextBoardVideoLastErrorNotification(
      lastBoardVideoErrorRef.current,
      nextBoardVideoLastError,
    )
    lastBoardVideoErrorRef.current = nextBoardVideoLastError
    if (!nextNotificationMessage) {
      return
    }
    enqueueNotification({
      tone: 'error',
      message: nextNotificationMessage,
      dedupeKey: `board-video-shadow:${nextNotificationMessage}`,
    })
  }, [enqueueNotification, reportedBoardVideo.lastError])

  useEffect(() => {
    if (!canUseBoardVideo && isBoardVideoExpanded) {
      setIsBoardVideoExpanded(false)
    }
  }, [canUseBoardVideo, isBoardVideoExpanded])

  useEffect(() => {
    if (!isBoardVideoExpanded || !canUseBoardVideo || !isShadowConnected) {
      return
    }

    const teleopController = new CmdVelTeleopController({
      publishCmdVel,
    })
    teleopController.activate()

    const repeatTimerId = window.setInterval(() => {
      teleopController.tick()
    }, cmdVelRepeatIntervalMs)

    const handleKeyDown = (event: KeyboardEvent): void => {
      if (teleopController.handleKeyDown(event.key, event.repeat)) {
        event.preventDefault()
      }
    }

    const handleKeyUp = (event: KeyboardEvent): void => {
      if (teleopController.handleKeyUp(event.key)) {
        event.preventDefault()
      }
    }

    const handleBlur = (): void => {
      teleopController.handleBlur()
    }

    const handleVisibilityChange = (): void => {
      if (document.hidden) {
        teleopController.handleVisibilityHidden()
      }
    }

    const handlePageHide = (): void => {
      teleopController.handleBlur()
    }

    window.addEventListener('keydown', handleKeyDown)
    window.addEventListener('keyup', handleKeyUp)
    window.addEventListener('blur', handleBlur)
    window.addEventListener('pagehide', handlePageHide)
    document.addEventListener('visibilitychange', handleVisibilityChange)

    return () => {
      window.clearInterval(repeatTimerId)
      window.removeEventListener('keydown', handleKeyDown)
      window.removeEventListener('keyup', handleKeyUp)
      window.removeEventListener('blur', handleBlur)
      window.removeEventListener('pagehide', handlePageHide)
      document.removeEventListener('visibilitychange', handleVisibilityChange)
      teleopController.deactivate()
    }
  }, [canUseBoardVideo, isBoardVideoExpanded, isShadowConnected])

  const loadShadow = async (): Promise<void> => {
    setIsLoadingShadow(true)

    try {
      const shadowSession = getShadowSession()
      const shadowResponse = await shadowSession.requestSnapshot()
      applyShadowSnapshot(shadowResponse)
    } catch (caughtError) {
      enqueueRuntimeError(
        caughtError instanceof Error ? caughtError.message : 'Unable to load shadow',
        'shadow-load',
      )
    } finally {
      setIsLoadingShadow(false)
    }
  }

  const publishRedconCommand = async (redcon: 3 | 4): Promise<boolean> => {
    setIsUpdatingShadow(true)

    try {
      const shadowSession = getShadowSession()
      await shadowSession.publishRedconCommand(redcon)
      enqueueNotification({
        tone: 'success',
        message: `Sparkplug DCMD.redcon -> ${redcon} at ${new Date().toLocaleTimeString()}`,
        dedupeKey: `sparkplug-redcon:${redcon}`,
      })
      return true
    } catch (caughtError) {
      enqueueRuntimeError(
        caughtError instanceof Error ? caughtError.message : 'Unable to publish Sparkplug command',
        'sparkplug-redcon',
      )
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
      await publishRedconCommand(3)
      return
    }

    if (!canSleep) {
      return
    }

    await publishRedconCommand(4)
  }

  const handleSignOff = (): void => {
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
        {blockingError && <p className="error status-inline-error">{blockingError}</p>}
      </main>
    )
  }

  return (
    <main className="page page-signed-in">
      <NotificationTray
        notifications={notifications}
        onDismiss={(notificationId) => {
          dismissNotification(notificationId)
        }}
      />
      <TxingPanel
        authUser={authUser}
        canLoadShadow={canLoadShadow}
        canUseBoardVideo={canUseBoardVideo}
        isBoardVideoExpanded={isBoardVideoExpanded}
        isDebugEnabled={isDebugEnabled}
        isSessionLogVisible={isSessionLogVisible}
        isTxingSwitchDisabled={isTxingSwitchDisabled}
        isTxingSwitchPending={isTxingSwitchPending}
        lastShadowUpdateAtMs={lastShadowUpdateAtMs}
        reportedBoardOnline={reportedBoardOnline}
        reportedBatteryMv={reportedBatteryMv}
        reportedMcuOnline={reportedMcuOnline}
        reportedRedcon={reportedRedcon}
        txingSwitchChecked={txingSwitchChecked}
        videoChannelName={reportedBoardVideo.channelName}
        resolveIdToken={resolveSessionIdToken}
        onBoardVideoRuntimeError={(message) => {
          enqueueRuntimeError(message, 'board-video-viewer')
        }}
        onLoadShadow={() => {
          void loadShadow()
        }}
        onSignOff={handleSignOff}
        onToggleBoardVideo={handleOpenBoardVideo}
        onToggleDebug={() => {
          setIsDebugEnabled((currentValue) => !currentValue)
        }}
        onToggleSessionLog={() => {
          setIsSessionLogVisible((currentValue) => !currentValue)
        }}
        onTxingSwitchChange={(checked) => {
          void handleTxingSwitchChange(checked)
        }}
      />

      {isSessionLogVisible && <NotificationLogPanel notificationLog={notificationLog} />}

      {isDebugEnabled && (
        <DebugPanel
          reportedBoardPower={reportedBoardPower}
          reportedMcuPower={reportedMcuPower}
          shadowJson={shadowJson}
        />
      )}
    </main>
  )
}

export default App
