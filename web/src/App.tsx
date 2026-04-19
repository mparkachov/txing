import {
  useCallback,
  useEffect,
  useEffectEvent,
  useMemo,
  useRef,
  useState,
  type MouseEvent as ReactMouseEvent,
  type ReactElement,
} from 'react'
import {
  beginSignIn,
  clearAuthState,
  getAuthUser,
  refreshTokensIfNeeded,
  signOut,
  type AuthUser,
} from './auth'
import {
  buildDevicePath,
  buildDeviceVideoPath,
  buildRigPath,
  buildTownPath,
  describeRouteTown,
  parseAppRoute,
  type AppRoute,
} from './app-route'
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
import {
  buildBoardVideoChannelName,
  deriveTxingPowerTransitionPending,
  deriveTxingPoweredOn,
  extractDesiredRedcon,
  extractReportedBatteryMv,
  extractReportedBoardDrive,
  extractReportedBoardPower,
  extractReportedBoardVideo,
  extractReportedBoardWifiOnline,
  extractReportedMcuOnline,
  extractReportedMcuPower,
  extractReportedRedcon,
} from './app-model'
import { listRigDevices, listRigThingGroups, isResourceNotFoundError } from './catalog-api'
import { CmdVelTeleopController } from './cmd-vel-teleop'
import type { Twist } from './cmd-vel'
import { appConfig } from './config'
import DebugPanel from './DebugPanel'
import NotificationLogPanel from './NotificationLogPanel'
import NotificationTray from './NotificationTray'
import type { ShadowConnectionState, ShadowSession } from './shadow-api'
import TxingPanel from './TxingPanel'
import VideoPanel from './VideoPanel'

type SessionStatus = 'loading' | 'authenticating' | 'signed_out' | 'signed_in'
type AppProps = {
  initialAuthError?: string
}
type ShadowSnapshotView = {
  json: string
  updatedAtMs: number
}
type RigCatalogState = {
  status: 'idle' | 'loading' | 'ready' | 'error'
  rigNames: string[]
  error: string
}
type DeviceCatalogState = {
  status: 'idle' | 'loading' | 'ready' | 'error' | 'not_found'
  deviceIds: string[]
  error: string
}
type DeviceRoute = {
  town: string
  rig: string
  device: string
}

const formatJson = (value: unknown): string => JSON.stringify(value, null, 2)
const cmdVelRepeatIntervalMs = 100
let shadowApiModulePromise: Promise<typeof import('./shadow-api')> | null = null

const emptyRigCatalogState = (): RigCatalogState => ({
  status: 'idle',
  rigNames: [],
  error: '',
})

const emptyDeviceCatalogState = (): DeviceCatalogState => ({
  status: 'idle',
  deviceIds: [],
  error: '',
})

const createShadowSnapshotView = (shadow: unknown): ShadowSnapshotView => ({
  json: formatJson(shadow),
  updatedAtMs: Date.now(),
})

const loadShadowApiModule = (): Promise<typeof import('./shadow-api')> => {
  if (!shadowApiModulePromise) {
    shadowApiModulePromise = import('./shadow-api')
  }
  return shadowApiModulePromise
}

const getInitialRoute = (): AppRoute => {
  if (typeof window === 'undefined') {
    return { kind: 'root' }
  }

  return parseAppRoute(window.location.pathname)
}

const isPlainLeftClick = (event: ReactMouseEvent<HTMLAnchorElement>): boolean =>
  event.button === 0 &&
  !event.defaultPrevented &&
  !event.metaKey &&
  !event.ctrlKey &&
  !event.altKey &&
  !event.shiftKey

