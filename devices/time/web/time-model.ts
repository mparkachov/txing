type TimeReportedState = {
  currentTimeIso: string | null
  mode: 'sleep' | 'active' | null
  activeUntilMs: number | null
  lastCommandId: string | null
  observedAtMs: number | null
}

export type TimeNowResult = {
  currentTimeIso: string
  epochMs: number | null
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value)

const asOptionalString = (value: unknown): string | null =>
  typeof value === 'string' && value.trim() ? value.trim() : null

const asOptionalNumber = (value: unknown): number | null =>
  typeof value === 'number' && Number.isFinite(value) ? Math.round(value) : null

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

export const extractTimeReportedState = (shadow: unknown): TimeReportedState => {
  const reported = readNamedShadowReported(shadow, 'time')
  if (!reported) {
    return {
      currentTimeIso: null,
      mode: null,
      activeUntilMs: null,
      lastCommandId: null,
      observedAtMs: null,
    }
  }
  const mode = reported.mode === 'sleep' || reported.mode === 'active' ? reported.mode : null
  return {
    currentTimeIso: asOptionalString(reported.currentTimeIso),
    mode,
    activeUntilMs: asOptionalNumber(reported.activeUntilMs),
    lastCommandId: asOptionalString(reported.lastCommandId),
    observedAtMs: asOptionalNumber(reported.observedAtMs),
  }
}

export const parseTimeNowResult = (result: unknown): TimeNowResult | null => {
  if (!isRecord(result)) {
    return null
  }
  const currentTimeIso = asOptionalString(result.currentTimeIso)
  if (!currentTimeIso) {
    return null
  }
  return {
    currentTimeIso,
    epochMs: asOptionalNumber(result.epochMs),
  }
}

export const formatTimeValue = (value: string | null): string => value ?? '--'

export const formatEpochMs = (value: number | null): string => {
  if (value === null) {
    return '--'
  }
  return new Date(value).toISOString()
}
