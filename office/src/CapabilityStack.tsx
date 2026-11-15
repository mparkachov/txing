import { useEffect, useState, type ReactElement } from 'react'
import type { AgentCapabilityStatus } from './agent-shadow-status'
import type { ShadowName } from './shadow-protocol'
import { extractSparkplugCapabilityAvailability } from './sparkplug-model'

export type CapabilityStackStatus = 'loading' | 'ready' | 'error'

type CapabilityStackProps = {
  thingName: string
  label: string
  capabilities: readonly ShadowName[]
  sparkplugShadow: unknown | null
  sparkplugShadowStatus: CapabilityStackStatus
  agentStatus?: AgentCapabilityStatus
  simulationExpiresAtMs?: number | null
  className?: string
}

function CapabilityStack({
  thingName,
  label,
  capabilities,
  sparkplugShadow,
  sparkplugShadowStatus,
  agentStatus,
  simulationExpiresAtMs,
  className,
}: CapabilityStackProps): ReactElement | null {
  const [now, setNow] = useState(Date.now)
  const simulationFresh = simulationExpiresAtMs != null && now < simulationExpiresAtMs
  const agentFresh = agentStatus?.active === true && now < agentStatus.expiresAtMs
  const inactiveAgentLabel = agentStatus?.active === false ? agentStatus.label : 'unavailable'
  const nextExpiryMs = Math.min(
    simulationFresh ? simulationExpiresAtMs : Infinity,
    agentFresh ? agentStatus.expiresAtMs : Infinity,
  )
  useEffect(() => {
    if (!Number.isFinite(nextExpiryMs)) return
    const timer = window.setTimeout(() => setNow(Math.max(nextExpiryMs, Date.now())), Math.max(0, nextExpiryMs - Date.now()))
    return () => window.clearTimeout(timer)
  }, [nextExpiryMs])

  const visibleCapabilities = capabilities.filter((capability) => capability !== 'sparkplug')
  if (visibleCapabilities.length === 0) {
    return null
  }

  const classes = ['catalog-status-capabilities', className].filter(Boolean).join(' ')

  return (
    <span className={classes} aria-label={`Capability status for ${label}`}>
      {visibleCapabilities.reverse().map((capability) => {
        const availability =
          sparkplugShadowStatus === 'ready'
            ? extractSparkplugCapabilityAvailability(sparkplugShadow, capability)
            : null
        const isAgent = capability === 'agent'
        const isActive = availability === true && (isAgent ? agentFresh : capability !== 'simulation' || simulationFresh)
        const statusLabel = isAgent ? (isActive ? 'running' : inactiveAgentLabel) : isActive ? 'active' : 'inactive'
        return (
          <span
            key={`${thingName}:${capability}`}
            className={`catalog-status-capability ${
              isActive
                ? 'catalog-status-capability-active'
                : 'catalog-status-capability-inactive'
            }`}
            title={`${capability}: ${statusLabel}`}
          >
            <span className="catalog-status-capability-dot" aria-hidden="true" />
            <span className="catalog-status-capability-label">{capability}</span>
          </span>
        )
      })}
    </span>
  )
}

export default CapabilityStack
