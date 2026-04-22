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
  extractDesiredRedcon,
  extractReportedBatteryMv,
  extractReportedBoardPower,
  extractReportedBoardWifiOnline,
  extractReportedMcuOnline,
  extractReportedMcuPower,
  extractReportedRedcon,
  selectPrimaryReportedRedcon,
} from './app-model'
import {
  isResourceNotFoundError,
  listRigDevices,
  listRigThingGroups,
  type DeviceCatalogEntry,
  type RigCatalogEntry,
} from './catalog-api'
import { CmdVelTeleopController } from './cmd-vel-teleop'
import type { Twist } from './cmd-vel'
import { appConfig } from './config'
import DebugPanel from './DebugPanel'
import { getMcpSteadyMotionHeartbeatIntervalMs } from './mcp-lease'
import NotificationLogPanel from './NotificationLogPanel'
import NotificationTray from './NotificationTray'
import type { RobotState, ShadowConnectionState, ShadowSession } from './shadow-api'
import { publishSparkplugRedconCommandWithAck } from './sparkplug-command'
import SparkplugPanel from './SparkplugPanel'
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
  rigs: RigCatalogEntry[]
  error: string
}
type DeviceCatalogState = {
  status: 'idle' | 'loading' | 'ready' | 'error' | 'not_found'
  devices: DeviceCatalogEntry[]
  error: string
}
type DeviceRoute = {
  town: string
  rig: string
  device: string
}

const formatJson = (value: unknown): string => JSON.stringify(value, null, 2)
const defaultMcpLeaseTtlMs = 5_000
const robotStatePollIntervalMs = 5_000
const txingLogoUrl = 'https://txing.dev/txing-logo.png'
const appHomePath = '/'
let shadowApiModulePromise: Promise<typeof import('./shadow-api')> | null = null

const emptyRigCatalogState = (): RigCatalogState => ({
  status: 'idle',
  rigs: [],
  error: '',
})

