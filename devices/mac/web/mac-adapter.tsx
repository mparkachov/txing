import type { DeviceWebAdapter } from '../../../office/src/device-adapter'
import VideoPanel from '../../../office/src/VideoPanel'
import {
  buildBoardVideoChannelName,
  extractReportedBoardPower,
  extractReportedBoardWifiOnline,
} from './mac-model'
import MacPanel from './MacPanel'

const macDeviceAdapter: DeviceWebAdapter = {
  type: 'mac',
  displayName: 'Mac',
  buildVideoChannelName: buildBoardVideoChannelName,
  canUseBoardVideo: (reportedRedcon) => reportedRedcon === 1,
  canUseDriveControl: () => false,
  extractTelemetry: (shadow) => ({
    reportedBatteryMv: null,
    reportedBoardPower: extractReportedBoardPower(shadow),
    reportedBoardOnline: extractReportedBoardWifiOnline(shadow),
    reportedMcuOnline: null,
    reportedMcuPower: null,
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
  renderDetail: (props) => (
    <MacPanel
      isBoardVideoExpanded={props.isBoardVideoExpanded}
      isDebugEnabled={props.isDebugEnabled}
      mcpTransport={props.mcpTransport}
      onBoardVideoRuntimeError={props.onBoardVideoRuntimeError}
      onToggleDebug={props.onToggleDebug}
      reportedBoardOnline={props.reportedBoardOnline}
      reportedRedcon={props.reportedRedcon}
      resolveIdToken={props.resolveIdToken}
      videoChannelName={props.videoChannelName}
    />
  ),
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

export default macDeviceAdapter
