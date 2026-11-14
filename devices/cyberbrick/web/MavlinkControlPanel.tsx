import {
  createContext,
  useContext,
  useEffect,
  useEffectEvent,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import {
  MavlinkControlSession,
  mavlinkWebRtcDataChannelLabel,
  type MavlinkControlState,
  type MavlinkFlightState,
  type MavlinkTelemetry,
  type MavlinkTarget,
} from '../../../office/src/mavlink-control'
import MavlinkControllerPanel from '../../../office/src/MavlinkControllerPanel'
import { centeredSticks, readRoverMotion, type ControllerSticks } from '../../../office/src/mavlink-controller-input'
import { startMavlinkDataChannel } from '../../../office/src/mavlink-session'

type MavlinkControlProviderProps = {
  actor: string
  channelName: string
  children: ReactNode
  enabled: boolean
  initialTarget: MavlinkTarget | null
  onRuntimeError: (message: string) => void
  region: string
  resolveIdToken: () => Promise<string>
}

type ConnectionState = 'connecting' | 'error' | 'idle' | 'open' | 'reconnecting'

type MavlinkControlContextValue = {
  activeHeldByCaller: boolean
  connectionState: ConnectionState
  controlActionLabel: string
  canDrive: boolean
  controlLabel: string
  flightState: MavlinkFlightState
  isControlActionDisabled: boolean
  leaseTtlMs: number
  telemetry: MavlinkTelemetry | null
  telemetryFrameCount: number
  acquireDriveControl: (signal: AbortSignal) => Promise<void>
  releaseDriveControl: () => Promise<void>
  sendMotion: (sticks: ControllerSticks) => void
}

const emptyControlState: MavlinkControlState = {
  activeControl: null,
  epoch: 0,
  leaseTtlMs: 5_000,
}

const MavlinkControlContext = createContext<MavlinkControlContextValue | null>(null)

const describeConnectionState = (state: ConnectionState): string => {
  switch (state) {
    case 'connecting':
      return 'Connecting MAVLink control peer'
    case 'open':
      return 'MAVLink control peer connected'
    case 'reconnecting':
      return 'MAVLink control peer reconnecting'
    case 'error':
      return 'MAVLink control peer unavailable'
    default:
      return 'MAVLink control peer idle'
  }
}

const describeOwner = (
  controlState: MavlinkControlState,
  activeHeldByCaller: boolean,
): string => {
  if (!controlState.activeControl) {
    return 'No active controller'
  }
  if (activeHeldByCaller) {
    return `You hold control epoch ${controlState.activeControl.epoch}`
  }
  return `Control held by ${controlState.activeControl.actor} (epoch ${controlState.activeControl.epoch})`
}

const describeFlightState = (flightState: MavlinkFlightState): string => {
  const armed = flightState.armed === null ? 'arm state pending' : flightState.armed ? 'armed' : 'disarmed'
  const mode = flightState.mode === null ? 'mode pending' : `mode ${flightState.mode}`
  return `${armed}; ${mode}`
}

export function MavlinkControlProvider({
  actor,
  channelName,
  children,
  enabled,
  initialTarget,
  onRuntimeError,
  region,
  resolveIdToken,
}: MavlinkControlProviderProps) {
  const [connectionState, setConnectionState] = useState<ConnectionState>('idle')
  const [controlState, setControlState] = useState<MavlinkControlState>(emptyControlState)
  const [activeHeldByCaller, setActiveHeldByCaller] = useState(false)
  const [flightState, setFlightState] = useState<MavlinkFlightState>({ armed: null, mode: null })
  const [telemetry, setTelemetry] = useState<MavlinkTelemetry | null>(null)
  const [telemetryFrameCount, setTelemetryFrameCount] = useState(0)
  const [pendingAction, setPendingAction] = useState<string | null>(null)
  const [driveReady, setDriveReady] = useState(false)
  const sessionRef = useRef<MavlinkControlSession | null>(null)
  const actionSession = useRef<MavlinkControlSession | null>(null)
  const reportRuntimeError = useEffectEvent(onRuntimeError)

  useEffect(() => {
    setPendingAction(null)
    if (!enabled || channelName === '') {
      setConnectionState('idle')
      setControlState(emptyControlState)
      setActiveHeldByCaller(false)
      setFlightState({ armed: null, mode: null })
      setTelemetry(null)
      setTelemetryFrameCount(0)
      setDriveReady(false)
      return
    }

    let disposed = false
    let retryTimerId: number | null = null
    let retryDelayMs = 1_000
    let connectionAbortController: AbortController | null = null

    const scheduleReconnect = (): void => {
      if (disposed || retryTimerId !== null) {
        return
      }
      setConnectionState('reconnecting')
      retryTimerId = window.setTimeout(() => {
        retryTimerId = null
        void connect()
      }, retryDelayMs)
      retryDelayMs = Math.min(retryDelayMs * 2, 10_000)
    }

    const connect = async (): Promise<void> => {
      if (disposed) {
        return
      }
      setConnectionState('connecting')
      setPendingAction(null)
      const abortController = new AbortController()
      connectionAbortController = abortController
      const session = new MavlinkControlSession({
        actor,
        onControlState: (nextState, nextActiveHeldByCaller) => {
          if (!disposed) {
            setControlState(nextState)
            setActiveHeldByCaller(nextActiveHeldByCaller)
            if (!nextActiveHeldByCaller) {
              setDriveReady(false)
            }
          }
        },
        onFlightState: (nextState) => {
          if (!disposed) {
            setFlightState(nextState)
          }
        },
        onProtocolError: (message) => {
          if (!disposed) {
            reportRuntimeError(message)
          }
        },
        onTelemetry: (nextTelemetry) => {
          if (!disposed) {
            setTelemetry(nextTelemetry)
            setTelemetryFrameCount((count) => count + 1)
          }
        },
        onStateChange: (state) => {
          if (disposed || state !== 'closed') {
            return
          }
          setActiveHeldByCaller(false)
          setDriveReady(false)
          scheduleReconnect()
        },
      })
      sessionRef.current = session
      try {
        const handle = await startMavlinkDataChannel({
          channelName,
          label: mavlinkWebRtcDataChannelLabel,
          region,
          resolveIdToken,
          signal: abortController.signal,
          onMessage: (message) => session.handleMessage(message),
          onStateChange: (state, message) => {
            if (disposed) {
              return
            }
            if (state === 'connecting') {
              setConnectionState('connecting')
              return
            }
            if (state === 'open') {
              retryDelayMs = 1_000
              setConnectionState('open')
              return
            }
            if (state === 'error' && message) {
              reportRuntimeError(message)
            }
            session.close()
          },
        })
        if (disposed) {
          handle.close()
          return
        }
        session.attach(handle)
        await session.getState()
      } catch (error) {
        abortController.abort()
        if (disposed) {
          return
        }
        setConnectionState('error')
        reportRuntimeError(
          error instanceof Error ? error.message : 'Unable to connect MAVLink control peer',
        )
        session.close()
        scheduleReconnect()
      }
    }

    void connect()
    return () => {
      disposed = true
      if (retryTimerId !== null) {
        window.clearTimeout(retryTimerId)
      }
      sessionRef.current?.close()
      connectionAbortController?.abort()
      sessionRef.current = null
    }
  }, [actor, channelName, enabled, region, resolveIdToken])

  const isConnected = enabled && connectionState === 'open'
  const canDrive = isConnected && activeHeldByCaller && initialTarget !== null && driveReady && pendingAction === null
  const sendMotion = (sticks: ControllerSticks) => {
    const session = sessionRef.current
    if (!canDrive || !initialTarget || !session || actionSession.current === session) return
    const { steering, throttle } = readRoverMotion(sticks)
    void session.sendManualControl(initialTarget, steering, throttle).catch(() => {
      // The session can lose its lease between a React render and this sample.
    })
  }

  const releaseSession = async (session: MavlinkControlSession): Promise<void> => {
    if (session === sessionRef.current) {
      sendMotion(centeredSticks)
      setDriveReady(false)
    }
    try {
      await session.release()
    } catch (error) {
      session.close()
      if (session === sessionRef.current) {
        onRuntimeError(error instanceof Error ? error.message : 'MAVLink release failed')
      }
    }
  }

  const acquireDriveControl = async (signal: AbortSignal) => {
    const session = sessionRef.current
    if (signal.aborted || !isConnected || !session || !initialTarget ||
      session.hasActiveControl() || actionSession.current === session) return
    actionSession.current = session
    setPendingAction('activate')
    setDriveReady(false)
    const abort = () => session.close()
    signal.addEventListener('abort', abort, { once: true })
    try {
      await session.takeManualControl(initialTarget)
      if (sessionRef.current === session && !signal.aborted && session.hasActiveControl()) setDriveReady(true)
    } catch (error) {
      if (sessionRef.current === session && !signal.aborted) {
        onRuntimeError(error instanceof Error ? error.message : 'MAVLink activation failed')
      }
    } finally {
      signal.removeEventListener('abort', abort)
      if (actionSession.current === session) {
        actionSession.current = null
        if (sessionRef.current === session) setPendingAction(null)
      }
    }
  }

  const releaseDriveControl = async () => {
    const session = sessionRef.current
    if (!session?.hasActiveControl() || actionSession.current === session) return
    const result = releaseSession(session)
    actionSession.current = session
    setPendingAction('release')
    try {
      await result
    } finally {
      if (actionSession.current === session) {
        actionSession.current = null
        if (sessionRef.current === session) setPendingAction(null)
      }
    }
  }

  const controlLabel = describeOwner(controlState, activeHeldByCaller)
  const controlActionLabel = controlState.activeControl ? 'Take over control' : 'Take control'
  const isControlActionDisabled = pendingAction !== null || !isConnected ||
    (!activeHeldByCaller && initialTarget === null)

  return (
    <MavlinkControlContext.Provider
      value={{
        activeHeldByCaller,
        connectionState,
        controlActionLabel,
        canDrive,
        controlLabel,
        flightState,
        isControlActionDisabled,
        leaseTtlMs: controlState.leaseTtlMs,
        telemetry,
        telemetryFrameCount,
        acquireDriveControl,
        releaseDriveControl,
        sendMotion,
      }}
    >
      {children}
    </MavlinkControlContext.Provider>
  )
}

export function RoverControllerPanel({ vehicleName }: { vehicleName: string }) {
  const control = useContext(MavlinkControlContext)
  if (!control) return null
  return (
    <MavlinkControllerPanel
      vehicleName={vehicleName}
      profile="rover"
      held={control.activeHeldByCaller}
      canMove={control.canDrive}
      status={control.controlLabel}
      acquire={{ label: control.controlActionLabel, enabled: !control.isControlActionDisabled, run: control.acquireDriveControl }}
      release={{ enabled: !control.isControlActionDisabled, run: control.releaseDriveControl }}
      sendMotion={control.sendMotion}
    />
  )
}

export function MavlinkDebugPanel({ vehicleName }: { vehicleName: string }) {
  const control = useContext(MavlinkControlContext)
  if (!control) {
    return null
  }
  return (
    <section className="mavlink-debug-panel" aria-label={`${vehicleName} ArduPilot debug`}>
      <div className="mavlink-debug-heading">
        <strong>ArduPilot / MAVLink</strong>
        <span data-mavlink-connection={control.connectionState}>
          {describeConnectionState(control.connectionState)}
        </span>
      </div>
      <p className="mavlink-debug-owner" data-mavlink-owner={control.activeHeldByCaller ? 'current' : 'other'}>
        {control.controlLabel}
      </p>
      <p className="mavlink-debug-flight" data-mavlink-flight-state={control.flightState.armed === true ? 'armed' : control.flightState.armed === false ? 'disarmed' : 'pending'}>
        {describeFlightState(control.flightState)}
      </p>
      <p className="mavlink-debug-lease" data-mavlink-lease-ms={control.leaseTtlMs}>
        {control.leaseTtlMs / 1_000}-second renewable lease
      </p>
      <p className="mavlink-debug-telemetry" data-mavlink-telemetry-count={control.telemetryFrameCount}>
        {control.telemetry
          ? `Telemetry ${control.telemetryFrameCount}: message ${control.telemetry.messageId} from ${control.telemetry.systemId}:${control.telemetry.componentId} (sequence ${control.telemetry.sequence})`
          : 'Telemetry pending'}
      </p>
      <p className="mavlink-debug-help">Use the controller panel to acquire or release drive control.</p>
    </section>
  )
}