const emptyDeviceCatalogState = (): DeviceCatalogState => ({
  status: 'idle',
  devices: [],
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

const formatShadowUpdateTime = (updatedAtMs: number | null): string =>
  updatedAtMs === null
    ? '--:--:--'
    : new Date(updatedAtMs).toLocaleTimeString([], {
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
      })

const getCatalogDeviceLabel = (device: DeviceCatalogEntry | null | undefined): string =>
  device?.deviceName?.trim() ? device.deviceName.trim() : 'Unnamed device'

const getCatalogDescription = (description: string | null | undefined, fallback: string): string =>
  typeof description === 'string' && description.trim() !== '' ? description.trim() : fallback

type NavigationUserMenuProps = {
  authUser: AuthUser | null
  canLoadShadow: boolean
  isDebugEnabled: boolean
  isSessionLogVisible: boolean
  onLoadShadow: () => void
  onSignOff: () => void
  onToggleDebug: () => void
  onToggleSessionLog: () => void
}

function NavigationUserMenu({
  authUser,
  canLoadShadow,
  isDebugEnabled,
  isSessionLogVisible,
  onLoadShadow,
  onSignOff,
  onToggleDebug,
  onToggleSessionLog,
}: NavigationUserMenuProps) {
  const [isUserMenuOpen, setIsUserMenuOpen] = useState(false)
  const userMenuRef = useRef<HTMLDivElement | null>(null)
  const userMenuIdentity = authUser?.email ?? authUser?.name ?? authUser?.sub ?? 'User'
  const userMenuInitial = userMenuIdentity.trim().charAt(0).toUpperCase() || 'U'

  useEffect(() => {
    if (!isUserMenuOpen) {
      return
    }

    const handlePointerDown = (event: MouseEvent): void => {
      if (!userMenuRef.current?.contains(event.target as Node)) {
        setIsUserMenuOpen(false)
      }
    }

    const handleEscape = (event: KeyboardEvent): void => {
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
      {isUserMenuOpen ? (
        <div className="user-menu-popover" role="menu" aria-label="User actions">
          <div className="user-menu-header">
            <span className="user-avatar user-avatar-large" aria-hidden="true">
              {userMenuInitial}
            </span>
            <div className="user-menu-identity">
              <p className="user-menu-name">{authUser?.name ?? 'Signed in'}</p>
              <p className="user-menu-email">{authUser?.email ?? authUser?.sub ?? 'Unknown user'}</p>
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
      ) : null}
    </div>
  )
}

function App({ initialAuthError = '' }: AppProps) {
  const [route, setRoute] = useState<AppRoute>(getInitialRoute)
  const [status, setStatus] = useState<SessionStatus>('loading')
  const [authUser, setAuthUser] = useState<AuthUser | null>(null)
  const [shadowJson, setShadowJson] = useState<string>('{}')
  const [sparkplugReportedBatteryMv, setSparkplugReportedBatteryMv] = useState<number | null>(null)
  const [sparkplugReportedRedcon, setSparkplugReportedRedcon] = useState<number | null>(null)
  const [robotState, setRobotState] = useState<RobotState | null>(null)
  const [lastShadowUpdateAtMs, setLastShadowUpdateAtMs] = useState<number | null>(null)
  const [isLoadingShadow, setIsLoadingShadow] = useState(false)
  const [isUpdatingShadow, setIsUpdatingShadow] = useState(false)
  const [isDebugEnabled, setIsDebugEnabled] = useState(false)
  const [isTownPanelOpen, setIsTownPanelOpen] = useState(false)
  const [isRigPanelOpen, setIsRigPanelOpen] = useState(false)
  const [isBotPanelOpen, setIsBotPanelOpen] = useState(false)
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
  const redconCommandSequenceRef = useRef(0)
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
  const selectedDeviceEntry = useMemo(() => {
    if (!selectedDeviceRoute || deviceCatalog.status !== 'ready') {
      return null
    }

    return (
      deviceCatalog.devices.find((device) => device.thingName === selectedDeviceRoute.device) ?? null
    )
  }, [deviceCatalog.devices, deviceCatalog.status, selectedDeviceRoute])
  const selectedDeviceLabel = useMemo(() => {
    if (!selectedDeviceRoute) {
      return null
    }
    return selectedDeviceEntry ? getCatalogDeviceLabel(selectedDeviceEntry) : 'Device'
  }, [selectedDeviceEntry, selectedDeviceRoute])

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
  const primaryReportedBatteryMv = sparkplugReportedBatteryMv ?? reportedBatteryMv
  const reportedBoardPower = useMemo(
    () => extractReportedBoardPower(shadowDocument),
    [shadowDocument],
  )
  const reportedBoardOnline = useMemo(
    () => extractReportedBoardWifiOnline(shadowDocument),
    [shadowDocument],
  )
  const shadowReportedRedcon = useMemo(
    () => extractReportedRedcon(shadowDocument),
    [shadowDocument],
  )
  const reportedRedcon = useMemo(
    () =>
      selectPrimaryReportedRedcon({
        sparkplugReportedRedcon,
        shadowReportedRedcon,
      }),
    [shadowReportedRedcon, sparkplugReportedRedcon],
  )
  const desiredRedcon = useMemo(
    () => extractDesiredRedcon(shadowDocument),
    [shadowDocument],
  )

  const isShadowConnected = shadowConnectionState === 'connected'
  const isRedconCommandPending = desiredRedcon !== null && desiredRedcon !== reportedRedcon
  const isRedconCommandDisabled =
    isLoadingShadow || isUpdatingShadow || isRedconCommandPending || !isShadowConnected
  const isRedconSleepCommandDisabled = isLoadingShadow || !isShadowConnected
  const canLoadShadow = !isLoadingShadow && isShadowConnected
  const canUseBoardVideo = reportedRedcon === 1
  const cmdVelRepeatIntervalMs = getMcpSteadyMotionHeartbeatIntervalMs(
    robotState?.control.leaseTtlMs ?? defaultMcpLeaseTtlMs,
  )
  const isRobotMotionActive =
    (robotState?.motion.leftSpeed ?? 0) !== 0 || (robotState?.motion.rightSpeed ?? 0) !== 0
  const isRobotControlActive = robotState?.control.leaseHeldByCaller === true
  const reportedBoardLeftTrackSpeed = robotState?.motion.leftSpeed ?? null
  const reportedBoardRightTrackSpeed = robotState?.motion.rightSpeed ?? null
  const robotVideoLastError = robotState?.video.lastError ?? null

  const isSelectedDeviceValid =
    selectedDeviceRoute !== null &&
    deviceCatalog.status === 'ready' &&
    deviceCatalog.devices.some((device) => device.thingName === selectedDeviceRoute.device)

  const activeSessionRoute =
    status === 'signed_in' &&
    !adminEmailMismatch &&
    (route.kind === 'device' || route.kind === 'device_video') &&
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

  const appendSessionLogEntry = useCallback((notification: AppNotificationInput): void => {
    const nowMs = Date.now()
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
    setRobotState(null)
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
      rigs: [],
      error: '',
    })

    const loadRigCatalog = async (): Promise<void> => {
      try {
        const rigs = await listRigThingGroups(resolveSessionIdToken)
        if (cancelled) {
          return
        }

        setRigCatalog({
          status: 'ready',
          rigs,
          error: '',
        })
      } catch (caughtError) {
        if (cancelled) {
          return
        }
        setRigCatalog({
          status: 'error',
          rigs: [],
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
      devices: [],
      error: '',
    })

    const loadDeviceCatalog = async (): Promise<void> => {
      try {
        const devices = await listRigDevices(resolveSessionIdToken, selectedRigName)
        if (cancelled) {
          return
        }

        setDeviceCatalog({
          status: 'ready',
          devices,
          error: '',
        })
      } catch (caughtError) {
        if (cancelled) {
          return
        }

        if (isResourceNotFoundError(caughtError)) {
          setDeviceCatalog({
            status: 'not_found',
            devices: [],
            error: `Rig '${selectedRigName}' was not found.`,
          })
          return
        }

        setDeviceCatalog({
          status: 'error',
          devices: [],
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
    setIsTownPanelOpen(false)
    setIsRigPanelOpen(false)
  }, [
    route.kind,
    route.kind === 'town'
      ? route.town
      : route.kind === 'rig' || route.kind === 'device' || route.kind === 'device_video'
        ? `${route.town}/${route.rig}`
        : '',
  ])

  useEffect(() => {
    if (!activeSessionRoute) {
      shadowSessionRef.current?.close()
      shadowSessionRef.current = null
      setShadowConnectionState('idle')
      setIsLoadingShadow(false)
      setIsUpdatingShadow(false)
      setLastShadowUpdateAtMs(null)
      setShadowJson('{}')
      setSparkplugReportedBatteryMv(null)
      setSparkplugReportedRedcon(null)
      setRobotState(null)
      setIsBotPanelOpen(false)
      setIsBoardVideoExpanded(false)
      lastBoardVideoErrorRef.current = null
      hasObservedBoardVideoLastErrorRef.current = false
      return
    }

    let cancelled = false
    let shadowSession: ShadowSession | null = null
    setShadowJson('{}')
    setSparkplugReportedBatteryMv(null)
    setSparkplugReportedRedcon(null)
    setRobotState(null)
    setLastShadowUpdateAtMs(null)
    setIsLoadingShadow(true)
    setIsUpdatingShadow(false)
    setIsBotPanelOpen(false)
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
          onSparkplugRedconChange: (nextRedcon) => {
            if (cancelled) {
              return
            }
            setSparkplugReportedRedcon(nextRedcon)
          },
          onSparkplugBatteryMvChange: (nextBatteryMv) => {
            if (!cancelled) {
              setSparkplugReportedBatteryMv(nextBatteryMv)
            }
          },
          onRobotStateChange: (nextRobotState) => {
            if (!cancelled) {
              setRobotState(nextRobotState)
            }
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
    const nextBoardVideoLastError = normalizeRuntimeMessage(robotVideoLastError)
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
      dedupeKey: `board-video-mcp:${nextNotificationMessage}`,
    })
  }, [enqueueNotification, robotVideoLastError])

  useEffect(() => {
    if (reportedRedcon === 1) {
      return
    }
    if (isBotPanelOpen) {
      setIsBotPanelOpen(false)
    }
    if (isBoardVideoExpanded) {
      setIsBoardVideoExpanded(false)
    }
  }, [isBoardVideoExpanded, isBotPanelOpen, reportedRedcon])

  useEffect(() => {
    if (!isShadowConnected && isBoardVideoExpanded) {
      setIsBoardVideoExpanded(false)
    }
  }, [isBoardVideoExpanded, isShadowConnected])

  const requestRobotState = useEffectEvent(async (): Promise<void> => {
    const shadowSession = shadowSessionRef.current
    if (!shadowSession || !shadowSession.isConnected()) {
      return
    }

    try {
      await shadowSession.requestRobotState()
    } catch (caughtError) {
      enqueueRuntimeError(
        caughtError instanceof Error ? caughtError.message : 'Unable to read robot state',
        'robot-state',
      )
    }
  })

  useEffect(() => {
    if (!isBoardVideoExpanded || !canUseBoardVideo || !isShadowConnected) {
      return
    }

    void requestRobotState()
    if (isRobotMotionActive || isRobotControlActive) {
      return
    }

    const intervalId = window.setInterval(() => {
      void requestRobotState()
    }, robotStatePollIntervalMs)

    return () => {
      window.clearInterval(intervalId)
    }
  }, [
    canUseBoardVideo,
    isBoardVideoExpanded,
    isRobotControlActive,
    isRobotMotionActive,
    isShadowConnected,
    requestRobotState,
  ])

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

  const publishRedconCommand = async (redcon: 1 | 2 | 3 | 4): Promise<boolean> => {
    const commandSequence = redconCommandSequenceRef.current + 1
    redconCommandSequenceRef.current = commandSequence
    setIsUpdatingShadow(true)

    try {
      const shadowSession = getShadowSession()
      await publishSparkplugRedconCommandWithAck(shadowSession, redcon)
      if (redconCommandSequenceRef.current === commandSequence) {
        appendSessionLogEntry({
          tone: 'neutral',
          message: `Sparkplug DCMD.redcon -> ${redcon}`,
          dedupeKey: `sparkplug-redcon:${redcon}`,
        })
      }
      return true
    } catch (caughtError) {
      if (redconCommandSequenceRef.current === commandSequence) {
        enqueueRuntimeError(
          caughtError instanceof Error ? caughtError.message : 'Unable to publish Sparkplug command',
          'sparkplug-redcon',
        )
      }
      return false
    } finally {
      if (redconCommandSequenceRef.current === commandSequence) {
        setIsUpdatingShadow(false)
      }
    }
  }

  const handleRedconSelect = async (redcon: 1 | 2 | 3 | 4): Promise<void> => {
    if (redcon === 4) {
      if (isRedconSleepCommandDisabled) {
        return
      }
      const isWakeTargetPending = desiredRedcon !== null && desiredRedcon !== 4
      if (reportedRedcon === 4 && !isWakeTargetPending) {
        return
      }
      await publishRedconCommand(4)
      return
    }
    if (isRedconCommandDisabled || reportedRedcon === redcon) {
      return
    }
    await publishRedconCommand(redcon)
  }

  const handleSignOff = (): void => {
    shadowSessionRef.current?.close()
    shadowSessionRef.current = null
    setShadowConnectionState('idle')
    signOut()
  }

  const handleToggleBotPanel = (): void => {
    if (!canUseBoardVideo) {
      return
    }
    setIsBotPanelOpen((currentValue) => {
      const nextValue = !currentValue
      setIsBoardVideoExpanded(nextValue)
      return nextValue
    })
  }

  const handleToggleTownPanel = (): void => {
    setIsTownPanelOpen((currentValue) => !currentValue)
  }

  const handleToggleRigPanel = (): void => {
    setIsRigPanelOpen((currentValue) => !currentValue)
  }

  const renderInlineRouteLink = (
    path: string,
    label: string,
    className = 'navigation-link',
  ): ReactElement => (
    <a
      href={path}
      className={className}
      onClick={(event) => {
        handleRouteLinkClick(event, path)
      }}
    >
      {label}
    </a>
  )

  const renderCatalogCardLink = (
    path: string,
    eyebrow: string,
    title: string,
    description?: string,
    titleClassName = '',
  ): ReactElement => (
    <a
      href={path}
      className="catalog-card-link"
      onClick={(event) => {
        handleRouteLinkClick(event, path)
      }}
    >
      <span className="catalog-card-link-eyebrow">{eyebrow}</span>
      <span className={`catalog-card-link-title ${titleClassName}`.trim()}>{title}</span>
      {description ? <span className="catalog-card-link-description">{description}</span> : null}
    </a>
  )

  const renderNavigationPath = (): ReactElement | null => {
    if (route.kind === 'root' || route.kind === 'not_found') {
      return null
    }

    const crumbs: ReactElement[] = [renderInlineRouteLink(buildTownPath(route.town), route.town)]
    if (route.kind === 'town') {
      crumbs[0] = (
        <span key={`crumb-town:${route.town}`} className="navigation-current-link">
          {route.town}
        </span>
      )
    } else if (route.kind === 'rig') {
      crumbs.push(<span key={`crumb-rig:${route.rig}`}>{route.rig}</span>)
    } else if (route.kind === 'device' || route.kind === 'device_video') {
      crumbs.push(renderInlineRouteLink(buildRigPath(route.town, route.rig), route.rig))
      crumbs.push(
        renderInlineRouteLink(
          buildDevicePath(route.town, route.rig, route.device),
          selectedDeviceLabel ?? route.device,
        ),
      )
    }
    if (route.kind === 'device_video') {
      crumbs.push(<span key={`crumb-video:${route.device}`}>video</span>)
    }
    if (route.kind === 'rig') {
      crumbs[crumbs.length - 1] = (
        <span key={`crumb-rig:${route.rig}`} className="navigation-current-link">
          {route.rig}
        </span>
      )
    }
    if (route.kind === 'device' || route.kind === 'device_video') {
      crumbs[crumbs.length - 1] = (
        <span
          key={`crumb-device:${route.device}:${route.kind}`}
          className="navigation-current-link"
        >
          {route.kind === 'device' ? selectedDeviceLabel ?? route.device : 'video'}
        </span>
      )
    }

    return (
      <nav className="navigation-path" aria-label="Breadcrumb">
        {crumbs.map((crumb, index) => (
          <span key={`crumb:${index}`} className="navigation-path-segment">
            {index > 0 ? <span className="navigation-path-separator">→</span> : null}
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
                <div className="status-auth-lockup">
                  <img src={txingLogoUrl} alt="txing logo" className="status-auth-logo" />
                  <div className="status-name status-txing-name status-auth-name">TXING</div>
                </div>
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

  const lastShadowUpdateLabel = formatShadowUpdateTime(lastShadowUpdateAtMs)
  const lastShadowUpdateTitle =
    lastShadowUpdateAtMs === null
      ? 'Last shadow update unavailable'
      : `Last shadow update ${new Date(lastShadowUpdateAtMs).toLocaleString()}`

  const isDetailsPanelOpen =
    route.kind === 'town'
      ? isTownPanelOpen
      : route.kind === 'rig'
        ? isRigPanelOpen
        : route.kind === 'device'
          ? isBotPanelOpen
          : false
  const isDetailsPanelToggleEnabled =
    route.kind === 'town' || route.kind === 'rig'
      ? true
      : route.kind === 'device'
        ? canUseBoardVideo
        : false
  const detailsToggleAriaLabel =
    route.kind === 'town'
      ? isTownPanelOpen
        ? 'Hide rig details'
        : 'Show rig details'
      : route.kind === 'rig'
        ? isRigPanelOpen
          ? 'Hide device details'
          : 'Show device details'
        : route.kind === 'device'
          ? isBotPanelOpen
            ? 'Hide bot device details'
            : 'Show bot device details'
          : null
  const detailsToggleTitle =
    route.kind === 'town'
      ? isTownPanelOpen
        ? 'Hide rig details'
        : 'Show rig details'
      : route.kind === 'rig'
        ? isRigPanelOpen
          ? 'Hide device details'
          : 'Show device details'
        : route.kind === 'device'
          ? canUseBoardVideo
            ? isBotPanelOpen
              ? 'Hide bot device details'
              : 'Show bot device details'
            : 'Bot device details become available at REDCON 1'
          : null

  const navigationPanel =
    route.kind !== 'root' ? (
      <section className="card navigation-panel" aria-label="Navigation panel">
        <div className="navigation-panel-main">
          <div className="navigation-panel-header">
            <a
              href={appHomePath}
              className="navigation-logo-link"
              aria-label="Open town browser home"
              onClick={(event) => {
                handleRouteLinkClick(event, appHomePath)
              }}
            >
              <img
                src={txingLogoUrl}
                alt="txing logo"
                className="navigation-logo"
              />
            </a>
            <span className="navigation-panel-brand">TXING</span>
            <div className="navigation-panel-route">
              {renderNavigationPath() ?? (
                <span className="navigation-current-link">route not found</span>
              )}
            </div>
          </div>
        </div>
        <div className="navigation-panel-actions">
          {route.kind === 'town' ||
          route.kind === 'rig' ||
          route.kind === 'device' ||
          route.kind === 'device_video' ? (
            <SparkplugPanel
              routeKind={route.kind}
              botRedcon={reportedRedcon}
              desiredRedcon={desiredRedcon}
              detailsToggleAriaLabel={detailsToggleAriaLabel}
              detailsToggleTitle={detailsToggleTitle}
              isDetailsPanelOpen={isDetailsPanelOpen}
              isDetailsPanelToggleEnabled={isDetailsPanelToggleEnabled}
              isRedconCommandDisabled={isRedconCommandDisabled}
              isRedconSleepCommandDisabled={isRedconSleepCommandDisabled}
              onRedconSelect={(redcon) => {
                void handleRedconSelect(redcon)
              }}
              onToggleDetailsPanel={() => {
                if (route.kind === 'town') {
                  handleToggleTownPanel()
                  return
                }
                if (route.kind === 'rig') {
                  handleToggleRigPanel()
                  return
                }
                if (route.kind === 'device') {
                  handleToggleBotPanel()
                }
              }}
            />
          ) : null}
          <NavigationUserMenu
            authUser={authUser}
            canLoadShadow={canLoadShadow}
            isDebugEnabled={isDebugEnabled}
            isSessionLogVisible={isSessionLogVisible}
            onLoadShadow={() => {
              void loadShadow()
            }}
            onSignOff={handleSignOff}
            onToggleDebug={() => {
              setIsDebugEnabled((currentValue) => !currentValue)
            }}
            onToggleSessionLog={() => {
              setIsSessionLogVisible((currentValue) => !currentValue)
            }}
          />
        </div>
      </section>
    ) : null

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
        <p>{renderInlineRouteLink(configuredTownPath, 'Open the configured town')}</p>
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
        <p>{renderInlineRouteLink(configuredTownPath, `Open ${configuredTown}`)}</p>
      </section>
    )
  } else if (route.kind === 'town') {
    content = isTownPanelOpen ? (
      <section className="catalog-grid-shell">
        {rigCatalog.status === 'loading' ? <p>Loading rigs...</p> : null}
        {rigCatalog.status === 'error' ? <p className="error">{rigCatalog.error}</p> : null}
        {rigCatalog.status === 'ready' && rigCatalog.rigs.length === 0 ? (
          <p>No rigs are currently registered for this town.</p>
        ) : null}
        {rigCatalog.rigs.length > 0 ? (
          <ul className="catalog-list catalog-grid" aria-label={`Rigs in ${route.town}`}>
            {rigCatalog.rigs.map((rig) => (
              <li key={rig.rigName} className="catalog-list-item">
                {renderCatalogCardLink(
                  buildRigPath(route.town, rig.rigName),
                  'Rig',
                  rig.rigName.toUpperCase(),
                  getCatalogDescription(rig.description, 'No rig description available.'),
                  'catalog-card-link-title-caps',
                )}
              </li>
            ))}
          </ul>
        ) : null}
      </section>
    ) : (
      <></>
    )
  } else if (route.kind === 'rig') {
    content = isRigPanelOpen ? (
      <section className="catalog-grid-shell">
        {deviceCatalog.status === 'loading' ? <p>Loading devices...</p> : null}
        {deviceCatalog.status === 'not_found' ? <p className="error">{deviceCatalog.error}</p> : null}
        {deviceCatalog.status === 'error' ? <p className="error">{deviceCatalog.error}</p> : null}
        {deviceCatalog.status === 'ready' && deviceCatalog.devices.length === 0 ? (
          <p>No devices are currently assigned to this rig.</p>
        ) : null}
        {deviceCatalog.devices.length > 0 ? (
          <ul className="catalog-list catalog-grid" aria-label={`Devices in ${route.rig}`}>
            {deviceCatalog.devices.map((device) => (
              <li key={device.thingName} className="catalog-list-item">
                {renderCatalogCardLink(
                  buildDevicePath(route.town, route.rig, device.thingName),
                  'Device',
                  getCatalogDeviceLabel(device),
                )}
              </li>
            ))}
          </ul>
        ) : null}
      </section>
    ) : (
      <></>
    )
  } else if (selectedDeviceRoute && deviceCatalog.status === 'loading') {
    content = (
      <section className="card catalog-card">
        <h1>Loading device</h1>
        <p>Validating device membership for rig {selectedDeviceRoute.rig}...</p>
      </section>
    )
  } else if (
    selectedDeviceRoute &&
    (deviceCatalog.status === 'not_found' ||
      deviceCatalog.status === 'error' ||
      (deviceCatalog.status === 'ready' &&
        !deviceCatalog.devices.some((device) => device.thingName === selectedDeviceRoute.device)))
  ) {
    content = (
      <section className="card catalog-card">
        <h1>Device not found</h1>
        <p>
          {deviceCatalog.status === 'error'
            ? deviceCatalog.error
            : `Device '${selectedDeviceRoute.device}' is not assigned to rig '${selectedDeviceRoute.rig}'.`}
        </p>
        <p>
          {renderInlineRouteLink(
            buildRigPath(selectedDeviceRoute.town, selectedDeviceRoute.rig),
            `Open ${selectedDeviceRoute.rig}`,
          )}
        </p>
      </section>
    )
  } else if (route.kind === 'device_video' && selectedDeviceRoute) {
    content = (
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
    )
  } else if (route.kind === 'device' && selectedDeviceRoute && isBotPanelOpen) {
    content = (
      <TxingPanel
        isBoardVideoExpanded={isBoardVideoExpanded}
        isDebugEnabled={isDebugEnabled}
        reportedBatteryMv={primaryReportedBatteryMv}
        reportedBoardLeftTrackSpeed={reportedBoardLeftTrackSpeed}
        reportedBoardOnline={reportedBoardOnline}
        reportedBoardRightTrackSpeed={reportedBoardRightTrackSpeed}
        reportedMcuOnline={reportedMcuOnline}
        videoChannelName={buildBoardVideoChannelName(selectedDeviceRoute.device)}
        resolveIdToken={resolveSessionIdToken}
        onBoardVideoRuntimeError={(message) => {
          enqueueRuntimeError(message, 'board-video-viewer')
        }}
      />
    )
  } else if (route.kind === 'device' && selectedDeviceRoute) {
    content = <></>
  } else {
    content = (
      <section className="card catalog-card">
        <h1>Device Shadow Admin</h1>
        <p>Waiting for a valid route selection.</p>
        <p>{renderInlineRouteLink(configuredTownPath, `Open ${configuredTown}`)}</p>
      </section>
    )
  }

  return (
    <main className="page page-signed-in">
      {navigationPanel}
      {content}

      <NotificationTray
        notifications={notifications}
        onDismiss={(notificationId) => {
          dismissNotification(notificationId)
        }}
      />

      {isSessionLogVisible && <NotificationLogPanel notificationLog={notificationLog} />}

      {isDebugEnabled && activeSessionRoute !== null && (
        <DebugPanel
          lastShadowUpdateLabel={lastShadowUpdateLabel}
          lastShadowUpdateTitle={lastShadowUpdateTitle}
          reportedBoardPower={reportedBoardPower}
          reportedMcuPower={reportedMcuPower}
          shadowJson={shadowJson}
        />
      )}
    </main>
  )
}

export default App
