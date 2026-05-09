import { extractSparkplugMetrics } from '../../../web/src/sparkplug-model'

export type PowerReportedState = {
  batteryMv: number | null
}

const readNumberMetric = (
  metrics: Record<string, unknown> | null,
  name: string,
): number | null => {
  const value = metrics?.[name]
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

export const extractPowerReportedState = (shadow: unknown): PowerReportedState => {
  const metrics = extractSparkplugMetrics(shadow)
  return {
    batteryMv: readNumberMetric(metrics, 'batteryMv'),
  }
}
