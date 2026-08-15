import type { DeviceWebAdapter } from '../../../office/src/device-adapter'
import VideoPanel from '../../../office/src/VideoPanel'
import {
  buildBoardVideoChannelName,
  buildMavlinkChannelName,
  extractReportedBatteryMv,
  extractReportedBoardPower,
  extractReportedBoardWifiOnline,
  extractReportedMcuOnline,
  extractReportedMcuPower,
} from './app-model'
import CyberbrickPanel from './CyberbrickPanel'

const cyberbrickDeviceAdapter: DeviceWebAdapter = {
  type: 'cyberbrick',
  displayName: 'Cyberbrick',
  buildVideoChannelName: buildBoardVideoChannelName,
  buildMavlinkChannelName,
  canUseBoardVideo: (reportedRedcon) => reportedRedcon === 1,
  // Cyberbrick owns a distinct MAVLink data peer. Keeping this false prevents
  // the Unit-only MCP/cmd_vel keyboard path from being initialized here.
  canUseDriveControl: () => false,
  extractTelemetry: (shadow) => ({
    reportedBatteryMv: extractReportedBatteryMv(shadow),
    reportedBoardPower: extractReportedBoardPower(shadow),
    reportedBoardOnline: extractReportedBoardWifiOnline(shadow),
    reportedMcuOnline: extractReportedMcuOnline(shadow),
    reportedMcuPower: extractReportedMcuPower(shadow),
  }),
  getAutoOpenState: ({
    detailRedcon,
    hasActiveSession,
    nextRedcon,
    routeKind,
  }) => {
    if (
      routeKind !== 'device' ||
      !hasActiveSession ||
      detailRedcon === null ||
      (nextRedcon !== 1 && nextRedcon !== 2)
    ) {
      return null
    }
    return {
      isDetailPanelOpen: true,
      isBoardVideoExpanded: nextRedcon === 1,
    }
  },
  shouldCloseDetail: ({ detailRedcon, reportedRedcon }) =>
    detailRedcon === null || (reportedRedcon !== 1 && reportedRedcon !== 2),
  renderDetail: (props) => <CyberbrickPanel {...props} />,
  renderVideo: ({
    debugEnabled,
    onRuntimeError,
    resolveIdToken,
    videoChannelName,
  }) => (
    <VideoPanel
      channelName={videoChannelName}
      debugEnabled={debugEnabled}
      onRuntimeError={onRuntimeError}
      resolveIdToken={resolveIdToken}
    />
  ),
}

export default cyberbrickDeviceAdapter
