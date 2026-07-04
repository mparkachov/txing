const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null

const extractBoardReportedState = (shadow: unknown): Record<string, unknown> | null => {
  if (!isRecord(shadow) || !isRecord(shadow.namedShadows)) {
    return null
  }
  const board = shadow.namedShadows.board
  if (!isRecord(board) || !isRecord(board.state)) {
    return null
  }
  const reported = board.state.reported
  return isRecord(reported) ? reported : null
}

export const extractReportedBoardPower = (shadow: unknown): boolean | null => {
  const board = extractBoardReportedState(shadow)
  if (!board) {
    return null
  }
  return typeof board.power === 'boolean' ? board.power : null
}

export const extractReportedBoardWifiOnline = (shadow: unknown): boolean | null => {
  const board = extractBoardReportedState(shadow)
  if (!board) {
    return null
  }
  const wifi = board.wifi
  return isRecord(wifi) && typeof wifi.online === 'boolean' ? wifi.online : null
}

export const buildBoardVideoChannelName = (deviceId: string): string => `${deviceId}-board-video`
