import { extractReportedState } from '../../../office/src/sparkplug-model'

const field = (value: unknown, key: string): unknown =>
  value !== null && typeof value === 'object' && key in value
    ? (value as Record<string, unknown>)[key]
    : undefined

// The agent controller samples its runtime on the one-minute repair pass.
const sampleMaxAgeMs = 75_000

export type VirtualQuadAgentStatus =
  'stopped' | 'stopping' | 'expired' | 'error' | 'unavailable' | 'starting' | 'running' | 'connecting'

export function readVirtualQuadAgentStatus(
  shadow: unknown, sessionId: string | null, nowMs: number,
): VirtualQuadAgentStatus {
  const reported = extractReportedState(shadow)
  const lifecycle = field(reported?.lifecycle, 'state')
  if (lifecycle === 'stopped' || lifecycle === 'stopping' || lifecycle === 'expired' || lifecycle === 'error') {
    return lifecycle
  }
  if (!reported || !sessionId || field(reported.activation, 'id') !== sessionId) return 'unavailable'
  const deadline = field(reported.activation, 'deadline')
  if (typeof deadline !== 'number' || !Number.isSafeInteger(deadline)) return 'unavailable'
  if (deadline * 1000 <= nowMs) return 'expired'
  if (lifecycle === 'starting') return 'starting'
  if (lifecycle !== 'running') return 'unavailable'

  const runId = field(reported.run, 'id')
  const sampledAt = field(reported.runtime, 'sampledAt')
  if (typeof runId !== 'string' || !runId || field(reported.runtime, 'runId') !== runId ||
    typeof sampledAt !== 'number' || !Number.isSafeInteger(sampledAt)) return 'unavailable'
  const age = nowMs - sampledAt * 1000
  if (age < 0 || age >= sampleMaxAgeMs) return 'unavailable'
  return field(field(reported.runtime, 'mavlink'), 'state') === 'connected' &&
    field(field(reported.runtime, 'video'), 'state') === 'connected'
    ? 'running'
    : 'connecting'
}
