import type { DeviceWebAdapter } from '../../../office/src/device-adapter'
import powerDeviceAdapter from '../../power/web/power-adapter'

const powerNrfDeviceAdapter: DeviceWebAdapter = {
  ...powerDeviceAdapter,
  type: 'power-nrf',
  displayName: 'Power nRF',
  buildVideoChannelName: (deviceId) => `${deviceId}-power-nrf`,
}

export default powerNrfDeviceAdapter
