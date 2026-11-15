import type { ReactElement } from 'react'
import type { AgentCapabilityStatus } from './device-adapter'
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
  className?: string
}

function CapabilityStack({
  thingName,
  label,
  capabilities,
  sparkplugShadow,
  sparkplugShadowStatus,
  agentStatus,
  className,
}: CapabilityStackProps): ReactElement | null {
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
        const status = capability === 'agent' ? agentStatus : undefined
        const isActive = status?.active ?? (availability === true)
        const statusLabel = status?.label ?? (isActive ? 'active' : 'inactive')
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
