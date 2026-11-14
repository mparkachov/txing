import { useEffect, useRef, useState } from 'react'
import type { AppNotificationInput } from '../../../office/src/app-notifications'
import { getThingNamedShadow } from '../../../office/src/catalog-api'
import { publishVirtualQuadCommand, type VirtualQuadCommand } from './virtual-quad-command'
import {
  extractReportedRedcon,
  extractSparkplugCapabilityAvailability,
  extractSparkplugMetrics,
  extractSparkplugRedconCommandStatus,
  hasLiveSparkplugDeviceProjection,
} from '../../../office/src/sparkplug-model'
import type { QuadTarget, useVirtualQuadSession } from './virtual-quad-session'

type SessionView = ReturnType<typeof useVirtualQuadSession>
type Pending = { target: QuadTarget; action: VirtualQuadCommand; deadlineMs: number }

const phaseLabel = {
  stopped: 'Stopped',
  starting: 'Starting simulator',
  operational: 'Simulator running',
  stopping: 'Stopping simulator',
  failed: 'Session failed',
}

export function readVirtualQuadLifecycleMessage(
  session: SessionView['session'], fresh = true, observedSessionId: string | null = null,
): Omit<AppNotificationInput, 'objectId'> | null {
  if (!session) return null
  if (session.phase === 'stopped' &&
    (!session.lastOutcome || observedSessionId === null || session.lastSessionId !== observedSessionId)) return null
  if (session.phase === 'operational' && !fresh) {
    return {
      tone: 'error',
      message: 'Simulator readiness unavailable',
      dedupeKey: `virtual-quad:${session.sessionId}:readiness-unavailable`,
    }
  }
  const reason = session.sessionId === null && session.lastOutcome !== 'stopped' ? session.lastReason : null
  return {
    tone: session.phase === 'failed' ? 'error' : session.phase === 'operational' ? 'success' : 'neutral',
    message: reason ? `${phaseLabel[session.phase]} · ${reason}` : phaseLabel[session.phase],
    dedupeKey: `virtual-quad:${session.sessionId ?? session.terminalRevision}:${session.phase}`,
  }
}

export function readVirtualQuadCommandResult(action: VirtualQuadCommand, { session, sparkplug, fresh }: SessionView) {
  const receipt = extractSparkplugRedconCommandStatus(sparkplug)
  const matches = receipt?.targetRedcon === action.redcon &&
    extractSparkplugMetrics(sparkplug)?.redconCommandId === action.requestId
  if (matches && receipt.status === 'failed') {
    return { status: 'failed', reason: receipt.message || 'Simulator command failed' } as const
  }
  if (action.redcon === 4 && session?.sessionId === null && session.lastSessionId === action.sessionId &&
    extractReportedRedcon(sparkplug) === 4) {
    return { status: 'succeeded' } as const
  }
  if (action.redcon === 1 && matches && receipt.status === 'succeeded' && fresh &&
    session?.phase === 'operational' && extractReportedRedcon(sparkplug) === 1) {
    return { status: 'succeeded' } as const
  }
  return null
}

