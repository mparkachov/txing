type CloudMcuReportedState = {
  desiredRedcon: 3 | 4 | null
  powered: boolean | null
  ecsTaskArn: string | null
  ecsTaskStatus: string | null
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value)

const readNamedShadowReported = (
  shadow: unknown,
  shadowName: string,
): Record<string, unknown> | null => {
  if (!isRecord(shadow) || !isRecord(shadow.namedShadows)) {
    return null
  }
  const namedShadow = shadow.namedShadows[shadowName]
  if (!isRecord(namedShadow) || !isRecord(namedShadow.state)) {
    return null
  }
  return isRecord(namedShadow.state.reported) ? namedShadow.state.reported : null
}

const readRedcon = (value: unknown): 3 | 4 | null =>
  value === 3 || value === 4 ? value : null

const readString = (value: unknown): string | null =>
  typeof value === 'string' && value.trim() ? value.trim() : null

export const extractCloudMcuReportedState = (shadow: unknown): CloudMcuReportedState => {
  const reported = readNamedShadowReported(shadow, 'power')
  if (!reported) {
    return {
      desiredRedcon: null,
      powered: null,
      ecsTaskArn: null,
      ecsTaskStatus: null,
    }
  }
  return {
    desiredRedcon: readRedcon(reported.desiredRedcon),
    powered: typeof reported.powered === 'boolean' ? reported.powered : null,
    ecsTaskArn: readString(reported.ecsTaskArn),
    ecsTaskStatus: readString(reported.ecsTaskStatus),
  }
}
