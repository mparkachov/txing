import {
  decodeSparkplugPayload,
  type SparkplugMetric,
  type SparkplugTopics,
} from './sparkplug-protocol'

export type SparkplugRedconSource = 'dbirth' | 'ddata'

export type SparkplugDeviceRedconUpdate = {
  redcon: 1 | 2 | 3 | 4
  source: SparkplugRedconSource
}

const decodeSparkplugDeviceMetrics = (
  topic: string,
  payload: Uint8Array,
  topics: Pick<SparkplugTopics, 'dbirth' | 'ddata'>,
): SparkplugMetric[] | null => {
  if (topic !== topics.dbirth && topic !== topics.ddata) {
    return null
  }

  try {
    return decodeSparkplugPayload(payload).metrics
  } catch {
    return null
  }
}

const extractMetricRedcon = (metric: SparkplugMetric | undefined): 1 | 2 | 3 | 4 | null => {
  if (!metric) {
    return null
  }
  const rawValue =
    typeof metric.intValue === 'number'
      ? metric.intValue
      : typeof metric.longValue === 'number'
        ? metric.longValue
        : null
  if (!Number.isInteger(rawValue) || rawValue === null) {
    return null
  }
  return rawValue >= 1 && rawValue <= 4 ? (rawValue as 1 | 2 | 3 | 4) : null
}

export const extractSparkplugDeviceRedconUpdate = (
  topic: string,
  payload: Uint8Array,
  topics: Pick<SparkplugTopics, 'dbirth' | 'ddata' | 'ddeath'>,
): SparkplugDeviceRedconUpdate | null => {
  if (topic === topics.ddeath) {
    return null
  }

  if (topic !== topics.dbirth && topic !== topics.ddata) {
    return null
  }

  const metrics = decodeSparkplugDeviceMetrics(topic, payload, topics)
  if (!metrics) {
    return null
  }

  const redconMetric = metrics.find((metric) => metric.name === 'redcon')
  const redcon = extractMetricRedcon(redconMetric)
  if (redcon === null) {
    return null
  }

  return {
    redcon,
    source: topic === topics.dbirth ? 'dbirth' : 'ddata',
  }
}

export const extractSparkplugDeviceBatteryMv = (
  topic: string,
  payload: Uint8Array,
  topics: Pick<SparkplugTopics, 'dbirth' | 'ddata'>,
): number | null => {
  const metrics = decodeSparkplugDeviceMetrics(topic, payload, topics)
  if (!metrics) {
    return null
  }

  const batteryMetric = metrics.find((metric) => metric.name === 'batteryMv')
  if (!batteryMetric) {
    return null
  }

  const rawValue =
    typeof batteryMetric.intValue === 'number'
      ? batteryMetric.intValue
      : typeof batteryMetric.longValue === 'number'
        ? batteryMetric.longValue
        : null
  return Number.isInteger(rawValue) ? rawValue : null
}
