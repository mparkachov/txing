import {
  decodeSparkplugPayload,
  type SparkplugMetric,
  type SparkplugTopics,
} from './sparkplug-protocol'

export type SparkplugRedconSource = 'dbirth' | 'ddata' | 'ddeath'

export type SparkplugDeviceRedconUpdate = {
  redcon: 1 | 2 | 3 | 4
  source: SparkplugRedconSource
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
    return {
      redcon: 4,
      source: 'ddeath',
    }
  }

  if (topic !== topics.dbirth && topic !== topics.ddata) {
    return null
  }

  let decoded
  try {
    decoded = decodeSparkplugPayload(payload)
  } catch {
    return null
  }

  const redconMetric = decoded.metrics.find((metric) => metric.name === 'redcon')
  const redcon = extractMetricRedcon(redconMetric)
  if (redcon === null) {
    return null
  }

  return {
    redcon,
    source: topic === topics.dbirth ? 'dbirth' : 'ddata',
  }
}
