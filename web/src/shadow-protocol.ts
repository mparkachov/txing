export type ShadowOperation = 'get' | 'update'
export type ShadowResponseKind = 'getAccepted' | 'getRejected' | 'updateAccepted' | 'updateRejected' | 'ignored'
export type ShadowTopics = {
  get: string
  getAccepted: string
  getRejected: string
  update: string
  updateAccepted: string
  updateRejected: string
}
export type DecodedShadowResponse = {
  kind: ShadowResponseKind
  operation: ShadowOperation | null
  payload: unknown
  clientToken: string | null
}
export type ShadowSubscriptionPacket = {
  subscriptions: Array<{
    topicFilter: string
    qos: 1
  }>
}
export type ShadowPublishPacket = {
  topicName: string
  qos: 1
  payload: Uint8Array
}

const decoder = new TextDecoder()
const encoder = new TextEncoder()

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null

export const deriveMqttHostFromIotDataEndpoint = (endpoint: string): string => {
  const trimmed = endpoint.trim()
  if (!trimmed) {
    throw new Error('AWS IoT data endpoint must not be empty')
  }

  if (!trimmed.includes('://')) {
    return trimmed.replace(/\/+$/, '')
  }

  return new URL(trimmed).hostname
}

export const buildShadowTopics = (thingName: string): ShadowTopics => {
  const topicPrefix = `$aws/things/${thingName}/shadow`
  return {
    get: `${topicPrefix}/get`,
    getAccepted: `${topicPrefix}/get/accepted`,
    getRejected: `${topicPrefix}/get/rejected`,
    update: `${topicPrefix}/update`,
    updateAccepted: `${topicPrefix}/update/accepted`,
    updateRejected: `${topicPrefix}/update/rejected`,
  }
}

export const buildShadowSubscriptionPacket = (topics: ShadowTopics): ShadowSubscriptionPacket => ({
  subscriptions: [
    { topicFilter: topics.getAccepted, qos: 1 },
    { topicFilter: topics.getRejected, qos: 1 },
    { topicFilter: topics.updateAccepted, qos: 1 },
    { topicFilter: topics.updateRejected, qos: 1 },
  ],
})

export const createShadowClientToken = (operation: ShadowOperation): string => {
  const randomSegment =
    typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
      ? crypto.randomUUID()
      : `${Date.now()}-${Math.random().toString(16).slice(2)}`
  return `${operation}-${randomSegment}`
}

const encodeShadowPayload = (payload: unknown): Uint8Array =>
  encoder.encode(JSON.stringify(payload))

export const buildGetShadowPublishPacket = (
  topics: ShadowTopics,
  clientToken: string,
): ShadowPublishPacket => ({
  topicName: topics.get,
  qos: 1,
  payload: encodeShadowPayload({
    clientToken,
  }),
})

export const buildUpdateShadowPublishPacket = (
  topics: ShadowTopics,
  shadowDocument: unknown,
  clientToken: string,
): ShadowPublishPacket => {
  if (!isRecord(shadowDocument)) {
    throw new Error('Thing Shadow update payload must be an object')
  }

  return {
    topicName: topics.update,
    qos: 1,
    payload: encodeShadowPayload({
      ...shadowDocument,
      clientToken,
    }),
  }
}

const payloadToText = (payload: unknown): string => {
  if (typeof payload === 'string') {
    return payload
  }
  if (payload instanceof ArrayBuffer) {
    return decoder.decode(new Uint8Array(payload))
  }
  if (ArrayBuffer.isView(payload)) {
    return decoder.decode(new Uint8Array(payload.buffer, payload.byteOffset, payload.byteLength))
  }
  return ''
}

export const parseShadowPayload = (payload: unknown): unknown => {
  const text = payloadToText(payload).trim()
  if (!text) {
    return {}
  }

  try {
    return JSON.parse(text)
  } catch {
    return { raw: text }
  }
}

export const extractShadowClientToken = (payload: unknown): string | null =>
  isRecord(payload) && typeof payload.clientToken === 'string' ? payload.clientToken : null

export const classifyShadowTopic = (topic: string, topics: ShadowTopics): ShadowResponseKind => {
  if (topic === topics.getAccepted) {
    return 'getAccepted'
  }
  if (topic === topics.getRejected) {
    return 'getRejected'
  }
  if (topic === topics.updateAccepted) {
    return 'updateAccepted'
  }
  if (topic === topics.updateRejected) {
    return 'updateRejected'
  }
  return 'ignored'
}

export const decodeShadowResponse = (
  topic: string,
  payload: unknown,
  topics: ShadowTopics,
): DecodedShadowResponse => {
  const kind = classifyShadowTopic(topic, topics)
  const parsedPayload = parseShadowPayload(payload)

  if (kind === 'ignored') {
    return {
      kind,
      operation: null,
      payload: parsedPayload,
      clientToken: null,
    }
  }

  return {
    kind,
    operation: kind.startsWith('get') ? 'get' : 'update',
    payload: parsedPayload,
    clientToken: extractShadowClientToken(parsedPayload),
  }
}
