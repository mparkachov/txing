import cloudMcuDeviceAdapter from '../../devices/cloud-mcu/web/cloud-mcu-adapter'
import unitDeviceAdapter from '../../devices/unit/web/unit-adapter'
import tbotDeviceAdapter from '../../devices/tbot/web/tbot-adapter'
import cyberbrickDeviceAdapter from '../../devices/cyberbrick/web/cyberbrick-adapter'
import weatherDeviceAdapter from '../../devices/weather/web/weather-adapter'
import powerDeviceAdapter from '../../devices/power/web/power-adapter'
import powerSiDeviceAdapter from '../../devices/power-si/web/power-si-adapter'
import powerNrfDeviceAdapter from '../../devices/power-nrf/web/power-nrf-adapter'
import macDeviceAdapter from '../../devices/mac/web/mac-adapter'
import type { DeviceWebAdapter } from './device-adapter'

const installedDeviceAdapters: readonly DeviceWebAdapter[] = [
  cloudMcuDeviceAdapter,
  unitDeviceAdapter,
  tbotDeviceAdapter,
  cyberbrickDeviceAdapter,
  weatherDeviceAdapter,
  powerDeviceAdapter,
  powerSiDeviceAdapter,
  powerNrfDeviceAdapter,
  macDeviceAdapter,
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
