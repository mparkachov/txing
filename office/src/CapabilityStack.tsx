import type { ReactElement } from 'react'
import type { ShadowName } from './shadow-protocol'
import { extractSparkplugCapabilityAvailability } from './sparkplug-model'

export type CapabilityStackStatus = 'loading' | 'ready' | 'error'

type CapabilityStackProps = {
  thingName: string
  label: string
  capabilities: readonly ShadowName[]
  sparkplugShadow: unknown | null
  sparkplugShadowStatus: CapabilityStackStatus
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
        const isActive = availability === true
        const statusLabel = isActive ? 'active' : 'inactive'
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
