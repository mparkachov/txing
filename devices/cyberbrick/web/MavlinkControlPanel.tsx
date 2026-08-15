import { useEffect, useEffectEvent, useRef, useState } from 'react'
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

type MavlinkControlPanelProps = {
  actor: string
  channelName: string
  initialArmed: boolean | null
  initialMode: string | null
  initialTarget: MavlinkTarget | null
  onRuntimeError: (message: string) => void
  region: string
  resolveIdToken: () => Promise<string>
}

type ConnectionState = 'connecting' | 'error' | 'idle' | 'open' | 'reconnecting'

const emptyControlState: MavlinkControlState = {
  activeControl: null,
  epoch: 0,
  leaseTtlMs: 5_000,
}

const initialFlightState = (
  armed: boolean | null,
  mode: string | null,
): MavlinkFlightState => ({ armed, mode })

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
  initialArmed,
  initialMode,
  initialTarget,
  onRuntimeError,
  region,
  resolveIdToken,
}: MavlinkControlPanelProps) {
  const [connectionState, setConnectionState] = useState<ConnectionState>('idle')
  const [controlState, setControlState] = useState<MavlinkControlState>(emptyControlState)
  const [activeHeldByCaller, setActiveHeldByCaller] = useState(false)
  const [flightState, setFlightState] = useState<MavlinkFlightState>(() =>
    initialFlightState(initialArmed, initialMode),
  )
  const [telemetry, setTelemetry] = useState<MavlinkTelemetry | null>(null)
  const [telemetryFrameCount, setTelemetryFrameCount] = useState(0)
  const [pendingAction, setPendingAction] = useState<string | null>(null)
  const sessionRef = useRef<MavlinkControlSession | null>(null)
  const reportRuntimeError = useEffectEvent(onRuntimeError)

  useEffect(() => {
    setFlightState(initialFlightState(initialArmed, initialMode))
  }, [initialArmed, initialMode])

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
  const controlLabel = describeOwner(controlState, activeHeldByCaller)
  const actionLabel = controlState.activeControl ? 'Take over control' : 'Acquire control'

  useEffect(() => {
    if (!canControl || !target) {
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
  }, [canControl, target])

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
    <section className="mavlink-control-panel" aria-label="Cyberbrick MAVLink control">
      <div className="mavlink-control-heading">
        <strong>MAVLink control</strong>
        <span data-mavlink-connection={connectionState}>{describeConnectionState(connectionState)}</span>
      </div>
      <p className="mavlink-control-owner" data-mavlink-owner={activeHeldByCaller ? 'current' : controlState.activeControl ? 'other' : 'none'}>
        {controlLabel}
      </p>
      <p className="mavlink-control-lease" data-mavlink-lease-ms={controlState.leaseTtlMs}>
        {controlState.leaseTtlMs / 1_000}-second renewable lease
      </p>
      <p className="mavlink-control-flight-state">
        {flightState.armed === null ? 'Arm state pending' : flightState.armed ? 'Armed' : 'Disarmed'}
        {' · '}
        {flightState.mode ?? 'Mode pending'}
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
                const session = sessionRef.current
                if (!session) {
                  throw new Error('MAVLink data channel is not connected')
                }
                await session.activate(controlState.activeControl !== null)
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
                if (target) {
                  await session.sendNeutral(target)
                }
                await session.release()
              })
            }}
          >
            Release control
          </button>
        )}
        <button
          type="button"
          disabled={!canControl || pendingAction !== null || flightState.armed === true}
          onClick={() => {
            if (target) {
              void runAction('arm', () => sessionRef.current!.armDisarm(target, true))
            }
          }}
        >
          Arm
        </button>
        <button
          type="button"
          disabled={!canControl || pendingAction !== null || flightState.armed !== true}
          onClick={() => {
            if (target) {
              void runAction('disarm', () => sessionRef.current!.armDisarm(target, false))
            }
          }}
        >
          Disarm
        </button>
        <button
          type="button"
          disabled={!canControl || pendingAction !== null || flightState.mode === 'manual'}
          onClick={() => {
            if (target) {
              void runAction('manual mode', () => sessionRef.current!.selectMode(target, 'manual'))
            }
          }}
        >
          Manual
        </button>
        <button
          type="button"
          disabled={!canControl || pendingAction !== null || flightState.mode === 'hold'}
          onClick={() => {
            if (target) {
              void runAction('hold mode', () => sessionRef.current!.selectMode(target, 'hold'))
            }
          }}
        >
          Hold
        </button>
      </div>
      <p className="mavlink-control-help">
        Arrow keys drive at 10 Hz while held. S, blur, and leaving the page send neutral control.
      </p>
    </section>
  )
}

export default MavlinkControlPanel
