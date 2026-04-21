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
  desiredRedcon: number | null
  reportedRedcon: number | null
}

export type PrimaryReportedRedconInputs = {
  sparkplugReportedRedcon: number | null
  shadowReportedRedcon: number | null
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

const extractDesiredState = (shadow: unknown): Record<string, unknown> | null => {
  if (!isRecord(shadow)) {
    return null
  }
  const state = shadow.state
  if (!isRecord(state)) {
    return null
  }
  const desired = state.desired
  return isRecord(desired) ? desired : null
}

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

export const extractReportedMcu = (shadow: unknown): Record<string, unknown> | null => {
  const reported = extractReportedState(shadow)
  if (!reported) {
    return null
  }
  const mcu = reported.mcu
  return isRecord(mcu) ? mcu : null
}

export const extractReportedBoard = (shadow: unknown): Record<string, unknown> | null => {
  const reported = extractReportedState(shadow)
  if (!reported) {
    return null
  }
  const board = reported.board
  return isRecord(board) ? board : null
}

export const extractDesiredRedcon = (shadow: unknown): number | null => {
  const desired = extractDesiredState(shadow)
  if (!desired) {
    return null
  }
  const redcon = desired.redcon
  if (typeof redcon !== 'number' || !Number.isInteger(redcon)) {
    return null
  }
  return redcon >= 1 && redcon <= 4 ? redcon : null
}

export const extractDesiredBoardPower = (shadow: unknown): boolean | null => {
  const desired = extractDesiredState(shadow)
  if (!desired) {
    return null
  }
  const board = desired.board
  if (!isRecord(board)) {
    return null
  }
  return typeof board.power === 'boolean' ? board.power : null
}

export const extractReportedRedcon = (shadow: unknown): number | null => {
  const reported = extractReportedState(shadow)
  if (!reported) {
    return null
  }
  const redcon = reported.redcon
  if (typeof redcon !== 'number' || !Number.isInteger(redcon)) {
    return null
  }
  return redcon >= 1 && redcon <= 4 ? redcon : null
}

export const selectPrimaryReportedRedcon = ({
  sparkplugReportedRedcon,
  shadowReportedRedcon,
}: PrimaryReportedRedconInputs): number | null =>
  sparkplugReportedRedcon ?? shadowReportedRedcon

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
  desiredRedcon,
  reportedRedcon,
}: TxingPowerTransitionInputs): boolean => {
  if (desiredRedcon === null) {
    return false
  }
  if (reportedRedcon === null) {
    return true
  }
  if (desiredRedcon === 4) {
    return reportedRedcon !== 4
  }
  return reportedRedcon > desiredRedcon
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
  const reported = extractReportedState(shadow)
  if (!reported) {
    return null
  }
  return typeof reported.batteryMv === 'number' ? reported.batteryMv : null
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
