export type TrackIndicatorPresentation = {
  toneClass: 'status-track-forward' | 'status-track-reverse' | 'status-track-idle'
  intensity: number
  ariaLabel: string
}

export type TxingReportedPowerInputs = {
  reportedRedcon: number | null
  reportedMcuPower: boolean | null
  reportedBoardPower: boolean | null
  reportedBoardWifiOnline: boolean | null
}

export type TxingPowerTransitionInputs = {
  targetRedcon: number | null
  reportedRedcon: number | null
}

export type TxingTargetRedconInputs = {
  targetRedcon: number | null
  reportedRedcon: number | null
}

type RedconDescriptor = {
  colorName: string
  postureName: string
  toneClass: string
}

const redconDescriptors: Record<1 | 2 | 3 | 4, RedconDescriptor> = {
  1: {
    colorName: 'Red',
    postureName: 'Hot Rig',
    toneClass: 'status-txing-redcon-1',
  },
  2: {
    colorName: 'Orange',
    postureName: 'Ember Watch',
    toneClass: 'status-txing-redcon-2',
  },
  3: {
    colorName: 'Yellow',
    postureName: 'Torch-Up',
    toneClass: 'status-txing-redcon-3',
  },
  4: {
    colorName: 'Green',
    postureName: 'Cold Camp',
    toneClass: 'status-txing-redcon-4',
  },
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null

const extractReportedState = (shadow: unknown): Record<string, unknown> | null => {
  if (!isRecord(shadow)) {
    return null
  }
  const state = shadow.state
  if (!isRecord(state)) {
    return null
  }
  const reported = state.reported
  return isRecord(reported) ? reported : null
}

const extractNamedShadowReportedState = (
  shadow: unknown,
  shadowName: 'sparkplug' | 'mcu' | 'board' | 'video',
): Record<string, unknown> | null => {
  if (!isRecord(shadow) || !isRecord(shadow.namedShadows)) {
    return null
  }
  const namedShadow = shadow.namedShadows[shadowName]
  if (!isRecord(namedShadow) || !isRecord(namedShadow.state)) {
    return null
  }
  const reported = namedShadow.state.reported
  return isRecord(reported) ? reported : null
}

export const extractReportedDevice = (shadow: unknown): Record<string, unknown> | null => {
  const reported = extractReportedState(shadow)
  if (!reported) {
    return null
  }
  const device = reported.device
  return isRecord(device) ? device : null
}

export const extractReportedMcu = (shadow: unknown): Record<string, unknown> | null => {
  const namedMcu = extractNamedShadowReportedState(shadow, 'mcu')
  if (namedMcu) {
    return namedMcu
  }
  const device = extractReportedDevice(shadow)
  if (!device) {
    return null
  }
  const mcu = device.mcu
  return isRecord(mcu) ? mcu : null
}

export const extractReportedBoard = (shadow: unknown): Record<string, unknown> | null => {
  const namedBoard = extractNamedShadowReportedState(shadow, 'board')
  if (namedBoard) {
    return namedBoard
  }
  const device = extractReportedDevice(shadow)
  if (!device) {
    return null
  }
  const board = device.board
  return isRecord(board) ? board : null
}

const extractSparkplugReportedState = (shadow: unknown): Record<string, unknown> | null =>
  extractNamedShadowReportedState(shadow, 'sparkplug') ?? extractReportedState(shadow)

const extractSparkplugPayload = (shadow: unknown): Record<string, unknown> | null => {
  const reported = extractSparkplugReportedState(shadow)
  if (!reported) {
    return null
  }
  const payload = reported.payload
  return isRecord(payload) ? payload : null
}

const extractSparkplugMetrics = (shadow: unknown): Record<string, unknown> | null => {
  const payload = extractSparkplugPayload(shadow)
  if (!payload) {
    return null
  }
  const metrics = payload.metrics
  return isRecord(metrics) ? metrics : null
}

const coerceRedcon = (value: unknown): number | null => {
  if (typeof value !== 'number' || !Number.isInteger(value)) {
    return null
  }
  return value >= 1 && value <= 4 ? value : null
}

export const extractReportedRedcon = (shadow: unknown): number | null => {
  const metrics = extractSparkplugMetrics(shadow)
  if (metrics) {
    const redcon = coerceRedcon(metrics.redcon)
    if (redcon !== null) {
      return redcon
    }
  }
  return null
}

export const getTxingRedconToneClass = (redcon: number | null): string => {
  if (redcon === null) {
    return 'status-txing-redcon-unknown'
  }

  const descriptor = redconDescriptors[redcon as 1 | 2 | 3 | 4]
  return descriptor?.toneClass ?? 'status-txing-redcon-unknown'
}

export const describeRedcon = (redcon: number | null): string => {
  if (redcon === null) {
    return 'REDCON unavailable'
  }

  const descriptor = redconDescriptors[redcon as 1 | 2 | 3 | 4]
  if (!descriptor) {
    return 'REDCON unavailable'
  }
  return `REDCON ${redcon} · ${descriptor.postureName} · ${descriptor.colorName}`
}

export const deriveTxingPoweredOn = ({
  reportedRedcon,
  reportedMcuPower,
  reportedBoardPower,
  reportedBoardWifiOnline,
}: TxingReportedPowerInputs): boolean => {
  if (reportedRedcon !== null) {
    return reportedRedcon < 4
  }
  return (
    reportedMcuPower === true ||
    reportedBoardPower === true ||
    reportedBoardWifiOnline === true
  )
}

export const deriveTxingPowerTransitionPending = ({
  targetRedcon,
  reportedRedcon,
}: TxingPowerTransitionInputs): boolean => {
  if (targetRedcon === null) {
    return false
  }
  return !hasReachedTargetRedcon({
    targetRedcon,
    reportedRedcon,
  })
}

export const hasReachedTargetRedcon = ({
  targetRedcon,
  reportedRedcon,
}: TxingTargetRedconInputs): boolean => {
  if (targetRedcon === null) {
    return false
  }
  if (reportedRedcon === null) {
    return false
  }
  if (targetRedcon === 4) {
    return reportedRedcon === 4
  }
  return reportedRedcon <= targetRedcon
}

export const extractReportedBoardPower = (shadow: unknown): boolean | null => {
  const board = extractReportedBoard(shadow)
  if (!board) {
    return null
  }
  return typeof board.power === 'boolean' ? board.power : null
}

export const extractReportedMcuPower = (shadow: unknown): boolean | null => {
  const mcu = extractReportedMcu(shadow)
  if (!mcu) {
    return null
  }
  return typeof mcu.power === 'boolean' ? mcu.power : null
}

export const extractReportedMcuOnline = (shadow: unknown): boolean | null => {
  const mcu = extractReportedMcu(shadow)
  if (!mcu) {
    return null
  }
  return typeof mcu.online === 'boolean' ? mcu.online : null
}

export const extractReportedBatteryMv = (shadow: unknown): number | null => {
  const metrics = extractSparkplugMetrics(shadow)
  if (!metrics) {
    return null
  }
  return typeof metrics.batteryMv === 'number' ? metrics.batteryMv : null
}

export const extractReportedBoardWifiOnline = (shadow: unknown): boolean | null => {
  const board = extractReportedBoard(shadow)
  if (!board) {
    return null
  }
  const wifi = board.wifi
  return isRecord(wifi) && typeof wifi.online === 'boolean' ? wifi.online : null
}

export const getTrackIndicatorPresentation = (
  speed: number | null,
  sideLabel: 'Left' | 'Right',
): TrackIndicatorPresentation => {
  if (speed === null) {
    return {
      toneClass: 'status-track-idle',
      intensity: 0,
      ariaLabel: `${sideLabel} track speed unavailable`,
    }
  }

  if (speed === 0) {
    return {
      toneClass: 'status-track-idle',
      intensity: 0,
      ariaLabel: `${sideLabel} track idle`,
    }
  }

  const magnitude = Math.abs(speed)
  return {
    toneClass: speed > 0 ? 'status-track-forward' : 'status-track-reverse',
    intensity: magnitude / 100,
    ariaLabel: `${sideLabel} track ${speed > 0 ? 'forward' : 'reverse'} ${magnitude} percent`,
  }
}

export const buildBoardVideoChannelName = (deviceId: string): string => `${deviceId}-board-video`
