import { extractSparkplugMetrics } from '../../../web/src/sparkplug-model'

export type WeatherReportedState = {
  batteryMv: number | null
  measuredTemperature: number | null
  measuredPressure: number | null
  measuredHumidity: number | null
}

const readNumberMetric = (
  metrics: Record<string, unknown> | null,
  name: string,
): number | null => {
  const value = metrics?.[name]
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

export const extractWeatherReportedState = (shadow: unknown): WeatherReportedState => {
  const metrics = extractSparkplugMetrics(shadow)
  return {
    batteryMv: readNumberMetric(metrics, 'batteryMv'),
    measuredTemperature: readNumberMetric(metrics, 'measuredTemperature'),
    measuredPressure: readNumberMetric(metrics, 'measuredPressure'),
    measuredHumidity: readNumberMetric(metrics, 'measuredHumidity'),
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
