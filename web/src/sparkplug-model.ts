export type TxingTargetRedconInputs = {
  targetRedcon: number | null
  reportedRedcon: number | null
}

export type PendingTargetResolutionInputs = {
  pendingTargetRedcon: number | null
  reportedRedcon: number | null
  isSparkplugDeviceUnavailable: boolean
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
  shadowName: 'sparkplug',
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

const extractSparkplugReportedState = (shadow: unknown): Record<string, unknown> | null =>
  extractNamedShadowReportedState(shadow, 'sparkplug') ?? extractReportedState(shadow)

const extractSparkplugTopic = (shadow: unknown): Record<string, unknown> | null => {
  const reported = extractSparkplugReportedState(shadow)
  if (!reported) {
    return null
  }
  const topic = reported.topic
  return isRecord(topic) ? topic : null
}

const extractSparkplugPayload = (shadow: unknown): Record<string, unknown> | null => {
  const reported = extractSparkplugReportedState(shadow)
  if (!reported) {
    return null
  }
  const payload = reported.payload
  return isRecord(payload) ? payload : null
}

export const extractSparkplugMetrics = (shadow: unknown): Record<string, unknown> | null => {
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

export const extractSparkplugMessageType = (shadow: unknown): string | null => {
  const topic = extractSparkplugTopic(shadow)
  return topic && typeof topic.messageType === 'string' ? topic.messageType : null
}

const extractSparkplugDeviceMessageType = (shadow: unknown): string | null => {
  const topic = extractSparkplugTopic(shadow)
  if (!topic || typeof topic.deviceId !== 'string' || topic.deviceId.length === 0) {
    return null
  }
  return typeof topic.messageType === 'string' ? topic.messageType : null
}

export const extractIsSparkplugDeviceUnavailable = (shadow: unknown): boolean =>
  extractSparkplugDeviceMessageType(shadow) === 'DDEATH'

export const extractReportedRedcon = (shadow: unknown): number | null => {
  if (extractIsSparkplugDeviceUnavailable(shadow)) {
    return null
  }
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

export const hasReachedTargetRedcon = ({
  targetRedcon,
  reportedRedcon,
}: TxingTargetRedconInputs): boolean => {
  if (targetRedcon === null || reportedRedcon === null) {
    return false
  }
  if (targetRedcon === 4) {
    return reportedRedcon === 4
  }
  return reportedRedcon <= targetRedcon
}

export const shouldClearPendingTargetRedcon = ({
  pendingTargetRedcon,
  reportedRedcon,
  isSparkplugDeviceUnavailable,
}: PendingTargetResolutionInputs): boolean => {
  if (pendingTargetRedcon === null) {
    return false
  }
  if (isSparkplugDeviceUnavailable) {
    return true
  }
  return hasReachedTargetRedcon({
    targetRedcon: pendingTargetRedcon,
    reportedRedcon,
  })
}
