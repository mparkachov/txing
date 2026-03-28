export type BoardVideoRuntime = {
  ready: boolean
  status: 'starting' | 'ready' | 'error' | null
  transport: 'aws-webrtc' | null
  viewerUrl: string | null
  channelName: string | null
  viewerConnected: boolean
  lastError: string | null
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
  if (typeof mcu.online === 'boolean') {
    return mcu.online
  }
  const ble = mcu.ble
  if (!isRecord(ble)) {
    return null
  }
  return typeof ble.online === 'boolean' ? ble.online : null
}

export const extractReportedMcuBleOnline = (shadow: unknown): boolean | null => {
  const mcu = extractReportedMcu(shadow)
  if (!mcu) {
    return null
  }
  const ble = mcu.ble
  return isRecord(ble) && typeof ble.online === 'boolean' ? ble.online : null
}

export const extractReportedMcuBatteryMv = (shadow: unknown): number | null => {
  const mcu = extractReportedMcu(shadow)
  if (!mcu) {
    return null
  }
  return typeof mcu.batteryMv === 'number' ? mcu.batteryMv : null
}

export const extractReportedBoardWifiOnline = (shadow: unknown): boolean | null => {
  const board = extractReportedBoard(shadow)
  if (!board) {
    return null
  }
  const wifi = board.wifi
  return isRecord(wifi) && typeof wifi.online === 'boolean' ? wifi.online : null
}

export const extractReportedBoardVideo = (shadow: unknown): BoardVideoRuntime => {
  const board = extractReportedBoard(shadow)
  if (!board) {
    return {
      ready: false,
      status: null,
      transport: null,
      viewerUrl: null,
      channelName: null,
      viewerConnected: false,
      lastError: null,
    }
  }

  const video = board.video
  if (!isRecord(video)) {
    return {
      ready: false,
      status: null,
      transport: null,
      viewerUrl: null,
      channelName: null,
      viewerConnected: false,
      lastError: null,
    }
  }

  const session = video.session
  const sessionRecord = isRecord(session) ? session : null
  const status = video.status

  return {
    ready: video.ready === true,
    status:
      status === 'starting' || status === 'ready' || status === 'error'
        ? status
        : null,
    transport: video.transport === 'aws-webrtc' ? 'aws-webrtc' : null,
    viewerUrl:
      sessionRecord && typeof sessionRecord.viewerUrl === 'string' && sessionRecord.viewerUrl.trim()
        ? sessionRecord.viewerUrl.trim()
        : null,
    channelName:
      sessionRecord &&
      typeof sessionRecord.channelName === 'string' &&
      sessionRecord.channelName.trim()
        ? sessionRecord.channelName.trim()
        : null,
    viewerConnected: video.viewerConnected === true,
    lastError: typeof video.lastError === 'string' && video.lastError.trim() ? video.lastError : null,
  }
}

export const resolveViewerChannelName = (
  currentUrl: string,
  fallbackChannelName: string | null,
  defaultChannelName = 'txing-board-video',
): string => {
  const routeUrl = new URL(currentUrl, 'https://txing.local')
  const channelFromUrl = routeUrl.searchParams.get('channel')?.trim()
  if (channelFromUrl) {
    return channelFromUrl
  }
  if (fallbackChannelName && fallbackChannelName.trim()) {
    return fallbackChannelName.trim()
  }
  return defaultChannelName
}

export const buildViewerUrlWithChannel = (
  viewerUrl: string,
  channelName: string | null,
): string => {
  const targetUrl = new URL(viewerUrl, 'https://txing.local')
  if (channelName && channelName.trim()) {
    targetUrl.searchParams.set('channel', channelName.trim())
  }
  return targetUrl.toString()
}

export const getAppRoute = (pathname: string): 'dashboard' | 'video' => {
  if (pathname === '/video' || pathname === '/video/') {
    return 'video'
  }
  return 'dashboard'
}
