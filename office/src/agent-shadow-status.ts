import { extractReportedState } from './sparkplug-model'

const field = (value: unknown, key: string): unknown =>
  value !== null && typeof value === 'object' && key in value
    ? (value as Record<string, unknown>)[key]
    : undefined

// The agent controller samples its runtime on the one-minute repair pass.
const sampleMaxAgeMs = 75_000

export type AgentCapabilityStatus =
  | { active: true; label: 'running'; expiresAtMs: number }
  | { active: false; label: 'stopped' | 'stopping' | 'expired' | 'error' | 'unavailable' | 'starting' | 'connecting' }

export function readAgentStatus(shadow: unknown, nowMs: number, sessionId?: string | null): AgentCapabilityStatus {
  const reported = extractReportedState(shadow)
  const lifecycle = field(reported?.lifecycle, 'state')
  if (lifecycle === 'stopped' || lifecycle === 'stopping' || lifecycle === 'expired' || lifecycle === 'error') {
    return { active: false, label: lifecycle }
  }
  const activationId = field(reported?.activation, 'id')
  if (!reported || typeof activationId !== 'string' || !activationId ||
    (sessionId !== undefined && activationId !== sessionId)) return { active: false, label: 'unavailable' }
  const deadline = field(reported.activation, 'deadline')
  if (typeof deadline !== 'number' || !Number.isSafeInteger(deadline)) return { active: false, label: 'unavailable' }
  if (deadline * 1000 <= nowMs) return { active: false, label: 'expired' }
  if (lifecycle === 'starting') return { active: false, label: 'starting' }
  if (lifecycle !== 'running') return { active: false, label: 'unavailable' }

  const runId = field(reported.run, 'id')
  const sampledAt = field(reported.runtime, 'sampledAt')
  if (typeof runId !== 'string' || !runId || field(reported.runtime, 'runId') !== runId ||
    typeof sampledAt !== 'number' || !Number.isSafeInteger(sampledAt)) return { active: false, label: 'unavailable' }
  const age = nowMs - sampledAt * 1000
  if (age < 0 || age >= sampleMaxAgeMs) return { active: false, label: 'unavailable' }
  if (field(field(reported.runtime, 'mavlink'), 'state') !== 'connected' ||
    field(field(reported.runtime, 'video'), 'state') !== 'connected') return { active: false, label: 'connecting' }
  return { active: true, label: 'running', expiresAtMs: Math.min(deadline * 1000, sampledAt * 1000 + sampleMaxAgeMs) }
}
