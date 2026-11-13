import type { DeviceWebAdapter } from '../../../office/src/device-adapter'

const virtualQuadAdapter: DeviceWebAdapter = {
  type: 'virtual-quad',
  displayName: 'Virtual Quadcopter',
  buildVideoChannelName: (deviceId) => `${deviceId}-board-video`,
  buildMavlinkChannelName: (deviceId) => `${deviceId}-mavlink`,
  canUseBoardVideo: () => false,
  canUseDriveControl: () => false,
  extractTelemetry: () => ({
    reportedBatteryMv: null,
    reportedBoardPower: null,
    reportedBoardOnline: null,
    reportedMcuOnline: null,
    reportedMcuPower: null,
  }),
  getAutoOpenState: () => null,
  shouldCloseDetail: () => false,
  renderDetail: ({ reportedRedcon }) => (
    <section aria-label="Virtual quadcopter status">
      {reportedRedcon === 4 ? 'Stopped' : 'Unavailable'}
    </section>
  ),
  renderVideo: () => <p>Video unavailable</p>,
}

export default virtualQuadAdapter
