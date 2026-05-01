import timeDeviceAdapter from '../../devices/time/web/time-adapter'
import unitDeviceAdapter from '../../devices/unit/web/unit-adapter'
import type { DeviceWebAdapter } from './device-adapter'

const installedDeviceAdapters: readonly DeviceWebAdapter[] = [
  timeDeviceAdapter,
  unitDeviceAdapter,
]

const adaptersByType = new Map(
  installedDeviceAdapters.map((adapter) => [adapter.type, adapter]),
)

export const getDeviceWebAdapter = (
  thingTypeName: string | null | undefined,
): DeviceWebAdapter | null => {
  if (!thingTypeName) {
    return null
  }
  return adaptersByType.get(thingTypeName) ?? null
}

export const listDeviceWebAdapters = (): readonly DeviceWebAdapter[] =>
  installedDeviceAdapters
