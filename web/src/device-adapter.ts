import type { ReactElement } from 'react'
import type { McpTransportKind } from './mcp-descriptor'

export type DeviceTelemetry = {
  reportedBatteryMv: number | null
  reportedBoardPower: boolean | null
  reportedBoardOnline: boolean | null
  reportedMcuOnline: boolean | null
  reportedMcuPower: boolean | null
}

export type DeviceAutoOpenInput = {
  hasActiveSession: boolean
  nextRedcon: number | null
  previousRedcon: number | null
  routeKind: 'device' | 'device_video'
}

export type DeviceAutoOpenState = {
  isDetailPanelOpen: boolean
  isBoardVideoExpanded: boolean
}

export type DeviceDetailRenderProps = {
  callMcpTool: (name: string, args?: Record<string, unknown>) => Promise<unknown>
  isBoardVideoExpanded: boolean
  isDebugEnabled: boolean
  isShadowConnected: boolean
  mcpTransport: McpTransportKind | null
  onBoardVideoRuntimeError: (message: string) => void
  onToggleDebug: () => void
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
  canUseBoardVideo: (reportedRedcon: number | null) => boolean
  extractTelemetry: (shadow: unknown) => DeviceTelemetry
  getAutoOpenState: (input: DeviceAutoOpenInput) => DeviceAutoOpenState | null
  shouldCloseDetail: (reportedRedcon: number | null) => boolean
  renderDetail: (props: DeviceDetailRenderProps) => ReactElement
  renderVideo: (props: DeviceVideoRenderProps) => ReactElement
}
