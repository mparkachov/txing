import cloudMcuDeviceAdapter from '../../devices/cloud-mcu/web/cloud-mcu-adapter'
import unitDeviceAdapter from '../../devices/unit/web/unit-adapter'
import weatherDeviceAdapter from '../../devices/weather/web/weather-adapter'
import powerDeviceAdapter from '../../devices/power/web/power-adapter'
import type { DeviceWebAdapter } from './device-adapter'

const installedDeviceAdapters: readonly DeviceWebAdapter[] = [
  cloudMcuDeviceAdapter,
  unitDeviceAdapter,
  weatherDeviceAdapter,
  powerDeviceAdapter,
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
