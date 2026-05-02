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
import { getDeviceWebAdapter } from './device-registry'
import {
  describeThingMetadata,
  formatThingShadowReadError,
  getThingNamedShadow,
  isResourceNotFoundError,
  listRigDevices,
  listTownRigs,
  type DeviceCatalogEntry,
  type RigCatalogEntry,
  type ThingMetadata,
} from './catalog-api'
import { CmdVelTeleopController } from './cmd-vel-teleop'
import type { Twist } from './cmd-vel'
import { appConfig } from './config'
import DebugPanel from './DebugPanel'
import {
  formatCatalogDetailLine,
  getRouteDetailPanelOpenState,
  shouldRenderRouteCatalogPanel,
} from './level-detail-panel'
import { shouldSuppressRobotStateTeardownError } from './mcp-errors'
import type { McpTransportKind } from './mcp-descriptor'
import { getMcpSteadyMotionHeartbeatIntervalMs } from './mcp-lease'
import NavigationUserMenu from './NavigationUserMenu'
import NotificationLogPanel from './NotificationLogPanel'
import NotificationTray from './NotificationTray'
import type { RobotState, ShadowConnectionState, ShadowSession } from './shadow-api'
import type { ShadowName } from './shadow-protocol'
import {
  publishDirectSparkplugRedconCommand,
  resolveThingSparkplugRedconCommandTarget,
} from './sparkplug-command'
import SparkplugPanel from './SparkplugPanel'
import {
  extractIsSparkplugDeviceUnavailable,
  extractReportedRedcon,
  hasReachedTargetRedcon,
  shouldClearPendingTargetRedcon,
} from './sparkplug-model'

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
type ShadowTarget = {
  routeKind: 'town' | 'rig' | 'device' | 'device_video'
  thingName: string
  capabilities: readonly ShadowName[]
  sparkplugGroupId: string
  sparkplugEdgeNodeId: string
}
type ShadowTargetState = {
  status: 'idle' | 'loading' | 'ready' | 'error'
  target: ShadowTarget | null
  error: string
}
type RouteHeaderState = {
  status: 'idle' | 'loading' | 'ready' | 'error'
  metadata: ThingMetadata | null
  sparkplugShadow: unknown | null
  shadowWarning: string
  error: string
}

const formatJson = (value: unknown): string => JSON.stringify(value, null, 2)
const defaultMcpLeaseTtlMs = 5_000
const robotStatePollIntervalMs = 5_000
const routeSparkplugPollIntervalMs = 2_000
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

const emptyShadowTargetState = (): ShadowTargetState => ({
  status: 'idle',
  target: null,
  error: '',
})

const emptyRouteHeaderState = (): RouteHeaderState => ({
  status: 'idle',
  metadata: null,
  sparkplugShadow: null,
  shadowWarning: '',
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

const sleep = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms))

const getCatalogDeviceLabel = (device: DeviceCatalogEntry | null | undefined): string =>
  device?.name?.trim() ? device.name.trim() : 'Unnamed device'

