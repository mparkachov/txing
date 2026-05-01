import type { DeviceWebAdapter } from '../../../web/src/device-adapter'
import TimePanel from './TimePanel'

const timeDeviceAdapter: DeviceWebAdapter = {
  type: 'time',
  displayName: 'Time',
  buildVideoChannelName: (deviceId) => `${deviceId}-time`,
  canUseBoardVideo: () => false,
  extractTelemetry: () => ({
    reportedBatteryMv: null,
    reportedBoardPower: null,
    reportedBoardOnline: null,
    reportedMcuOnline: null,
    reportedMcuPower: null,
  }),
  getAutoOpenState: ({ hasActiveSession, routeKind }) => {
    if (routeKind !== 'device' || !hasActiveSession) {
      return null
    }
    return {
      isDetailPanelOpen: true,
      isBoardVideoExpanded: false,
    }
  },
  shouldCloseDetail: () => false,
  renderDetail: (props) => (
    <TimePanel
      callMcpTool={props.callMcpTool}
      isShadowConnected={props.isShadowConnected}
      reportedRedcon={props.reportedRedcon}
      shadow={props.shadow}
    />
  ),
  renderVideo: () => (
    <section className="time-device-panel" aria-label="Time device video">
      <div className="time-device-metric">
        <span className="time-device-metric-label">Video</span>
        <span className="time-device-metric-value">unsupported</span>
      </div>
    </section>
  ),
}

export default timeDeviceAdapter