export function useVirtualQuadRedcon(
  target: QuadTarget | null,
  sessionView: SessionView,
  resolveIdToken: () => Promise<string>,
  notify: (notification: AppNotificationInput) => void,
  log: (notification: AppNotificationInput) => void,
) {
  const { session, sparkplug, fresh, now } = sessionView
  const [pending, setPending] = useState<Pending | null>(null)
  const command = useRef<Pending | null>(null)
  const [awakeRigId, setAwakeRigId] = useState<string | null>(null)
  const lastMessage = useRef(new Map<string, string>())
  const observedSession = useRef<{ deviceId: string; sessionId: string } | null>(null)
  const currentPending = pending?.target === target ? pending : null
  const rigId = target?.edgeNodeId

  useEffect(() => {
    if (!rigId) return
    let cancelled = false
    let timer: number | undefined
    const refresh = async () => {
      let awake = false
      try {
        awake = extractReportedRedcon(await getThingNamedShadow(resolveIdToken, rigId, 'sparkplug')) === 1
      } catch {
        // An unreadable rig projection cannot authorize a start.
      }
      if (cancelled) return
      setAwakeRigId(awake ? rigId : null)
      timer = window.setTimeout(() => { void refresh() }, 5_000)
    }
    void refresh()
    return () => {
      cancelled = true
      window.clearTimeout(timer)
      setAwakeRigId(null)
    }
  }, [resolveIdToken, rigId])

  useEffect(() => () => {
    if (command.current?.target === target) command.current = null
  }, [target])

  useEffect(() => {
    if (!target) return
    if (session?.sessionId) {
      observedSession.current = { deviceId: target.deviceId, sessionId: session.sessionId }
    }
    const observedSessionId = observedSession.current?.deviceId === target.deviceId
      ? observedSession.current.sessionId
      : null
    const message = readVirtualQuadLifecycleMessage(session, fresh, observedSessionId)
    if (!message || lastMessage.current.get(target.deviceId) === message.dedupeKey) return
    lastMessage.current.set(target.deviceId, message.dedupeKey)
    notify({ ...message, dedupeKey: `${target.deviceId}:${message.dedupeKey}`, objectId: target.deviceId })
  }, [fresh, notify, session, target])

  useEffect(() => {
    if (!currentPending || command.current !== currentPending) return
    const { action, deadlineMs, target: commandTarget } = currentPending
    const result = readVirtualQuadCommandResult(action, sessionView)
    if (!result && now < deadlineMs) return
    command.current = null
    setPending(null)
    if (result?.status !== 'succeeded' &&
      !(result?.status === 'failed' && session?.phase === 'failed' && session.lastReason === result.reason)) {
      notify({
        tone: 'error',
        message: `REDCON ${action.redcon} · ${result?.reason ?? 'Simulator command was not confirmed'}`,
        dedupeKey: `virtual-quad-command:${action.requestId}`,
        objectId: commandTarget.deviceId,
      })
    }
  }, [currentPending, notify, now, session, sessionView])

  const canStart = target !== null && awakeRigId === rigId && currentPending === null &&
    (session?.phase === 'stopped' || session?.phase === 'failed') &&
    extractReportedRedcon(sparkplug) === 4 && hasLiveSparkplugDeviceProjection(sparkplug, target) &&
    extractSparkplugCapabilityAvailability(sparkplug, 'simulation') === true
  const stopSession = session?.phase === 'starting' || session?.phase === 'operational' ? session.sessionId : null
  const canStop = stopSession !== null && currentPending?.action.redcon !== 4

  const select = async (redcon: 1 | 2 | 3 | 4) => {
    if (!target || !session || (command.current?.target === target && command.current.action.redcon === redcon)) return
    const requestId = crypto.randomUUID()
    let action: VirtualQuadCommand
    if (redcon === 1 && canStart) action = { redcon, requestId, terminalRevision: session.terminalRevision }
    else if (redcon === 4 && canStop && stopSession) action = { redcon, requestId, sessionId: stopSession }
    else return

    const next = { action, target, deadlineMs: Date.now() + 120_000 }
    command.current = next
    setPending(next)
    try {
      await publishVirtualQuadCommand(resolveIdToken, target, action, Date.now() % 2_147_000_000)
      if (command.current === next) log({
        tone: 'neutral',
        message: `Sparkplug DCMD.redcon -> ${redcon}`,
        dedupeKey: `sparkplug-redcon:${redcon}`,
        objectId: target.deviceId,
      })
    } catch (cause) {
      if (command.current !== next) return
      command.current = null
      setPending(null)
      notify({
        tone: 'error',
        message: cause instanceof Error ? cause.message : 'Unable to send simulator command',
        dedupeKey: `virtual-quad-command:${requestId}`,
        objectId: target.deviceId,
      })
    }
  }

  return { canStart, canStop, pendingRedcon: currentPending?.action.redcon ?? null, select }
}
