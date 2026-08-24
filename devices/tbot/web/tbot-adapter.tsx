import type { DeviceWebAdapter } from '../../../office/src/device-adapter'
import unitDeviceAdapter from '../../unit/web/unit-adapter'
import TxingPanel from '../../unit/web/TxingPanel'

const tbotDeviceAdapter: DeviceWebAdapter = {
  ...unitDeviceAdapter,
  type: 'tbot',
  displayName: 'TBot',
  renderDetail: (props) => (
    <TxingPanel {...props} watchTransport="Thread" deviceLabel="TBOT" />
  ),
}

export default tbotDeviceAdapter
