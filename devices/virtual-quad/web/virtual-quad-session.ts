import { useEffect, useState } from 'react'
import { getThingNamedShadow } from '../../../office/src/catalog-api'
import type { SparkplugRedconCommandTarget } from '../../../office/src/sparkplug-command'
import {
  extractReportedState,
  extractSparkplugMetrics,
  extractSparkplugPayloadTimestamp,
  hasLiveSparkplugDeviceProjection,
} from '../../../office/src/sparkplug-model'

export type QuadTarget = Extract<SparkplugRedconCommandTarget, { kind: 'device' }>

const phases = ['stopped', 'starting', 'operational', 'stopping', 'failed'] as const
type Phase = typeof phases[number]

type Session = {
  phase: Phase
  terminalRevision: number
  sessionId: string | null
  lastOutcome: string | null
  lastReason: string | null
  availabilityWatermarkMs: number | null
  availabilityExpiresAtMs: number | null
  startupDeadlineMs: number | null
  flightDeadlineMs: number | null
  shutdownDeadlineMs: number | null
}

const integer = (value: unknown): number | null =>
  typeof value === 'number' && Number.isSafeInteger(value) && value >= 0 ? value : null

const text = (value: unknown): string | null =>
  typeof value === 'string' && value !== '' ? value : null

export const readVirtualQuadSession = (shadow: unknown): Session | null => {
  const reported = extractReportedState(shadow)
  const phase = phases.find((value) => value === reported?.phase)
  const terminalRevision = integer(reported?.terminalRevision)
  if (!reported || !phase || terminalRevision === null) return null
  const sessionId = text(reported.sessionId)
  const terminal = phase === 'stopped' || phase === 'failed'
  if (terminal ? sessionId !== null : sessionId === null) return null
  return {
    phase, terminalRevision, sessionId,
    lastOutcome: text(reported.lastOutcome),
    lastReason: text(reported.lastReason),
    availabilityWatermarkMs: integer(reported.availabilityWatermarkMs),
    availabilityExpiresAtMs: integer(reported.availabilityExpiresAtMs),
    startupDeadlineMs: integer(reported.startupDeadlineMs),
    flightDeadlineMs: integer(reported.flightDeadlineMs),
    shutdownDeadlineMs: integer(reported.shutdownDeadlineMs),
  }
}

export const virtualQuadProjectedSession = (sparkplug: unknown): string | null => {
  const data = extractSparkplugMetrics(sparkplug)?.virtualQuad
  return data && typeof data === 'object' && 'sessionId' in data ? text(data.sessionId) : null
}

export const isVirtualQuadProjectionFresh = (
  target: QuadTarget,
  session: Session | null,
  sparkplug: unknown,
  now: number,
): boolean => {
  const timestamp = extractSparkplugPayloadTimestamp(sparkplug)
  return session !== null && session.sessionId !== null &&
    (session.phase === 'starting' || session.phase === 'operational') &&
    session.availabilityWatermarkMs !== null && session.availabilityExpiresAtMs !== null &&
    timestamp !== null && timestamp >= session.availabilityWatermarkMs && now < session.availabilityExpiresAtMs &&
    virtualQuadProjectedSession(sparkplug) === session.sessionId &&
    hasLiveSparkplugDeviceProjection(sparkplug, target)
}

type Snapshot = {
  target: QuadTarget
  session: Session | null
  sparkplug: unknown
}

export const useVirtualQuadSession = (
  target: QuadTarget | null,
  resolveIdToken: () => Promise<string>,
) => {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null)
  const [now, setNow] = useState(Date.now)

  useEffect(() => {
    if (!target) return
    let cancelled = false
    let nextPoll: number | undefined
    const refresh = async () => {
      const [simulation, sparkplug] = await Promise.allSettled([
        getThingNamedShadow(resolveIdToken, target.deviceId, 'simulation'),
        getThingNamedShadow(resolveIdToken, target.deviceId, 'sparkplug'),
      ])
      if (cancelled) return
      setSnapshot({
        target,
        session: simulation.status === 'fulfilled' ? readVirtualQuadSession(simulation.value) : null,
        sparkplug: sparkplug.status === 'fulfilled' ? sparkplug.value : null,
      })
      setNow(Date.now())
      nextPoll = window.setTimeout(() => { void refresh() }, 1_000)
    }
    void refresh()
    const countdown = window.setInterval(() => setNow(Date.now()), 1_000)
    return () => {
      cancelled = true
      window.clearTimeout(nextPoll)
      window.clearInterval(countdown)
    }
  }, [target, resolveIdToken])

  const current = target && snapshot?.target === target ? snapshot : null
  const expiresAt = current?.session?.availabilityExpiresAtMs
  useEffect(() => {
    if (!expiresAt || expiresAt <= Date.now()) return
    const timer = window.setTimeout(() => setNow(Date.now()), expiresAt - Date.now())
    return () => window.clearTimeout(timer)
  }, [expiresAt])
  return {
    session: current?.session ?? null,
    sparkplug: current?.sparkplug ?? null,
    fresh: current ? isVirtualQuadProjectionFresh(current.target, current.session, current.sparkplug, now) : false,
    now,
  }
}