function App({ initialAuthError = '' }: AppProps) {
  const [route, setRoute] = useState<AppRoute>(getInitialRoute)
  const [status, setStatus] = useState<SessionStatus>('loading')
  const [authUser, setAuthUser] = useState<AuthUser | null>(null)
  const [shadowJson, setShadowJson] = useState<string>('{}')
  const [robotState, setRobotState] = useState<RobotState | null>(null)
  const [mcpTransport, setMcpTransport] = useState<McpTransportKind | null>(null)
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
  const [routeHeaderState, setRouteHeaderState] =
    useState<RouteHeaderState>(emptyRouteHeaderState)
  const [rigCatalog, setRigCatalog] = useState<RigCatalogState>(emptyRigCatalogState)
  const [deviceCatalog, setDeviceCatalog] = useState<DeviceCatalogState>(emptyDeviceCatalogState)
  const [shadowTargetState, setShadowTargetState] = useState<ShadowTargetState>(emptyShadowTargetState)
  const [shadowBootstrapError, setShadowBootstrapError] = useState('')
  const [pendingTargetRedcon, setPendingTargetRedcon] = useState<1 | 2 | 3 | 4 | null>(null)
  const shadowSessionRef = useRef<ShadowSession | null>(null)
  const redconCommandSequenceRef = useRef(0)
  const nextNotificationIdRef = useRef(0)
  const nextNotificationLogIdRef = useRef(0)
  const lastBoardVideoErrorRef = useRef<string | null>(null)
  const hasObservedBoardVideoLastErrorRef = useRef(false)
  const previousReportedRedconRef = useRef<number | null>(null)
  const hasReceivedShadowSnapshotRef = useRef(false)

  const hasConfigErrors = appConfig.errors.length > 0
  const configuredTownThingName = appConfig.townThingName
  const configuredTownLabel = appConfig.sparkplugGroupId || configuredTownThingName
  const configuredTownPath = buildTownPath(configuredTownThingName)
  const currentRouteTown = useMemo(() => describeRouteTown(route), [route])
  const currentNotificationObjectId = useMemo(() => {
    if (route.kind === 'town') {
      return route.town
    }
    if (route.kind === 'rig') {
      return route.rig
    }
    if (route.kind === 'device' || route.kind === 'device_video') {
      return route.device
    }
    return null
  }, [route])
  const hasUnsupportedTown =
    currentRouteTown !== null && currentRouteTown !== configuredTownThingName
  const currentRouteThingName =
    route.kind === 'town'
      ? route.town
      : route.kind === 'rig'
        ? route.rig
        : route.kind === 'device' || route.kind === 'device_video'
          ? route.device
          : null
  const selectedDeviceRoute = useMemo<DeviceRoute | null>(() => {
    if (!hasUnsupportedTown && (route.kind === 'device' || route.kind === 'device_video')) {
      return route
    }
    return null
  }, [hasUnsupportedTown, route])
  const routeHeaderMetadata =
    routeHeaderState.status === 'ready' ? routeHeaderState.metadata : null
  const routeSparkplugShadow =
    routeHeaderState.status === 'ready' ? routeHeaderState.sparkplugShadow : null
  const routeHeaderShadowWarning =
    routeHeaderState.status === 'ready' ? routeHeaderState.shadowWarning : ''
  const currentThingTypeName = routeHeaderMetadata?.thingTypeName ?? null
  const currentThingKind = routeHeaderMetadata?.kind ?? null
  const currentTownCatalogName =
    route.kind === 'town'
      ? routeHeaderMetadata?.name ?? null
      : route.kind === 'rig' || route.kind === 'device' || route.kind === 'device_video'
        ? routeHeaderMetadata?.townName ?? null
        : null
  const currentRigCatalogThingName = route.kind === 'rig' ? route.rig : null
  const selectedDeviceEntry = useMemo(() => {
    if (!selectedDeviceRoute || deviceCatalog.status !== 'ready') {
      return null
    }

    return (
      deviceCatalog.devices.find((device) => device.thingName === selectedDeviceRoute.device) ?? null
    )
  }, [deviceCatalog.devices, deviceCatalog.status, selectedDeviceRoute])
  const selectedDeviceLabel = useMemo(() => {
    if (route.kind === 'device' || route.kind === 'device_video') {
      return routeHeaderMetadata?.name?.trim() || null
    }
    if (!selectedDeviceRoute) {
      return null
    }
    return selectedDeviceEntry ? getCatalogDeviceLabel(selectedDeviceEntry) : 'Device'
  }, [route.kind, routeHeaderMetadata?.name, selectedDeviceEntry, selectedDeviceRoute])
  const navigationTownLabel =
    route.kind === 'town'
      ? routeHeaderMetadata?.name ?? route.town
      : route.kind === 'rig'
        ? routeHeaderMetadata?.townName ?? route.town
        : route.kind === 'device' || route.kind === 'device_video'
          ? routeHeaderMetadata?.townName ?? route.town
          : null
  const navigationRigLabel =
    route.kind === 'rig'
      ? routeHeaderMetadata?.name ?? route.rig
      : route.kind === 'device' || route.kind === 'device_video'
        ? routeHeaderMetadata?.rigName ?? route.rig
        : null
  const isNavigationReady =
    route.kind !== 'root' &&
    route.kind !== 'not_found' &&
    !hasUnsupportedTown &&
    routeHeaderState.status === 'ready'
  const hasShadowBootstrapFailure = shadowBootstrapError !== '' && lastShadowUpdateAtMs === null

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
  const displayShadowDocument = lastShadowUpdateAtMs !== null ? shadowDocument : routeSparkplugShadow
  const currentDeviceAdapter = useMemo(
    () => getDeviceWebAdapter(currentThingTypeName),
    [currentThingTypeName],
  )
  const isDeviceThingType = currentThingKind === 'deviceType'
  const deviceTelemetry = useMemo(
    () => currentDeviceAdapter?.extractTelemetry(displayShadowDocument) ?? null,
    [currentDeviceAdapter, displayShadowDocument],
  )

  const reportedMcuPower = deviceTelemetry?.reportedMcuPower ?? null
  const reportedMcuOnline = deviceTelemetry?.reportedMcuOnline ?? null
  const primaryReportedBatteryMv = deviceTelemetry?.reportedBatteryMv ?? null
  const reportedBoardPower = deviceTelemetry?.reportedBoardPower ?? null
  const reportedBoardOnline = deviceTelemetry?.reportedBoardOnline ?? null
  const shadowReportedRedcon = useMemo(
    () => extractReportedRedcon(displayShadowDocument),
    [displayShadowDocument],
  )
  const isSparkplugDeviceUnavailable = useMemo(
    () => extractIsSparkplugDeviceUnavailable(displayShadowDocument),
    [displayShadowDocument],
  )
  const reportedRedcon = shadowReportedRedcon
  const currentThingSparkplugCommandTarget = useMemo(
    () => resolveThingSparkplugRedconCommandTarget(routeHeaderMetadata),
    [routeHeaderMetadata],
  )
  const isSparkplugDeviceCommandAvailable =
    currentThingSparkplugCommandTarget !== null && !isSparkplugDeviceUnavailable
  const shouldRenderCatalogPanel = shouldRenderRouteCatalogPanel({
    thingKind: currentThingKind,
    reportedRedcon,
  })

  const isShadowConnected = shadowConnectionState === 'connected'
  const isRedconCommandPending =
    pendingTargetRedcon !== null &&
    !isSparkplugDeviceUnavailable &&
    (reportedRedcon === null ||
      (pendingTargetRedcon === 4
        ? reportedRedcon !== 4
        : reportedRedcon > pendingTargetRedcon))
  const isRedconCommandDisabled =
    !isSparkplugDeviceCommandAvailable || isUpdatingShadow || isRedconCommandPending
  const isRedconSleepCommandDisabled =
    !isSparkplugDeviceCommandAvailable || isUpdatingShadow
  const canLoadShadow = !isLoadingShadow && isShadowConnected
  const canUseBoardVideo = currentDeviceAdapter?.canUseBoardVideo(reportedRedcon) ?? false
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
    routeHeaderMetadata !== null &&
    isDeviceThingType &&
    routeHeaderMetadata.townId !== null &&
    routeHeaderMetadata.rigId !== null &&
    (route.kind !== 'device_video' ||
      (currentDeviceAdapter !== null && routeHeaderMetadata.capabilities.includes('video')))
  const activeShadowTarget = shadowTargetState.status === 'ready' ? shadowTargetState.target : null

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
      objectId: currentNotificationObjectId,
    })
  }, [currentNotificationObjectId, enqueueNotification])

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

  const refreshRouteSparkplugShadow = useCallback(
    async (thingName: string): Promise<unknown | null> => {
      try {
        const nextShadow = await getThingNamedShadow(resolveSessionIdToken, thingName, 'sparkplug')
        setRouteHeaderState((currentState) => {
          if (
            currentState.status !== 'ready' ||
            currentState.metadata?.thingName !== thingName
          ) {
            return currentState
          }
          return {
            ...currentState,
            sparkplugShadow: nextShadow,
            shadowWarning: '',
          }
        })
        return nextShadow
      } catch (caughtError) {
        const nextWarning = formatThingShadowReadError(caughtError, thingName, 'sparkplug')
        setRouteHeaderState((currentState) => {
          if (
            currentState.status !== 'ready' ||
            currentState.metadata?.thingName !== thingName
          ) {
            return currentState
          }
          return {
            ...currentState,
            shadowWarning: nextWarning,
          }
        })
        return null
      }
    },
    [resolveSessionIdToken],
  )

  const waitForRouteSparkplugRedcon = useCallback(
    async (
      thingName: string,
      targetRedcon: 1 | 2 | 3 | 4,
      commandSequence: number,
    ): Promise<void> => {
      while (true) {
        if (redconCommandSequenceRef.current !== commandSequence) {
          return
        }

        const nextShadow = await refreshRouteSparkplugShadow(thingName)
        if (extractIsSparkplugDeviceUnavailable(nextShadow)) {
          if (redconCommandSequenceRef.current === commandSequence) {
            setPendingTargetRedcon(null)
          }
          return
        }
        if (
          hasReachedTargetRedcon({
            targetRedcon,
            reportedRedcon: extractReportedRedcon(nextShadow),
          })
        ) {
          if (redconCommandSequenceRef.current === commandSequence) {
            setPendingTargetRedcon(null)
          }
          return
        }

        await sleep(1_000)
      }
    },
    [refreshRouteSparkplugShadow],
  )

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
    if (
      shouldClearPendingTargetRedcon({
        pendingTargetRedcon,
        reportedRedcon,
        isSparkplugDeviceUnavailable,
      })
    ) {
      setPendingTargetRedcon(null)
    }
  }, [isSparkplugDeviceUnavailable, pendingTargetRedcon, reportedRedcon])

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
      !currentRouteThingName ||
      hasUnsupportedTown
    ) {
      setRouteHeaderState(emptyRouteHeaderState())
      return
    }

    let cancelled = false
    setRouteHeaderState({
      status: 'loading',
      metadata: null,
      sparkplugShadow: null,
      shadowWarning: '',
      error: '',
    })

    const loadRouteHeader = async (): Promise<void> => {
      try {
        const metadata = await describeThingMetadata(resolveSessionIdToken, currentRouteThingName)
        if (cancelled) {
          return
        }
        if (route.kind === 'town' && metadata.kind !== 'townType') {
          throw new Error(`Thing '${currentRouteThingName}' is not a town.`)
        }
        if (route.kind === 'rig' && metadata.kind !== 'rigType') {
          throw new Error(`Thing '${currentRouteThingName}' is not a rig.`)
        }
        if (
          (route.kind === 'device' || route.kind === 'device_video') &&
          metadata.kind !== 'deviceType'
        ) {
          throw new Error(`Thing '${currentRouteThingName}' is not a device.`)
        }

        let sparkplugShadow: unknown | null = null
        let shadowWarning = ''
        try {
          sparkplugShadow = await getThingNamedShadow(
            resolveSessionIdToken,
            currentRouteThingName,
            'sparkplug',
          )
        } catch (caughtShadowError) {
          shadowWarning = formatThingShadowReadError(
            caughtShadowError,
            currentRouteThingName,
            'sparkplug',
          )
        }
        if (cancelled) {
          return
        }

        setRouteHeaderState({
          status: 'ready',
          metadata,
          sparkplugShadow,
          shadowWarning,
          error: '',
        })
      } catch (caughtError) {
        if (cancelled) {
          return
        }
        setRouteHeaderState({
          status: 'error',
          metadata: null,
          sparkplugShadow: null,
          shadowWarning: '',
          error:
            caughtError instanceof Error
              ? caughtError.message
              : 'Unable to resolve route header state',
        })
      }
    }

    void loadRouteHeader()

    return () => {
      cancelled = true
    }
  }, [
    adminEmailMismatch,
    currentRouteThingName,
    hasUnsupportedTown,
    resolveSessionIdToken,
    route.kind,
    status,
  ])

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
    if (routeHeaderState.status === 'error') {
      setRigCatalog({
        status: 'error',
        rigs: [],
        error: routeHeaderState.error,
      })
      return
    }
    if (routeHeaderState.status !== 'ready' || !currentTownCatalogName) {
      setRigCatalog({
        status: 'loading',
        rigs: [],
        error: '',
      })
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
        const rigs = await listTownRigs(resolveSessionIdToken, currentTownCatalogName)
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
  }, [
    adminEmailMismatch,
    hasUnsupportedTown,
    currentTownCatalogName,
    resolveSessionIdToken,
    route.kind,
    routeHeaderState.error,
    routeHeaderState.status,
    status,
  ])

  useEffect(() => {
    if (
      status !== 'signed_in' ||
      adminEmailMismatch ||
      route.kind !== 'rig' ||
      !currentRigCatalogThingName ||
      hasUnsupportedTown
    ) {
      setDeviceCatalog(emptyDeviceCatalogState())
      return
    }
    if (routeHeaderState.status === 'error') {
      setDeviceCatalog({
        status: 'error',
        devices: [],
        error: routeHeaderState.error,
      })
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
        const devices = await listRigDevices(resolveSessionIdToken, currentRigCatalogThingName)
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
            error: `Rig '${navigationRigLabel ?? currentRigCatalogThingName}' was not found.`,
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
  }, [
    adminEmailMismatch,
    hasUnsupportedTown,
    currentRigCatalogThingName,
    navigationRigLabel,
    resolveSessionIdToken,
    route.kind,
    routeHeaderState.error,
    routeHeaderState.status,
    status,
  ])

  useEffect(() => {
    if (
      status !== 'signed_in' ||
      adminEmailMismatch ||
      hasUnsupportedTown ||
      !currentRouteThingName ||
      routeHeaderState.status !== 'ready'
    ) {
      return
    }
    if (route.kind !== 'town' && route.kind !== 'rig') {
      return
    }

    let cancelled = false
    const intervalId = window.setInterval(() => {
      if (!cancelled) {
        void refreshRouteSparkplugShadow(currentRouteThingName)
      }
    }, routeSparkplugPollIntervalMs)

    return () => {
      cancelled = true
      window.clearInterval(intervalId)
    }
  }, [
    adminEmailMismatch,
    currentRouteThingName,
    hasUnsupportedTown,
    refreshRouteSparkplugShadow,
    route.kind,
    routeHeaderState.status,
    status,
  ])

  useEffect(() => {
    if (status !== 'signed_in' || adminEmailMismatch || hasUnsupportedTown) {
      setShadowTargetState(emptyShadowTargetState())
      return
    }

    if (
      route.kind === 'root' ||
      route.kind === 'not_found' ||
      route.kind === 'town' ||
      route.kind === 'rig'
    ) {
      setShadowTargetState(emptyShadowTargetState())
      return
    }
    if (routeHeaderState.status === 'error') {
      setShadowTargetState({
        status: 'error',
        target: null,
        error: routeHeaderState.error,
      })
      return
    }
    if (routeHeaderState.status !== 'ready' || !routeHeaderMetadata) {
      setShadowTargetState({
        status: 'loading',
        target: null,
        error: '',
      })
      return
    }
    if (
      !selectedDeviceRoute ||
      !isSelectedDeviceValid ||
      !routeHeaderMetadata.townId ||
      !routeHeaderMetadata.rigId
    ) {
      setShadowTargetState(emptyShadowTargetState())
      return
    }

    setShadowTargetState({
      status: 'ready',
      target: {
        routeKind: route.kind,
        thingName: selectedDeviceRoute.device,
        capabilities: routeHeaderMetadata.capabilities,
        sparkplugGroupId: routeHeaderMetadata.townId,
        sparkplugEdgeNodeId: routeHeaderMetadata.rigId,
      },
      error: '',
    })
  }, [
    adminEmailMismatch,
    hasUnsupportedTown,
    isSelectedDeviceValid,
    route,
    routeHeaderMetadata,
    routeHeaderState.error,
    routeHeaderState.status,
    selectedDeviceRoute,
    status,
  ])

  useEffect(() => {
    const nextRouteDetailPanelOpenState = getRouteDetailPanelOpenState(route)
    setIsTownPanelOpen(nextRouteDetailPanelOpenState.isTownPanelOpen)
    setIsRigPanelOpen(nextRouteDetailPanelOpenState.isRigPanelOpen)
  }, [route])

  useEffect(() => {
    if (!activeShadowTarget) {
      redconCommandSequenceRef.current += 1
      shadowSessionRef.current?.close()
      shadowSessionRef.current = null
      hasReceivedShadowSnapshotRef.current = false
      previousReportedRedconRef.current = null
      setShadowBootstrapError('')
      setShadowConnectionState('idle')
      setIsLoadingShadow(false)
      setIsUpdatingShadow(false)
      setLastShadowUpdateAtMs(null)
      setShadowJson('{}')
      setPendingTargetRedcon(null)
      setRobotState(null)
      setIsBotPanelOpen(false)
      setIsBoardVideoExpanded(false)
      lastBoardVideoErrorRef.current = null
      hasObservedBoardVideoLastErrorRef.current = false
      return
    }

    let cancelled = false
    let shadowSession: ShadowSession | null = null
    redconCommandSequenceRef.current += 1
    hasReceivedShadowSnapshotRef.current = false
    previousReportedRedconRef.current = null
    setShadowJson('{}')
    setShadowBootstrapError('')
    setPendingTargetRedcon(null)
    setRobotState(null)
    setMcpTransport(null)
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
          thingName: activeShadowTarget.thingName,
          awsRegion: appConfig.awsRegion,
          sparkplugGroupId: activeShadowTarget.sparkplugGroupId,
          sparkplugEdgeNodeId: activeShadowTarget.sparkplugEdgeNodeId,
          capabilities: activeShadowTarget.capabilities,
          resolveIdToken: resolveSessionIdToken,
          onShadowDocument: (shadow) => {
            if (cancelled) {
              return
            }
            hasReceivedShadowSnapshotRef.current = true
            setShadowBootstrapError('')
            applyShadowSnapshot(shadow)
            setIsLoadingShadow(false)
          },
          onRobotStateChange: (nextRobotState) => {
            if (!cancelled) {
              setRobotState(nextRobotState)
            }
          },
          onMcpTransportChange: (nextTransport) => {
            if (!cancelled) {
              setMcpTransport(nextTransport)
            }
          },
          onConnectionStateChange: (nextState) => {
            if (!cancelled) {
              setShadowConnectionState(nextState)
            }
          },
          onError: (message) => {
            if (!cancelled) {
              if (!hasReceivedShadowSnapshotRef.current) {
                setShadowBootstrapError(message)
              }
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
        const message =
          caughtError instanceof Error ? caughtError.message : 'Unable to open Thing Shadow session'
        setIsLoadingShadow(false)
        setShadowConnectionState('error')
        setShadowBootstrapError(message)
        enqueueRuntimeError(message, 'shadow-session')
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
  }, [
    activeShadowTarget,
    applyShadowSnapshot,
    enqueueRuntimeError,
    resolveSessionIdToken,
  ])

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

  const callDeviceMcpTool = useCallback(
    async (name: string, args: Record<string, unknown> = {}): Promise<unknown> => {
      const shadowSession = shadowSessionRef.current
      if (!shadowSession || !isShadowConnected) {
        throw new Error('Shadow connection is not ready')
      }
      return shadowSession.callMcpTool(name, args)
    },
    [isShadowConnected],
  )

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
      objectId: currentNotificationObjectId,
    })
  }, [currentNotificationObjectId, enqueueNotification, robotVideoLastError])

  useEffect(() => {
    if (route.kind !== 'device' && route.kind !== 'device_video') {
      previousReportedRedconRef.current = reportedRedcon
      return
    }
    const nextAutoOpenDeviceDetailPanelState = currentDeviceAdapter?.getAutoOpenState({
      hasActiveSession: activeShadowTarget !== null,
      previousRedcon: previousReportedRedconRef.current,
      nextRedcon: reportedRedcon,
      routeKind: route.kind,
    }) ?? null
    if (nextAutoOpenDeviceDetailPanelState) {
      setIsBotPanelOpen(nextAutoOpenDeviceDetailPanelState.isDetailPanelOpen)
      setIsBoardVideoExpanded(nextAutoOpenDeviceDetailPanelState.isBoardVideoExpanded)
    }
    previousReportedRedconRef.current = reportedRedcon
  }, [activeShadowTarget, currentDeviceAdapter, reportedRedcon, route])

  useEffect(() => {
    if (!currentDeviceAdapter?.shouldCloseDetail(reportedRedcon)) {
      return
    }
    if (isBotPanelOpen) {
      setIsBotPanelOpen(false)
    }
    if (isBoardVideoExpanded) {
      setIsBoardVideoExpanded(false)
    }
  }, [currentDeviceAdapter, isBoardVideoExpanded, isBotPanelOpen, reportedRedcon])

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
      if (
        shouldSuppressRobotStateTeardownError({
          error: caughtError,
          canUseBoardVideo,
          isBoardVideoExpanded,
          isShadowConnected,
          pendingTargetRedcon,
        })
      ) {
        return
      }
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
    pendingTargetRedcon,
    isShadowConnected,
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
  }, [canUseBoardVideo, cmdVelRepeatIntervalMs, isBoardVideoExpanded, isShadowConnected])

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
    const commandTarget = currentThingSparkplugCommandTarget
    if (!commandTarget) {
      return false
    }

    const commandSequence = redconCommandSequenceRef.current + 1
    redconCommandSequenceRef.current = commandSequence
    setIsUpdatingShadow(true)

    try {
      await publishDirectSparkplugRedconCommand(
        resolveSessionIdToken,
        commandTarget,
        redcon,
        commandSequence - 1,
      )
      if (redconCommandSequenceRef.current === commandSequence) {
        setPendingTargetRedcon(redcon)
        appendSessionLogEntry({
          tone: 'neutral',
          message: `Sparkplug DCMD.redcon -> ${redcon}`,
          dedupeKey: `sparkplug-redcon:${redcon}`,
          objectId: currentNotificationObjectId,
        })
        void waitForRouteSparkplugRedcon(commandTarget.deviceId, redcon, commandSequence)
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
      const isWakeTargetPending =
        pendingTargetRedcon !== null && pendingTargetRedcon !== 4
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

  const renderCatalogCardLink = (path: string, label: string): ReactElement => (
    <a
      href={path}
      className="catalog-card-link"
      onClick={(event) => {
        handleRouteLinkClick(event, path)
      }}
    >
      <span className="catalog-card-link-line">{label}</span>
    </a>
  )

  const renderNavigationPath = (): ReactElement | null => {
    if (route.kind === 'root' || route.kind === 'not_found') {
      return null
    }

    const townLabel = navigationTownLabel ?? route.town
    const crumbs: ReactElement[] = [renderInlineRouteLink(buildTownPath(route.town), townLabel)]
    if (route.kind === 'town') {
      crumbs[0] = (
        <span key={`crumb-town:${route.town}`} className="navigation-current-link">
          {townLabel}
        </span>
      )
    } else if (route.kind === 'rig') {
      const rigLabel = navigationRigLabel ?? route.rig
      crumbs.push(<span key={`crumb-rig:${route.rig}`}>{rigLabel}</span>)
    } else if (route.kind === 'device' || route.kind === 'device_video') {
      const rigLabel = navigationRigLabel ?? route.rig
      const deviceLabel = selectedDeviceLabel ?? route.device
      crumbs.push(renderInlineRouteLink(buildRigPath(route.town, route.rig), rigLabel))
      crumbs.push(
        renderInlineRouteLink(
          buildDevicePath(route.town, route.rig, route.device),
          deviceLabel,
        ),
      )
    }
    if (route.kind === 'device_video') {
      crumbs.push(<span key={`crumb-video:${route.device}`}>video</span>)
    }
    if (route.kind === 'rig') {
      const rigLabel = navigationRigLabel ?? route.rig
      crumbs[crumbs.length - 1] = (
        <span key={`crumb-rig:${route.rig}`} className="navigation-current-link">
          {rigLabel}
        </span>
      )
    }
    if (route.kind === 'device' || route.kind === 'device_video') {
      const deviceLabel = selectedDeviceLabel ?? route.device
      crumbs[crumbs.length - 1] = (
        <span
          key={`crumb-device:${route.device}:${route.kind}`}
          className="navigation-current-link"
        >
          {route.kind === 'device' ? deviceLabel : 'video'}
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
                  <button type="button" onClick={() => void beginSignIn()} className="status-auth-link">
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
  const isRouteSessionPending =
    !hasUnsupportedTown &&
    (route.kind === 'town' ||
      route.kind === 'rig' ||
      route.kind === 'device' ||
      route.kind === 'device_video') &&
    routeHeaderState.status === 'loading'
  const routeLoadingLabel =
    route.kind === 'town'
      ? navigationTownLabel ?? 'town'
      : route.kind === 'rig'
        ? navigationRigLabel ?? 'rig'
        : route.kind === 'device' || route.kind === 'device_video'
          ? selectedDeviceLabel ?? 'device'
          : 'route'

  const navigationPanel =
    route.kind !== 'root' && isNavigationReady ? (
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
          {currentRouteThingName !== null ? (
            <SparkplugPanel
              sparkplugRedcon={reportedRedcon}
              targetRedcon={pendingTargetRedcon}
              isInteractive={isSparkplugDeviceCommandAvailable}
              isRedconCommandDisabled={isRedconCommandDisabled}
              isRedconSleepCommandDisabled={isRedconSleepCommandDisabled}
              onRedconSelect={(redcon) => {
                void handleRedconSelect(redcon)
              }}
            />
          ) : null}
          <NavigationUserMenu
            authUser={authUser}
            txingVersion={appConfig.txingVersion}
            isSessionLogVisible={isSessionLogVisible}
            onSignOff={handleSignOff}
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
          This deployment is scoped to <strong>{configuredTownLabel}</strong> (
          <code>{configuredTownThingName}</code>). The current URL targets town thing{' '}
          <strong>{currentRouteTown}</strong>.
        </p>
        <p>{renderInlineRouteLink(configuredTownPath, `Open ${configuredTownLabel}`)}</p>
      </section>
    )
  } else if (routeHeaderState.status === 'error') {
    content = (
      <section className="card catalog-card">
        <h1>Route unavailable</h1>
        <p>{routeHeaderState.error}</p>
        <p>{renderInlineRouteLink(configuredTownPath, `Open ${configuredTownLabel}`)}</p>
      </section>
    )
  } else if (isRouteSessionPending) {
    content = (
      <section className="card catalog-card">
        <h1>Loading route</h1>
        <p>Resolving {routeLoadingLabel} metadata and current Sparkplug state...</p>
      </section>
    )
  } else if (currentThingKind === 'townType' && route.kind === 'town') {
    content = isTownPanelOpen && shouldRenderCatalogPanel ? (
      <section className="catalog-grid-shell">
        {rigCatalog.status === 'loading' ? <p>Loading rigs...</p> : null}
        {rigCatalog.status === 'error' ? <p className="error">{rigCatalog.error}</p> : null}
        {rigCatalog.status === 'ready' && rigCatalog.rigs.length === 0 ? (
          <p>No rigs are currently registered for this town.</p>
        ) : null}
        {rigCatalog.rigs.length > 0 ? (
          <ul
            className="catalog-list catalog-grid"
            aria-label={`Rigs in ${navigationTownLabel ?? route.town}`}
          >
            {rigCatalog.rigs.map((rig) => (
              <li key={rig.thingName} className="catalog-list-item">
                {renderCatalogCardLink(
                  buildRigPath(route.town, rig.thingName),
                  formatCatalogDetailLine(rig.shortId, rig.rigName),
                )}
              </li>
            ))}
          </ul>
        ) : null}
      </section>
    ) : (
      <></>
    )
  } else if (currentThingKind === 'rigType' && route.kind === 'rig') {
    content = isRigPanelOpen && shouldRenderCatalogPanel ? (
      <section className="catalog-grid-shell">
        {deviceCatalog.status === 'loading' ? <p>Loading devices...</p> : null}
        {deviceCatalog.status === 'not_found' ? <p className="error">{deviceCatalog.error}</p> : null}
        {deviceCatalog.status === 'error' ? <p className="error">{deviceCatalog.error}</p> : null}
        {deviceCatalog.status === 'ready' && deviceCatalog.devices.length === 0 ? (
          <p>No devices are currently assigned to this rig.</p>
        ) : null}
        {deviceCatalog.devices.length > 0 ? (
          <ul
            className="catalog-list catalog-grid"
            aria-label={`Devices in ${navigationRigLabel ?? route.rig}`}
          >
            {deviceCatalog.devices.map((device) => (
              <li key={device.thingName} className="catalog-list-item">
                {renderCatalogCardLink(
                  buildDevicePath(route.town, route.rig, device.thingName),
                  formatCatalogDetailLine(device.shortId, getCatalogDeviceLabel(device)),
                )}
              </li>
            ))}
          </ul>
        ) : null}
      </section>
    ) : (
      <></>
    )
  } else if (isDeviceThingType && selectedDeviceRoute && !isSelectedDeviceValid) {
    content = (
      <section className="card catalog-card">
        <h1>Device unavailable</h1>
        <p>
          {route.kind === 'device_video'
            ? `Thing '${selectedDeviceRoute.device}' does not expose board video for this route.`
            : `Thing '${selectedDeviceRoute.device}' could not be opened as a device route.`}
        </p>
        <p>
          {renderInlineRouteLink(
            buildRigPath(selectedDeviceRoute.town, selectedDeviceRoute.rig),
            `Open ${navigationRigLabel ?? selectedDeviceRoute.rig}`,
          )}
        </p>
      </section>
    )
  } else if (
    isDeviceThingType &&
    currentDeviceAdapter !== null &&
    route.kind === 'device_video' &&
    selectedDeviceRoute
  ) {
    content = (
      <section className="card catalog-card catalog-card-detail">
        {currentDeviceAdapter.renderVideo({
          videoChannelName: currentDeviceAdapter.buildVideoChannelName(selectedDeviceRoute.device),
          debugEnabled: isDebugEnabled,
          onRuntimeError: (message: string) => {
            enqueueRuntimeError(message, 'board-video-viewer')
          },
          resolveIdToken: resolveSessionIdToken,
        })}
      </section>
    )
  } else if (
    isDeviceThingType &&
    currentDeviceAdapter !== null &&
    route.kind === 'device' &&
    selectedDeviceRoute &&
    isBotPanelOpen
  ) {
    content = (
      currentDeviceAdapter.renderDetail({
        callMcpTool: callDeviceMcpTool,
        isBoardVideoExpanded,
        isDebugEnabled,
        isShadowConnected,
        mcpTransport,
        onToggleDebug: () => {
          setIsDebugEnabled((currentValue) => !currentValue)
        },
        reportedBatteryMv: primaryReportedBatteryMv,
        reportedBoardLeftTrackSpeed,
        reportedBoardOnline,
        reportedBoardRightTrackSpeed,
        reportedRedcon,
        reportedMcuOnline,
        videoChannelName: currentDeviceAdapter.buildVideoChannelName(selectedDeviceRoute.device),
        resolveIdToken: resolveSessionIdToken,
        shadow: displayShadowDocument,
        onBoardVideoRuntimeError: (message) => {
          enqueueRuntimeError(message, 'board-video-viewer')
        },
      })
    )
  } else if (
    isDeviceThingType &&
    currentDeviceAdapter !== null &&
    route.kind === 'device' &&
    selectedDeviceRoute
  ) {
    content = <></>
  } else if (isDeviceThingType && selectedDeviceRoute) {
    content = (
      <section className="card catalog-card">
        <h1>Unsupported device type</h1>
        <p>
          Thing <strong>{selectedDeviceRoute.device}</strong> has device type{' '}
          <strong>{currentThingTypeName}</strong>, but this web build has no registered detail
          adapter for that type.
        </p>
      </section>
    )
  } else {
    content = (
      <section className="card catalog-card">
        <h1>Device Shadow Admin</h1>
        <p>Waiting for a valid route selection.</p>
        <p>{renderInlineRouteLink(configuredTownPath, `Open ${configuredTownLabel}`)}</p>
      </section>
    )
  }

  const shadowAvailabilityNotice =
    hasShadowBootstrapFailure && activeShadowTarget !== null ? (
      <section className="card catalog-card">
        <h1>Live shadow connection unavailable</h1>
        <p>{shadowBootstrapError}</p>
        <p>
          Showing route labels and current Sparkplug state from direct AWS IoT reads. Sparkplug
          REDCON commands still publish directly; device detail telemetry remains limited until the
          live shadow session reconnects.
        </p>
      </section>
    ) : null
  const routeHeaderShadowNotice =
    routeHeaderShadowWarning !== '' ? (
      <section className="card catalog-card">
        <h1>Current Sparkplug state unavailable</h1>
        <p>{routeHeaderShadowWarning}</p>
        <p>
          Route labels come from the registry metadata. The top panel stays generic to the
          current thing, while type-specific detail content remains gated by the current
          Sparkplug REDCON state.
        </p>
      </section>
    ) : null

  return (
    <main className="page page-signed-in">
      {navigationPanel}
      {routeHeaderShadowNotice}
      {shadowAvailabilityNotice}
      {content}

      <NotificationTray
        notifications={notifications}
        onDismiss={(notificationId) => {
          dismissNotification(notificationId)
        }}
      />

      {isSessionLogVisible && <NotificationLogPanel notificationLog={notificationLog} />}

      {isDebugEnabled && activeShadowTarget !== null && (
        <DebugPanel
          canLoadShadow={canLoadShadow}
          lastShadowUpdateLabel={lastShadowUpdateLabel}
          lastShadowUpdateTitle={lastShadowUpdateTitle}
          onLoadShadow={() => {
            void loadShadow()
          }}
          reportedBoardPower={reportedBoardPower}
          reportedMcuPower={reportedMcuPower}
          shadowJson={shadowJson}
        />
      )}
    </main>
  )
}

export default App
