import { useEffect, useRef, useState } from 'react'
import { getThingNamedShadow } from '../../../office/src/catalog-api'
import type { DeviceWebAdapter } from '../../../office/src/device-adapter'
import { publishVirtualQuadCommand } from '../../../office/src/sparkplug-command'
import {
  extractReportedRedcon,
  extractSparkplugCapabilityAvailability,
  extractSparkplugMetrics,
  extractSparkplugRedconCommandStatus,
  hasLiveSparkplugDeviceProjection,
} from '../../../office/src/sparkplug-model'
import type { VirtualQuadCommand } from '../../../office/src/sparkplug-protocol'
import { virtualQuadProjectedSession, type QuadTarget, type useVirtualQuadSession } from './virtual-quad-session'

const rigStatusPollIntervalMs = 5_000

const VirtualQuadStartButton = ({
  rigId,
  resolveIdToken,
  disabled,
  onStart,
}: {
  rigId: string
  resolveIdToken: () => Promise<string>
  disabled: boolean
  onStart: () => void
}) => {
  const [awake, setAwake] = useState(false)

  useEffect(() => {
    let cancelled = false
    let timer: number | undefined
    const refresh = async () => {
      let rigAwake = false
      try {
        const shadow = await getThingNamedShadow(resolveIdToken, rigId, 'sparkplug')
        rigAwake = extractReportedRedcon(shadow) === 1
      } catch {
        // Start remains unavailable while the rig projection cannot be read.
      }
      if (!cancelled) {
        setAwake(rigAwake)
        timer = window.setTimeout(() => { void refresh() }, rigStatusPollIntervalMs)
      }
    }
    void refresh()
    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
  }, [resolveIdToken, rigId])

  return awake ? <button type="button" disabled={disabled} onClick={onStart}>Start</button> : null
}

type Pending = { requestId: string; redcon: 1 | 4; deadlineMs: number }

const phaseLabel = {
  stopped: 'Stopped',
  starting: 'Starting simulator',
  operational: 'Simulator running',
  stopping: 'Stopping simulator',
  failed: 'Session failed',
}

export const VirtualQuadSessionControls = ({
  target,
  resolveIdToken,
  sessionView: { session, sparkplug, fresh, now },
}: {
  target: QuadTarget
  resolveIdToken: () => Promise<string>
  sessionView: ReturnType<typeof useVirtualQuadSession>
}) => {
  const [pending, setPending] = useState<Pending | null>(null)
  const [error, setError] = useState('')
  const command = useRef<Pending | null>(null)
  const receipt = extractSparkplugRedconCommandStatus(sparkplug)
  const receiptId = extractSparkplugMetrics(sparkplug)?.redconCommandId
  const receiptStatus = receipt?.status
  const receiptTarget = receipt?.targetRedcon
  const receiptMessage = receipt?.message
  const receiptSession = virtualQuadProjectedSession(sparkplug)

  useEffect(() => {
    if (!pending) return
    if (pending.requestId === receiptId && pending.redcon === receiptTarget && receiptStatus) {
      if (receiptStatus === 'failed') {
        setError(receiptMessage || 'Simulator command failed')
      }
      const phaseConfirmed = session?.sessionId === receiptSession && receiptSession !== null &&
        (pending.redcon === 1 || session?.phase === 'stopping')
      if (receiptStatus !== 'accepted' || phaseConfirmed) {
        command.current = null
        setPending(null)
        return
      }
    }
    if (now >= pending.deadlineMs) {
      setError('Simulator command was not confirmed')
      command.current = null
      setPending(null)
    }
  }, [now, pending, receiptId, receiptMessage, receiptSession, receiptStatus, receiptTarget, session?.phase, session?.sessionId])

  const send = async (action: Omit<Extract<VirtualQuadCommand, { redcon: 1 }>, 'requestId'> |
    Omit<Extract<VirtualQuadCommand, { redcon: 4 }>, 'requestId'>) => {
    if (command.current?.redcon === action.redcon) return
    const requestId = crypto.randomUUID()
    const next = { requestId, redcon: action.redcon, deadlineMs: Date.now() + 30_000 }
    command.current = next
    setError('')
    setPending(next)
    try {
      await publishVirtualQuadCommand(resolveIdToken, target, { ...action, requestId }, Date.now() % 2_147_000_000)
    } catch (cause) {
      if (command.current !== next) return
      command.current = null
      setPending(null)
      setError(cause instanceof Error ? cause.message : 'Unable to send simulator command')
    }
  }

  if (!session) return <span role="status">Reading simulator status</span>
  const canStart = (session.phase === 'stopped' || session.phase === 'failed') &&
    extractReportedRedcon(sparkplug) === 4 && hasLiveSparkplugDeviceProjection(sparkplug, target) &&
    extractSparkplugCapabilityAvailability(sparkplug, 'simulation') === true
  const stopSession = session.phase === 'starting' || session.phase === 'operational' ? session.sessionId : null
  const deadline = session.phase === 'starting' ? session.startupDeadlineMs
    : session.phase === 'operational' ? session.flightDeadlineMs
      : session.phase === 'stopping' ? session.shutdownDeadlineMs : null
  const seconds = deadline === null ? null : Math.max(0, Math.ceil((deadline - now) / 1_000))
  const phase = session.phase === 'operational' && !fresh ? 'Simulator readiness unavailable' : phaseLabel[session.phase]
  const lastReason = session.sessionId === null && session.lastOutcome !== 'stopped' ? session.lastReason : null
  const feedback = pending ? (pending.redcon === 1 ? 'Requesting Start' : 'Requesting Stop') : phase

  return (
    <>
      {canStart && (
        <VirtualQuadStartButton
          rigId={target.edgeNodeId}
          resolveIdToken={resolveIdToken}
          disabled={pending !== null}
          onStart={() => { void send({ redcon: 1, terminalRevision: session.terminalRevision }) }}
        />
      )}
      {stopSession && (
        <button type="button" disabled={pending?.redcon === 4}
          onClick={() => { void send({ redcon: 4, sessionId: stopSession }) }}>Stop</button>
      )}
      <span role="status">{feedback}{lastReason ? ` · ${lastReason}` : ''}</span>
      {seconds !== null && <span aria-label="Session time remaining">
        {Math.floor(seconds / 60)}:{String(seconds % 60).padStart(2, '0')}
      </span>}
      {error && <span role="alert">{error}</span>}
    </>
  )
}

const virtualQuadAdapter: DeviceWebAdapter = {
  type: 'virtual-quad',
  displayName: 'Virtual Quadcopter',
  buildVideoChannelName: (deviceId) => `${deviceId}-board-video`,
  buildMavlinkChannelName: (deviceId) => `${deviceId}-mavlink`,
  canUseBoardVideo: () => false,
  canUseDriveControl: () => false,
  extractTelemetry: () => ({
    reportedBatteryMv: null,
    reportedBoardPower: null,
    reportedBoardOnline: null,
    reportedMcuOnline: null,
    reportedMcuPower: null,
  }),
  getAutoOpenState: () => null,
  shouldCloseDetail: () => false,
  renderDetail: ({ reportedRedcon }) => (
    <section aria-label="Virtual quadcopter status">
      {reportedRedcon === 4 ? 'Stopped' : 'Unavailable'}
    </section>
  ),
  renderVideo: () => <p>Video unavailable</p>,
}

export default virtualQuadAdapter
