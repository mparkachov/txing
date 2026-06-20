import type { DeviceWebAdapter } from '../../../office/src/device-adapter'
import powerDeviceAdapter from '../../power/web/power-adapter'

const powerSiDeviceAdapter: DeviceWebAdapter = {
  ...powerDeviceAdapter,
  type: 'power-si',
  displayName: 'Power SI',
  buildVideoChannelName: (deviceId) => `${deviceId}-power-si`,
}

export default powerSiDeviceAdapter
