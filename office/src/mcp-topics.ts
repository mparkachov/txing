export const mcpTopicNamespace = 'txings'
export const mcpServiceName = 'mcp'

const normalizeSegment = (value: string, fieldName: string): string => {
  const normalized = value.trim()
  if (!normalized) {
    throw new Error(`${fieldName} must not be empty`)
  }
  if (normalized.includes('/') || normalized.includes('+') || normalized.includes('#')) {
    throw new Error(`${fieldName} must not include MQTT separators or wildcards`)
  }
  return normalized
}

export const normalizeDeviceId = (deviceId: string): string => normalizeSegment(deviceId, 'deviceId')

export const normalizeSessionId = (sessionId: string): string =>
  normalizeSegment(sessionId, 'sessionId')

export const buildMcpTopicRoot = (deviceId: string): string =>
  `${mcpTopicNamespace}/${normalizeDeviceId(deviceId)}/${mcpServiceName}`

export const buildMcpDescriptorTopic = (deviceId: string): string =>
  `${buildMcpTopicRoot(deviceId)}/descriptor`

export const buildMcpStatusTopic = (deviceId: string): string =>
  `${buildMcpTopicRoot(deviceId)}/status`

export const buildMcpSessionC2sTopic = (deviceId: string, sessionId: string): string =>
  `${buildMcpTopicRoot(deviceId)}/session/${normalizeSessionId(sessionId)}/c2s`

export const buildMcpSessionS2cTopic = (deviceId: string, sessionId: string): string =>
  `${buildMcpTopicRoot(deviceId)}/session/${normalizeSessionId(sessionId)}/s2c`

export const buildMcpSessionC2sSubscription = (deviceId: string): string =>
  `${buildMcpTopicRoot(deviceId)}/session/+/c2s`

export type ParsedMcpDescriptorOrStatusTopic = {
  deviceId: string
  kind: 'descriptor' | 'status'
}

export const parseMcpDescriptorOrStatusTopic = (
  topic: string,
): ParsedMcpDescriptorOrStatusTopic | null => {
  const parts = topic.split('/')
  if (parts.length !== 4) {
    return null
  }
  if (parts[0] !== mcpTopicNamespace || parts[2] !== mcpServiceName) {
    return null
  }
  const kind = parts[3]
  if (kind !== 'descriptor' && kind !== 'status') {
    return null
  }
  if (!parts[1]) {
    return null
  }
  return {
    deviceId: parts[1],
    kind,
  }
}
