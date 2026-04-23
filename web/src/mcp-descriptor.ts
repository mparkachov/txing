export const mcpWebRtcDataChannelLabel = 'txing.mcp.v1'

export type McpTransportKind = 'mqtt-jsonrpc' | 'webrtc-datachannel'

export type McpMqttTransportDescriptor = {
  type: 'mqtt-jsonrpc'
  priority: number
}

export type McpWebRtcTransportDescriptor = {
  type: 'webrtc-datachannel'
  priority: number
  signaling: 'aws-kvs'
  channelName: string
  region: string
  label: string
}

export type McpTransportDescriptor = McpMqttTransportDescriptor | McpWebRtcTransportDescriptor

export type McpDescriptor = {
  leaseTtlMs: number
  transports: McpTransportDescriptor[]
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value)

const parseTransportPriority = (
  value: Record<string, unknown>,
  fallback: number,
): number => {
  const rawPriority = value.priority
  if (typeof rawPriority !== 'number' || !Number.isFinite(rawPriority)) {
    return fallback
  }
  return Math.round(rawPriority)
}

const parseMcpTransportDescriptor = (
  value: unknown,
): McpTransportDescriptor | null => {
  if (!isRecord(value)) {
    return null
  }
  if (value.type === 'mqtt-jsonrpc') {
    return {
      type: 'mqtt-jsonrpc',
      priority: parseTransportPriority(value, 100),
    }
  }
  if (value.type !== 'webrtc-datachannel') {
    return null
  }
  if (value.signaling !== 'aws-kvs') {
    return null
  }
  if (typeof value.channelName !== 'string' || !value.channelName.trim()) {
    return null
  }
  if (typeof value.region !== 'string' || !value.region.trim()) {
    return null
  }
  const label =
    typeof value.label === 'string' && value.label.trim()
      ? value.label.trim()
      : mcpWebRtcDataChannelLabel
  return {
    type: 'webrtc-datachannel',
    priority: parseTransportPriority(value, 10),
    signaling: 'aws-kvs',
    channelName: value.channelName.trim(),
    region: value.region.trim(),
    label,
  }
}

const orderMcpTransports = (
  transports: McpTransportDescriptor[],
): McpTransportDescriptor[] =>
  [...transports].sort((left, right) => left.priority - right.priority)

const parseMcpTransports = (value: Record<string, unknown>): McpTransportDescriptor[] => {
  const parsedTransports = Array.isArray(value.transports)
    ? value.transports
        .map((transport) => parseMcpTransportDescriptor(transport))
        .filter((transport): transport is McpTransportDescriptor => transport !== null)
    : []

  if (!parsedTransports.some((transport) => transport.type === 'mqtt-jsonrpc')) {
    parsedTransports.push({
      type: 'mqtt-jsonrpc',
      priority: 100,
    })
  }

  return orderMcpTransports(parsedTransports)
}

export const parseMcpDescriptor = (value: unknown): McpDescriptor | null => {
  if (!isRecord(value)) {
    return null
  }
  const leaseTtlRaw = value.leaseTtlMs
  if (typeof leaseTtlRaw !== 'number' || !Number.isFinite(leaseTtlRaw) || leaseTtlRaw <= 0) {
    return null
  }
  return {
    leaseTtlMs: Math.round(leaseTtlRaw),
    transports: parseMcpTransports(value),
  }
}

export const selectPreferredMcpWebRtcTransport = (
  descriptor: McpDescriptor | null,
): McpWebRtcTransportDescriptor | null =>
  descriptor?.transports.find(
    (transport): transport is McpWebRtcTransportDescriptor =>
      transport.type === 'webrtc-datachannel',
  ) ?? null
