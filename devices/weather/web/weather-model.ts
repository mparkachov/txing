export type WeatherReportedState = {
  measuredTemperature: number | null
  measuredPressure: number | null
  measuredHumidity: number | null
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
  shadowName: 'power' | 'weather',
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

export const extractWeatherReportedState = (shadow: unknown): WeatherReportedState => {
  const reported = extractNamedShadowReportedState(shadow, 'weather') ?? extractReportedState(shadow)
  return {
    measuredTemperature: readNumberField(reported, 'measuredTemperature'),
    measuredPressure: readNumberField(reported, 'measuredPressure'),
    measuredHumidity: readNumberField(reported, 'measuredHumidity'),
  }
}

export const extractWeatherPowerReportedState = (shadow: unknown): {
  batteryMv: number | null
} => {
  const reported = extractNamedShadowReportedState(shadow, 'power')
  return {
    batteryMv: readNumberField(reported, 'batteryMv'),
  }
}

export const formatWeatherMetric = (
  value: number | null,
  unit: string,
  fractionDigits: number,
): string => {
  if (value === null) {
    return '--'
  }
  return `${value.toFixed(fractionDigits)} ${unit}`
}
