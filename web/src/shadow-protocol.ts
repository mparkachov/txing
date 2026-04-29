export type ShadowOperation = 'get' | 'update'
export type ShadowName = 'sparkplug' | 'mcu' | 'board' | 'video'
export type ShadowResponseKind = 'getAccepted' | 'getRejected' | 'updateAccepted' | 'updateRejected' | 'ignored'
export type ShadowTopics = {
  shadowName: ShadowName
  get: string
  getAccepted: string
  getRejected: string
  update: string
  updateAccepted: string
  updateRejected: string
}
export const namedShadowNames: readonly ShadowName[] = ['sparkplug', 'mcu', 'board', 'video']
export const isShadowName = (value: string): value is ShadowName =>
  (namedShadowNames as readonly string[]).includes(value)
export type DecodedShadowResponse = {
  kind: ShadowResponseKind
  operation: ShadowOperation | null
  shadowName: ShadowName | null
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

export const buildShadowTopics = (
  thingName: string,
  shadowName: ShadowName = 'sparkplug',
): ShadowTopics => {
  const topicPrefix = `$aws/things/${thingName}/shadow/name/${shadowName}`
  return {
    shadowName,
    get: `${topicPrefix}/get`,
    getAccepted: `${topicPrefix}/get/accepted`,
    getRejected: `${topicPrefix}/get/rejected`,
    update: `${topicPrefix}/update`,
    updateAccepted: `${topicPrefix}/update/accepted`,
    updateRejected: `${topicPrefix}/update/rejected`,
  }
}

export const buildNamedShadowTopics = (
  thingName: string,
  shadowNames: readonly ShadowName[] = namedShadowNames,
): Partial<Record<ShadowName, ShadowTopics>> =>
  Object.fromEntries(
    shadowNames.map((shadowName) => [shadowName, buildShadowTopics(thingName, shadowName)]),
  ) as Partial<Record<ShadowName, ShadowTopics>>

export const buildShadowSubscriptionPacket = (
  topics: ShadowTopics | Partial<Record<ShadowName, ShadowTopics>>,
): ShadowSubscriptionPacket => {
  const topicList =
    'getAccepted' in topics
      ? [topics]
      : Object.values(topics).filter((topic): topic is ShadowTopics => topic !== undefined)
  return {
    subscriptions: topicList.flatMap((topicSet) => [
      { topicFilter: topicSet.getAccepted, qos: 1 as const },
      { topicFilter: topicSet.getRejected, qos: 1 as const },
      { topicFilter: topicSet.updateAccepted, qos: 1 as const },
      { topicFilter: topicSet.updateRejected, qos: 1 as const },
    ]),
  }
}

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
      shadowName: null,
      payload: parsedPayload,
      clientToken: null,
    }
  }

  return {
    kind,
    operation: kind.startsWith('get') ? 'get' : 'update',
    shadowName: topics.shadowName,
    payload: parsedPayload,
    clientToken: extractShadowClientToken(parsedPayload),
  }
}
