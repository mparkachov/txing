import type { DeviceWebAdapter } from '../../../web/src/device-adapter'
import VideoPanel from '../../../web/src/VideoPanel'
import {
  buildBoardVideoChannelName,
  extractReportedBatteryMv,
  extractReportedBoardPower,
  extractReportedBoardWifiOnline,
  extractReportedMcuOnline,
  extractReportedMcuPower,
} from './app-model'
import TxingPanel from './TxingPanel'

const unitDeviceAdapter: DeviceWebAdapter = {
  type: 'unit',
  displayName: 'Unit',
  buildVideoChannelName: buildBoardVideoChannelName,
  canUseBoardVideo: (reportedRedcon) => reportedRedcon === 1,
  extractTelemetry: (shadow) => ({
    reportedBatteryMv: extractReportedBatteryMv(shadow),
    reportedBoardPower: extractReportedBoardPower(shadow),
    reportedBoardOnline: extractReportedBoardWifiOnline(shadow),
    reportedMcuOnline: extractReportedMcuOnline(shadow),
    reportedMcuPower: extractReportedMcuPower(shadow),
  }),
  getAutoOpenState: ({
    hasActiveSession,
    nextRedcon,
    previousRedcon,
    routeKind,
  }) => {
    if (
      routeKind !== 'device' ||
      !hasActiveSession ||
      previousRedcon === 1 ||
      nextRedcon !== 1
    ) {
      return null
    }
    return {
      isDetailPanelOpen: true,
      isBoardVideoExpanded: true,
    }
  },
  shouldCloseDetail: (reportedRedcon) => reportedRedcon !== 1,
  renderDetail: (props) => <TxingPanel {...props} />,
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

export default unitDeviceAdapter