function App({ initialAuthError = '' }: AppProps) {
  const [route, setRoute] = useState<AppRoute>(getInitialRoute)
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
  const [rigCatalog, setRigCatalog] = useState<RigCatalogState>(emptyRigCatalogState)
  const [deviceCatalog, setDeviceCatalog] = useState<DeviceCatalogState>(emptyDeviceCatalogState)
  const shadowSessionRef = useRef<ShadowSession | null>(null)
  const nextNotificationIdRef = useRef(0)
  const nextNotificationLogIdRef = useRef(0)
  const lastBoardVideoErrorRef = useRef<string | null>(null)
  const hasObservedBoardVideoLastErrorRef = useRef(false)

  const hasConfigErrors = appConfig.errors.length > 0
  const configuredTown = appConfig.sparkplugGroupId
  const configuredTownPath = buildTownPath(configuredTown)
  const currentRouteTown = useMemo(() => describeRouteTown(route), [route])
  const hasUnsupportedTown =
    currentRouteTown !== null && currentRouteTown !== appConfig.sparkplugGroupId
  const routeRigName =
    !hasUnsupportedTown &&
    (route.kind === 'rig' || route.kind === 'device' || route.kind === 'device_video')
      ? route.rig
      : null
  const selectedDeviceRoute = useMemo<DeviceRoute | null>(() => {
    if (!hasUnsupportedTown && (route.kind === 'device' || route.kind === 'device_video')) {
      return route
    }
    return null
  }, [hasUnsupportedTown, route])
  const selectedRigName = routeRigName ?? null

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
  const reportedBoardDrive = useMemo(
    () => extractReportedBoardDrive(shadowDocument),
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
    reportedBoardVideo.status === 'ready'
  const boardVideoReachable = !isTxingSwitchPending && boardOnline && reportedBoardPower !== false
  const canUseBoardVideo = boardVideoReachable && boardVideoReady

  const isSelectedDeviceValid =
    selectedDeviceRoute !== null &&
    deviceCatalog.status === 'ready' &&
    deviceCatalog.deviceIds.includes(selectedDeviceRoute.device)

  const activeSessionRoute =
    status === 'signed_in' &&
    !adminEmailMismatch &&
    route.kind === 'device' &&
    isSelectedDeviceValid
      ? selectedDeviceRoute
      : null

  useEffect(() => {
    const handlePopstate = (): void => {
      setRoute(parseAppRoute(window.location.pathname))
    }

    window.addEventListener('popstate', handlePopstate)
    return () => {
      window.removeEventListener('popstate', handlePopstate)
    }
  }, [])

  useEffect(() => {
    window.sessionStorage.setItem(
      notificationLogSessionStorageKey,
      serializeNotificationLog(notificationLog),
    )
  }, [notificationLog])

  const navigateToPath = useCallback((path: string, replace = false): void => {
    const normalizedUrl = new URL(path, window.location.origin)
    const nextPath = `${normalizedUrl.pathname}${normalizedUrl.search}${normalizedUrl.hash}`
    const nextRoute = parseAppRoute(normalizedUrl.pathname)

    if (replace) {
      window.history.replaceState({}, document.title, nextPath)
    } else {
      window.history.pushState({}, document.title, nextPath)
    }
    setRoute(nextRoute)
  }, [])

  const handleRouteLinkClick = useCallback(
    (event: ReactMouseEvent<HTMLAnchorElement>, path: string): void => {
      if (!isPlainLeftClick(event)) {
        return
      }

      event.preventDefault()
      navigateToPath(path)
    },
    [navigateToPath],
  )

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
    hasObservedBoardVideoLastErrorRef.current = false
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
      return
    }
    if (route.kind !== 'root') {
      return
    }

    navigateToPath(configuredTownPath, true)
  }, [adminEmailMismatch, configuredTownPath, navigateToPath, route.kind, status])

  useEffect(() => {
    if (
      status !== 'signed_in' ||
      adminEmailMismatch ||
      route.kind !== 'town' ||
      hasUnsupportedTown
    ) {
      setRigCatalog(emptyRigCatalogState())
      return
    }

    let cancelled = false
    setRigCatalog({
      status: 'loading',
      rigNames: [],
      error: '',
    })

    const loadRigCatalog = async (): Promise<void> => {
      try {
        const rigNames = await listRigThingGroups(resolveSessionIdToken)
        if (cancelled) {
          return
        }

        setRigCatalog({
          status: 'ready',
          rigNames,
          error: '',
        })
      } catch (caughtError) {
        if (cancelled) {
          return
        }
        setRigCatalog({
          status: 'error',
          rigNames: [],
          error:
            caughtError instanceof Error ? caughtError.message : 'Unable to list rigs',
        })
      }
    }

    void loadRigCatalog()

    return () => {
      cancelled = true
    }
  }, [adminEmailMismatch, hasUnsupportedTown, resolveSessionIdToken, route.kind, status])

  useEffect(() => {
    if (
      status !== 'signed_in' ||
      adminEmailMismatch ||
      !selectedRigName ||
      hasUnsupportedTown
    ) {
      setDeviceCatalog(emptyDeviceCatalogState())
      return
    }

    let cancelled = false
    setDeviceCatalog({
      status: 'loading',
      deviceIds: [],
      error: '',
    })

    const loadDeviceCatalog = async (): Promise<void> => {
      try {
        const deviceIds = await listRigDevices(resolveSessionIdToken, selectedRigName)
        if (cancelled) {
          return
        }

        setDeviceCatalog({
          status: 'ready',
          deviceIds,
          error: '',
        })
      } catch (caughtError) {
        if (cancelled) {
          return
        }

        if (isResourceNotFoundError(caughtError)) {
          setDeviceCatalog({
            status: 'not_found',
            deviceIds: [],
            error: `Rig '${selectedRigName}' was not found.`,
          })
          return
        }

        setDeviceCatalog({
          status: 'error',
          deviceIds: [],
          error:
            caughtError instanceof Error ? caughtError.message : 'Unable to list devices',
        })
      }
    }

    void loadDeviceCatalog()

    return () => {
      cancelled = true
    }
  }, [adminEmailMismatch, hasUnsupportedTown, resolveSessionIdToken, selectedRigName, status])

  useEffect(() => {
    if (!activeSessionRoute) {
      shadowSessionRef.current?.close()
      shadowSessionRef.current = null
      setShadowConnectionState('idle')
      setIsLoadingShadow(false)
      setIsUpdatingShadow(false)
      setLastShadowUpdateAtMs(null)
      setShadowJson('{}')
      setIsBoardVideoExpanded(false)
      lastBoardVideoErrorRef.current = null
      hasObservedBoardVideoLastErrorRef.current = false
      return
    }

    let cancelled = false
    let shadowSession: ShadowSession | null = null
    setShadowJson('{}')
    setLastShadowUpdateAtMs(null)
    setIsLoadingShadow(true)
    setIsUpdatingShadow(false)
    setIsBoardVideoExpanded(false)
    setShadowConnectionState('connecting')
    lastBoardVideoErrorRef.current = null
    hasObservedBoardVideoLastErrorRef.current = false

    const startShadowSession = async (): Promise<void> => {
      try {
        const { createShadowSession } = await loadShadowApiModule()
        if (cancelled) {
          return
        }

        shadowSession = createShadowSession({
          thingName: activeSessionRoute.device,
          awsRegion: appConfig.awsRegion,
          sparkplugGroupId: activeSessionRoute.town,
          sparkplugEdgeNodeId: activeSessionRoute.rig,
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

        if (cancelled) {
          shadowSession.close()
          shadowSession = null
          return
        }

        shadowSessionRef.current = shadowSession
        await shadowSession.start()
      } catch (caughtError) {
        if (cancelled) {
          return
        }
        setIsLoadingShadow(false)
        enqueueRuntimeError(
          caughtError instanceof Error ? caughtError.message : 'Unable to open Thing Shadow session',
          'shadow-session',
        )
      }
    }

    void startShadowSession()

    return () => {
      cancelled = true
      if (shadowSessionRef.current === shadowSession) {
        shadowSessionRef.current = null
      }
      shadowSession?.close()
    }
  }, [activeSessionRoute, applyShadowSnapshot, enqueueRuntimeError, resolveSessionIdToken])

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
      hasObservedBoardVideoLastErrorRef.current,
    )
    lastBoardVideoErrorRef.current = nextBoardVideoLastError
    hasObservedBoardVideoLastErrorRef.current = true
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
        message: `Sparkplug DCMD.redcon -> ${redcon}`,
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

  const renderRouteLink = (path: string, label: string): ReactElement => (
    <a
      href={path}
      className="catalog-link"
      onClick={(event) => {
        handleRouteLinkClick(event, path)
      }}
    >
      {label}
    </a>
  )

  const renderBreadcrumbs = (): ReactElement | null => {
    if (route.kind === 'root' || route.kind === 'not_found') {
      return null
    }

    const crumbs = [renderRouteLink(buildTownPath(route.town), route.town)]
    if (route.kind === 'rig' || route.kind === 'device' || route.kind === 'device_video') {
      crumbs.push(renderRouteLink(buildRigPath(route.town, route.rig), route.rig))
    }
    if (route.kind === 'device' || route.kind === 'device_video') {
      crumbs.push(
        renderRouteLink(buildDevicePath(route.town, route.rig, route.device), route.device),
      )
    }
    if (route.kind === 'device_video') {
      crumbs.push(
        <span key={`crumb-video:${route.device}`} className="catalog-crumb-current">
          video
        </span>,
      )
    }
    if (route.kind === 'device') {
      crumbs[crumbs.length - 1] = (
        <span key={`crumb-device:${route.device}`} className="catalog-crumb-current">
          {route.device}
        </span>
      )
    }

    return (
      <nav className="catalog-breadcrumbs" aria-label="Breadcrumb">
        {crumbs.map((crumb, index) => (
          <span key={`crumb:${index}`} className="catalog-breadcrumb">
            {index > 0 ? <span className="catalog-breadcrumb-separator">/</span> : null}
            {crumb}
          </span>
        ))}
      </nav>
    )
  }

  if (hasConfigErrors) {
    return (
      <main className="page">
        <section className="card">
          <h1>Device Shadow Admin</h1>
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
          <h1>Device Shadow Admin</h1>
          <p>{status === 'authenticating' ? 'Finishing sign-in...' : 'Loading session...'}</p>
        </section>
      </main>
    )
  }

  if (status === 'signed_out') {
    return (
      <main className="page page-signed-in">
        <section className="status-hero status-hero-auth" aria-label="Device sign in">
          <div className="shadow-diagram">
            <div className="status-node status-node-txing">
              <div className="status-txing-header status-auth-header">
                <div
                  className="status-txing-header-side status-txing-header-side-start status-auth-spacer"
                  aria-hidden="true"
                />
                <div className="status-name status-txing-name status-auth-name">Bot</div>
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

  const showDevicePanel = activeSessionRoute !== null

  let content: ReactElement
  if (route.kind === 'root') {
    content = (
      <section className="card">
        <h1>Device Shadow Admin</h1>
        <p>Loading town route...</p>
      </section>
    )
  } else if (route.kind === 'not_found') {
    content = (
      <section className="card catalog-card">
        <h1>Route not found</h1>
        <p>The path does not match the supported town / rig / device URL schema.</p>
        <p>{renderRouteLink(configuredTownPath, 'Open the configured town')}</p>
      </section>
    )
  } else if (hasUnsupportedTown) {
    content = (
      <section className="card catalog-card">
        <h1>Unsupported town</h1>
        <p>
          This deployment is scoped to <strong>{configuredTown}</strong>. The current URL targets{' '}
          <strong>{currentRouteTown}</strong>.
        </p>
        <p>{renderRouteLink(configuredTownPath, `Open ${configuredTown}`)}</p>
      </section>
    )
  } else if (route.kind === 'town') {
    content = (
      <section className="card catalog-card">
        <h1>{route.town}</h1>
        <p>Available rigs</p>
        {rigCatalog.status === 'loading' ? <p>Loading rigs...</p> : null}
        {rigCatalog.status === 'error' ? <p className="error">{rigCatalog.error}</p> : null}
        {rigCatalog.status === 'ready' && rigCatalog.rigNames.length === 0 ? (
          <p>No rigs are currently registered for this town.</p>
        ) : null}
        {rigCatalog.rigNames.length > 0 ? (
          <ul className="catalog-list" aria-label={`Rigs in ${route.town}`}>
            {rigCatalog.rigNames.map((rigName) => (
              <li key={rigName} className="catalog-list-item">
                {renderRouteLink(buildRigPath(route.town, rigName), rigName)}
              </li>
            ))}
          </ul>
        ) : null}
      </section>
    )
  } else if (route.kind === 'rig') {
    content = (
      <section className="card catalog-card">
        {renderBreadcrumbs()}
        <h1>{route.rig}</h1>
        <p>Registered devices</p>
        {deviceCatalog.status === 'loading' ? <p>Loading devices...</p> : null}
        {deviceCatalog.status === 'not_found' ? <p className="error">{deviceCatalog.error}</p> : null}
        {deviceCatalog.status === 'error' ? <p className="error">{deviceCatalog.error}</p> : null}
        {deviceCatalog.status === 'ready' && deviceCatalog.deviceIds.length === 0 ? (
          <p>No devices are currently assigned to this rig.</p>
        ) : null}
        {deviceCatalog.deviceIds.length > 0 ? (
          <ul className="catalog-list" aria-label={`Devices in ${route.rig}`}>
            {deviceCatalog.deviceIds.map((deviceId) => (
              <li key={deviceId} className="catalog-list-item">
                {renderRouteLink(buildDevicePath(route.town, route.rig, deviceId), deviceId)}
              </li>
            ))}
          </ul>
        ) : null}
      </section>
    )
  } else if (selectedDeviceRoute && deviceCatalog.status === 'loading') {
    content = (
      <section className="card catalog-card">
        {renderBreadcrumbs()}
        <h1>{selectedDeviceRoute.device}</h1>
        <p>Validating device membership for rig {selectedDeviceRoute.rig}...</p>
      </section>
    )
  } else if (
    selectedDeviceRoute &&
    (deviceCatalog.status === 'not_found' ||
      deviceCatalog.status === 'error' ||
      (deviceCatalog.status === 'ready' &&
        !deviceCatalog.deviceIds.includes(selectedDeviceRoute.device)))
  ) {
    content = (
      <section className="card catalog-card">
        {renderBreadcrumbs()}
        <h1>Device not found</h1>
        <p>
          {deviceCatalog.status === 'error'
            ? deviceCatalog.error
            : `Device '${selectedDeviceRoute.device}' is not assigned to rig '${selectedDeviceRoute.rig}'.`}
        </p>
        <p>
          {renderRouteLink(
            buildRigPath(selectedDeviceRoute.town, selectedDeviceRoute.rig),
            `Open ${selectedDeviceRoute.rig}`,
          )}
        </p>
      </section>
    )
  } else if (route.kind === 'device_video' && selectedDeviceRoute) {
    content = (
      <>
        <section className="card catalog-card catalog-card-detail">
          {renderBreadcrumbs()}
          <div className="catalog-detail-heading">
            <h1>{selectedDeviceRoute.device} video</h1>
            <p>
              Rig <strong>{selectedDeviceRoute.rig}</strong> · Town{' '}
              <strong>{selectedDeviceRoute.town}</strong>
            </p>
          </div>
        </section>
        <section className="card catalog-card catalog-card-detail">
          <VideoPanel
            channelName={buildBoardVideoChannelName(selectedDeviceRoute.device)}
            debugEnabled={isDebugEnabled}
            onRuntimeError={(message: string) => {
              enqueueRuntimeError(message, 'board-video-viewer')
            }}
            resolveIdToken={resolveSessionIdToken}
          />
        </section>
      </>
    )
  } else if (showDevicePanel && selectedDeviceRoute) {
    content = (
      <>
        <section className="card catalog-card catalog-card-detail">
          {renderBreadcrumbs()}
          <div className="catalog-detail-heading">
            <h1>{selectedDeviceRoute.device}</h1>
            <p>
              Rig <strong>{selectedDeviceRoute.rig}</strong> · Town{' '}
              <strong>{selectedDeviceRoute.town}</strong> ·{' '}
              {renderRouteLink(
                buildDeviceVideoPath(
                  selectedDeviceRoute.town,
                  selectedDeviceRoute.rig,
                  selectedDeviceRoute.device,
                ),
                'open video route',
              )}
            </p>
          </div>
        </section>

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
          reportedBoardLeftTrackSpeed={reportedBoardDrive.leftSpeed}
          reportedBoardOnline={reportedBoardOnline}
          reportedBoardRightTrackSpeed={reportedBoardDrive.rightSpeed}
          reportedBatteryMv={reportedBatteryMv}
          reportedMcuOnline={reportedMcuOnline}
          reportedRedcon={reportedRedcon}
          txingSwitchChecked={txingSwitchChecked}
          videoChannelName={buildBoardVideoChannelName(selectedDeviceRoute.device)}
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
      </>
    )
  } else {
    content = (
      <section className="card catalog-card">
        <h1>Device Shadow Admin</h1>
        <p>Waiting for a valid route selection.</p>
        <p>{renderRouteLink(configuredTownPath, `Open ${configuredTown}`)}</p>
      </section>
    )
  }

  return (
    <main className="page page-signed-in">
      {content}

      <NotificationTray
        notifications={notifications}
        onDismiss={(notificationId) => {
          dismissNotification(notificationId)
        }}
      />

      {isSessionLogVisible && <NotificationLogPanel notificationLog={notificationLog} />}

      {isDebugEnabled && showDevicePanel && (
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
