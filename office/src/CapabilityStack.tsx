import type { ReactElement } from 'react'
import type { QuadMavlinkStatus } from '../../devices/virtual-quad/web/virtual-quad-media-status'
import type { VirtualQuadAgentStatus } from './agent-shadow-status'
import type { ShadowName } from './shadow-protocol'
import { extractSparkplugCapabilityAvailability } from './sparkplug-model'

export type CapabilityStackStatus = 'loading' | 'ready' | 'error'

type CapabilityStackProps = {
  thingName: string
  label: string
  capabilities: readonly ShadowName[]
  sparkplugShadow: unknown | null
  sparkplugShadowStatus: CapabilityStackStatus
  inactiveCapabilities?: readonly ShadowName[]
  agentStatus?: VirtualQuadAgentStatus
  mavlinkStatus?: QuadMavlinkStatus
  className?: string
}

const capabilityDisplayAttributes: Partial<Record<ShadowName, { visible: boolean }>> = {
  sparkplug: { visible: false },
}

const isCapabilityVisible = (capability: ShadowName): boolean =>
  capabilityDisplayAttributes[capability]?.visible ?? true

function CapabilityStack({
  thingName,
  label,
  capabilities,
  sparkplugShadow,
  sparkplugShadowStatus,
  inactiveCapabilities,
  agentStatus,
  mavlinkStatus,
  className,
}: CapabilityStackProps): ReactElement | null {
  const displayCapabilities = [...capabilities].filter(isCapabilityVisible).reverse()

  if (displayCapabilities.length === 0) {
    return null
  }

  const classes = ['catalog-status-capabilities', className].filter(Boolean).join(' ')

  return (
    <span className={classes} aria-label={`Capability status for ${label}`}>
      {displayCapabilities.map((capability) => {
        const availability =
          sparkplugShadowStatus === 'ready' && !inactiveCapabilities?.includes(capability)
            ? extractSparkplugCapabilityAvailability(sparkplugShadow, capability)
            : null
        const observedAgentStatus = capability === 'agent' ? agentStatus : undefined
        const browserMavlinkStatus = capability === 'mavlink' ? mavlinkStatus : undefined
        const isActive = observedAgentStatus !== undefined ? observedAgentStatus === 'running'
          : browserMavlinkStatus !== undefined ? browserMavlinkStatus === 'live' : availability === true
        const statusLabel = observedAgentStatus ?? browserMavlinkStatus ?? (isActive ? 'active' : 'inactive')
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
