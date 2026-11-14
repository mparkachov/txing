import type { ReactElement } from 'react'
import type { CapabilityStatuses } from './device-adapter'
import type { ShadowName } from './shadow-protocol'
import { extractSparkplugCapabilityAvailability } from './sparkplug-model'

export type CapabilityStackStatus = 'loading' | 'ready' | 'error'

type CapabilityStackProps = {
  thingName: string
  label: string
  capabilities: readonly ShadowName[]
  sparkplugShadow: unknown | null
  sparkplugShadowStatus: CapabilityStackStatus
  capabilityStatuses?: CapabilityStatuses
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
  capabilityStatuses,
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
          sparkplugShadowStatus === 'ready'
            ? extractSparkplugCapabilityAvailability(sparkplugShadow, capability)
            : null
        const status = capabilityStatuses?.[capability]
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
