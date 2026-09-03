import type { DeviceWebAdapter } from '../../../office/src/device-adapter'
import VideoPanel from '../../../office/src/VideoPanel'
import CyberbrickPanel from '../../cyberbrick/web/CyberbrickPanel'
import { buildMavlinkChannelName } from '../../cyberbrick/web/app-model'
import {
  buildBoardVideoChannelName,
  extractReportedBatteryMv,
  extractReportedBoardPower,
  extractReportedBoardWifiOnline,
  extractReportedMcuOnline,
  extractReportedMcuPower,
} from '../../unit/web/app-model'

const tbotDeviceAdapter: DeviceWebAdapter = {
  type: 'tbot',
  displayName: 'TBot',
  buildVideoChannelName: buildBoardVideoChannelName,
  buildMavlinkChannelName,
  canUseBoardVideo: (reportedRedcon) => reportedRedcon === 1,
  // TBot owns motor control through its MAVLink peer. Returning false keeps
  // the Unit-only MCP/cmd_vel session and keyboard handlers out of this path.
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
  renderDetail: (props) => (
    <CyberbrickPanel
      {...props}
      deviceLabel="TBOT"
      deviceName="TBot"
      watchTransport="Thread"
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

export default tbotDeviceAdapter
