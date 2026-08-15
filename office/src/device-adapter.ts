import type { ReactElement } from 'react'
import type { McpTransportKind } from './mcp-descriptor'
import type { RobotControlState } from './shadow-api'

export type DeviceTelemetry = {
  reportedBatteryMv: number | null
  reportedBoardPower: boolean | null
  reportedBoardOnline: boolean | null
  reportedMcuOnline: boolean | null
  reportedMcuPower: boolean | null
}

export type DeviceAutoOpenInput = {
  detailRedcon: number | null
  hasActiveSession: boolean
  nextRedcon: number | null
  routeKind: 'device' | 'device_video'
}

export type DeviceAutoOpenState = {
  isDetailPanelOpen: boolean
  isBoardVideoExpanded: boolean
}

export type DeviceDetailCloseInput = {
  detailRedcon: number | null
  reportedRedcon: number | null
}

export type DeviceDetailRenderProps = {
  callMcpTool: (name: string, args?: Record<string, unknown>) => Promise<unknown>
  isBoardVideoExpanded: boolean
  isDebugEnabled: boolean
  mavlinkActor: string
  mavlinkChannelName: string
  mavlinkRegion: string
  isShadowConnected: boolean
  isTakeControlPending: boolean
  mcpTransport: McpTransportKind | null
  onBoardVideoRuntimeError: (message: string) => void
  onTakeControl: () => void
  onToggleDebug: () => void
  robotControl: RobotControlState | null
  reportedBatteryMv: number | null
  reportedBoardLeftTrackSpeed: number | null
  reportedBoardOnline: boolean | null
  reportedBoardRightTrackSpeed: number | null
  reportedRedcon: number | null
  reportedMcuOnline: boolean | null
  resolveIdToken: () => Promise<string>
  shadow: unknown
  videoChannelName: string
}

export type DeviceVideoRenderProps = {
  debugEnabled: boolean
  onRuntimeError: (message: string) => void
  resolveIdToken: () => Promise<string>
  videoChannelName: string
}

export type DeviceWebAdapter = {
  type: string
  displayName: string
  buildVideoChannelName: (deviceId: string) => string
  buildMavlinkChannelName?: (deviceId: string) => string
  canUseBoardVideo: (reportedRedcon: number | null) => boolean
  canUseDriveControl: (reportedRedcon: number | null) => boolean
  extractTelemetry: (shadow: unknown) => DeviceTelemetry
  getAutoOpenState: (input: DeviceAutoOpenInput) => DeviceAutoOpenState | null
  shouldCloseDetail: (input: DeviceDetailCloseInput) => boolean
  renderDetail: (props: DeviceDetailRenderProps) => ReactElement
  renderVideo: (props: DeviceVideoRenderProps) => ReactElement
}

type BoardVideoTeardownContext = {
  canUseBoardVideo: (reportedRedcon: number | null) => boolean
  pendingTargetRedcon: 1 | 2 | 3 | 4 | null
  reportedRedcon: number | null
}

// A board RTC failure is the trailing edge of an expected teardown when
// the device has already left its video-capable posture or office itself
// has commanded it out of one. The browser's ICE timeout races both the
// clean data channel close and the shadow update (a REDCON command can
// block behind the worker teardown before new state publishes), so
// neither signal alone is sufficient.
export const shouldSuppressBoardVideoRuntimeError = ({
  canUseBoardVideo,
  pendingTargetRedcon,
  reportedRedcon,
}: BoardVideoTeardownContext): boolean => {
  if (pendingTargetRedcon !== null && !canUseBoardVideo(pendingTargetRedcon)) {
    return true
  }
  return reportedRedcon !== null && !canUseBoardVideo(reportedRedcon)
}
