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
  MavlinkDriveTeleopController,
  mavlinkDriveRefreshMs,
  mavlinkWebRtcDataChannelLabel,
  type MavlinkControlState,
  type MavlinkFlightState,
  type MavlinkTelemetry,
  type MavlinkTarget,
} from '../../../office/src/mavlink-control'
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
  controlActionTitle: string
  controlLabel: string
  flightState: MavlinkFlightState
  isControlActionDisabled: boolean
  leaseTtlMs: number
  telemetry: MavlinkTelemetry | null
  telemetryFrameCount: number
  toggleControl: () => void
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
  const reportRuntimeError = useEffectEvent(onRuntimeError)

  useEffect(() => {
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
      sessionRef.current = null
    }
  }, [actor, channelName, enabled, region, resolveIdToken])

  const canControl = connectionState === 'open' && activeHeldByCaller && initialTarget !== null
  const canDrive = canControl && driveReady && pendingAction === null

  useEffect(() => {
    if (!canDrive || !initialTarget) {
      return
    }
    const teleop = new MavlinkDriveTeleopController({
      sendControl: async (steering, throttle) => {
        await sessionRef.current?.sendManualControl(initialTarget, steering, throttle)
      },
    })
    teleop.activate()
    const refreshTimerId = window.setInterval(() => {
      teleop.tick()
    }, mavlinkDriveRefreshMs)
    const handleKeyDown = (event: KeyboardEvent): void => {
      if (teleop.handleKeyDown(event.key)) {
        event.preventDefault()
      }
    }
    const handleKeyUp = (event: KeyboardEvent): void => {
      if (teleop.handleKeyUp(event.key)) {
        event.preventDefault()
      }
    }
    const handleBlur = (): void => teleop.handleSafetyStop()
    const handleVisibilityChange = (): void => {
      if (document.hidden) {
        teleop.handleSafetyStop()
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    window.addEventListener('keyup', handleKeyUp)
    window.addEventListener('blur', handleBlur)
    window.addEventListener('pagehide', handleBlur)
    document.addEventListener('visibilitychange', handleVisibilityChange)
    return () => {
      window.clearInterval(refreshTimerId)
      window.removeEventListener('keydown', handleKeyDown)
      window.removeEventListener('keyup', handleKeyUp)
      window.removeEventListener('blur', handleBlur)
      window.removeEventListener('pagehide', handleBlur)
      document.removeEventListener('visibilitychange', handleVisibilityChange)
      teleop.deactivate()
    }
  }, [canDrive, initialTarget])

  const acquireDriveControl = async (): Promise<void> => {
    const session = sessionRef.current
    if (!session || !initialTarget) {
      throw new Error('MAVLink control is not ready')
    }
    setDriveReady(false)
    await session.activate(controlState.activeControl !== null)
    try {
      await session.selectMode(initialTarget, 'manual')
      await session.armDisarm(initialTarget, true)
      setDriveReady(true)
    } catch (error) {
      try {
        await session.release()
      } catch {
        session.close()
      }
      throw error
    }
  }

  const releaseDriveControl = async (): Promise<void> => {
    const session = sessionRef.current
    if (!session) {
      throw new Error('MAVLink data channel is not connected')
    }
    setDriveReady(false)
    await session.release()
  }

  const toggleControl = (): void => {
    const action = activeHeldByCaller ? 'release' : 'activate'
    setPendingAction(action)
    void (async () => {
      try {
        if (activeHeldByCaller) {
          await releaseDriveControl()
        } else {
          await acquireDriveControl()
        }
      } catch (error) {
        reportRuntimeError(error instanceof Error ? error.message : `MAVLink ${action} failed`)
      } finally {
        setPendingAction(null)
      }
    })()
  }

  const controlLabel = describeOwner(controlState, activeHeldByCaller)
  const controlActionLabel = activeHeldByCaller
    ? 'Release control'
    : controlState.activeControl
      ? 'Take over control'
      : 'Take control'
  const controlActionTitle = activeHeldByCaller
    ? 'Release MAVLink control and return the vehicle to its safe state'
    : controlState.activeControl
      ? `Take over MAVLink control from ${controlState.activeControl.actor}`
      : 'Take MAVLink control'
  const isControlActionDisabled =
    pendingAction !== null ||
    (activeHeldByCaller ? connectionState !== 'open' : connectionState !== 'open' || initialTarget === null)

  return (
    <MavlinkControlContext.Provider
      value={{
        activeHeldByCaller,
        connectionState,
        controlActionLabel,
        controlActionTitle,
        controlLabel,
        flightState,
        isControlActionDisabled,
        leaseTtlMs: controlState.leaseTtlMs,
        telemetry,
        telemetryFrameCount,
        toggleControl,
      }}
    >
      {children}
    </MavlinkControlContext.Provider>
  )
}

const MavlinkControlGlyph = ({ active }: { active: boolean }) => (
  <svg
    className="status-video-take-control-glyph"
    viewBox="0 0 24 24"
    aria-hidden="true"
    focusable="false"
  >
    {active ? (
      <path
        d="M5 12.8 9.4 17 19 7"
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="2.4"
      />
    ) : (
      <>
        <circle cx="12" cy="12" r="7" fill="none" stroke="currentColor" strokeWidth="1.9" />
        <path
          d="M12 7.6v8.8M7.6 12h8.8"
          fill="none"
          stroke="currentColor"
          strokeLinecap="round"
          strokeWidth="2.1"
        />
      </>
    )}
  </svg>
)

export function MavlinkControlButton({ vehicleName }: { vehicleName: string }) {
  const control = useContext(MavlinkControlContext)
  if (!control) {
    return null
  }
  return (
    <button
      type="button"
      className="status-video-take-control-button status-video-mavlink-control-button"
      aria-label={`${control.controlActionLabel} for ${vehicleName}`}
      disabled={control.isControlActionDisabled}
      title={control.controlActionTitle}
      data-mavlink-control-owner={control.activeHeldByCaller ? 'current' : 'other'}
      onClick={control.toggleControl}
    >
      <MavlinkControlGlyph active={control.activeHeldByCaller} />
    </button>
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
      <p className="mavlink-debug-help">Use the single status control button to acquire or release drive control.</p>
    </section>
  )
}
