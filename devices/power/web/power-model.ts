export type PowerReportedState = {
  batteryMv: number | null
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
  shadowName: 'power',
): Record<string, unknown> | null => {
  if (!isRecord(shadow) || !isRecord(shadow.namedShadows)) {
    return null
  }
  const namedShadow = shadow.namedShadows[shadowName]
  if (!isRecord(namedShadow)) {
    return null
  }
  return extractReportedState(namedShadow)
}

const readNumberField = (
  reported: Record<string, unknown> | null,
  name: string,
): number | null => {
  const value = reported?.[name]
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

export const extractPowerReportedState = (shadow: unknown): PowerReportedState => {
  const reported = extractNamedShadowReportedState(shadow, 'power') ?? extractReportedState(shadow)
  return {
    batteryMv: readNumberField(reported, 'batteryMv'),
  }
}
