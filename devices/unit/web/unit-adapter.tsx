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
    detailRedcon,
    hasActiveSession,
    nextRedcon,
    routeKind,
  }) => {
    if (
      routeKind !== 'device' ||
      !hasActiveSession ||
      detailRedcon === null ||
      nextRedcon !== detailRedcon
    ) {
      return null
    }
    return {
      isDetailPanelOpen: true,
      isBoardVideoExpanded: nextRedcon === 1,
    }
  },
  shouldCloseDetail: ({ detailRedcon, reportedRedcon }) =>
    detailRedcon === null || reportedRedcon !== detailRedcon,
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
