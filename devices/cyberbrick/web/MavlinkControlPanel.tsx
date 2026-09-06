import { useEffect, useEffectEvent, useRef, useState } from 'react'
import {
  MavlinkControlSession,
  MavlinkDriveTeleopController,
  mavlinkDriveRefreshMs,
  mavlinkWebRtcDataChannelLabel,
  type MavlinkControlState,
  type MavlinkTelemetry,
  type MavlinkTarget,
} from '../../../office/src/mavlink-control'
import { startMavlinkDataChannel } from '../../../office/src/mavlink-session'

type MavlinkControlPanelProps = {
  actor: string
  channelName: string
  initialTarget: MavlinkTarget | null
  onRuntimeError: (message: string) => void
  region: string
  resolveIdToken: () => Promise<string>
  vehicleName?: string
}

type ConnectionState = 'connecting' | 'error' | 'idle' | 'open' | 'reconnecting'

const emptyControlState: MavlinkControlState = {
  activeControl: null,
  epoch: 0,
  leaseTtlMs: 5_000,
}

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

function MavlinkControlPanel({
  actor,
  channelName,
  initialTarget,
  onRuntimeError,
  region,
  resolveIdToken,
  vehicleName = 'Cyberbrick',
}: MavlinkControlPanelProps) {
  const [connectionState, setConnectionState] = useState<ConnectionState>('idle')
  const [controlState, setControlState] = useState<MavlinkControlState>(emptyControlState)
  const [activeHeldByCaller, setActiveHeldByCaller] = useState(false)
  const [telemetry, setTelemetry] = useState<MavlinkTelemetry | null>(null)
  const [telemetryFrameCount, setTelemetryFrameCount] = useState(0)
  const [pendingAction, setPendingAction] = useState<string | null>(null)
  const [driveReady, setDriveReady] = useState(false)
  const sessionRef = useRef<MavlinkControlSession | null>(null)
  const reportRuntimeError = useEffectEvent(onRuntimeError)

  useEffect(() => {
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
        onFlightState: () => {},
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
  }, [actor, channelName, region, resolveIdToken])

  const target = initialTarget
  const canControl = connectionState === 'open' && activeHeldByCaller && target !== null
  const canDrive = canControl && driveReady && pendingAction === null
  const controlLabel = describeOwner(controlState, activeHeldByCaller)
  const actionLabel = controlState.activeControl ? 'Take over control' : 'Acquire control'
  const operatorMode = canDrive
    ? 'Control mode active'
    : activeHeldByCaller
      ? 'Preparing control mode'
      : 'View-only mode'

  useEffect(() => {
    if (!canDrive || !target) {
      return
    }
    const teleop = new MavlinkDriveTeleopController({
      sendControl: async (steering, throttle) => {
        await sessionRef.current?.sendManualControl(target, steering, throttle)
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
  }, [canDrive, target])

  const acquireDriveControl = async (): Promise<void> => {
    const session = sessionRef.current
    if (!session || !target) {
      throw new Error('MAVLink control is not ready')
    }
    setDriveReady(false)
    await session.activate(controlState.activeControl !== null)
    try {
      // ArduPilot details stay beneath the operator-level control boundary:
      // an acquired control lease is always ready for manual keyboard driving.
      await session.selectMode(target, 'manual')
      await session.armDisarm(target, true)
      setDriveReady(true)
    } catch (error) {
      // If setup is incomplete, relinquish authority so the daemon's full
      // safe-state path returns the vehicle to view-only operation.
      try {
        await session.release()
      } catch {
        session.close()
      }
      throw error
    }
  }

  const runAction = async (action: string, callback: () => Promise<void>): Promise<void> => {
    setPendingAction(action)
    try {
      await callback()
    } catch (error) {
      reportRuntimeError(error instanceof Error ? error.message : `MAVLink ${action} failed`)
    } finally {
      setPendingAction(null)
    }
  }

  return (
    <section className="mavlink-control-panel" aria-label={`${vehicleName} MAVLink control`}>
      <div className="mavlink-control-heading">
        <strong>MAVLink control</strong>
        <span data-mavlink-connection={connectionState}>{describeConnectionState(connectionState)}</span>
      </div>
      <p className="mavlink-control-owner" data-mavlink-owner={activeHeldByCaller ? 'current' : controlState.activeControl ? 'other' : 'none'}>
        {controlLabel}
      </p>
      <p className="mavlink-control-mode" data-mavlink-mode={canDrive ? 'control' : 'view'}>
        {operatorMode}
      </p>
      <p className="mavlink-control-lease" data-mavlink-lease-ms={controlState.leaseTtlMs}>
        {controlState.leaseTtlMs / 1_000}-second renewable lease
      </p>
      <p className="mavlink-control-telemetry" data-mavlink-telemetry-count={telemetryFrameCount}>
        {telemetry
          ? `Telemetry ${telemetryFrameCount}: message ${telemetry.messageId} from ${telemetry.systemId}:${telemetry.componentId} (sequence ${telemetry.sequence})`
          : 'Telemetry pending'}
      </p>
      <div className="mavlink-control-actions">
        {!activeHeldByCaller ? (
          <button
            type="button"
            disabled={connectionState !== 'open' || pendingAction !== null}
            onClick={() => {
              void runAction('activate', async () => {
                await acquireDriveControl()
              })
            }}
          >
            {actionLabel}
          </button>
        ) : (
          <button
            type="button"
            disabled={pendingAction !== null}
            onClick={() => {
              void runAction('release', async () => {
                const session = sessionRef.current
                if (!session) {
                  throw new Error('MAVLink data channel is not connected')
                }
                setDriveReady(false)
                await session.release()
              })
            }}
          >
            Release control
          </button>
        )}
      </div>
      <p className="mavlink-control-help">
        Acquiring control prepares manual drive. Arrow keys drive at 10 Hz while held; releasing them sends neutral control.
      </p>
    </section>
  )
}

export default MavlinkControlPanel
