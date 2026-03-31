export const SPARKPLUG_NAMESPACE = 'spBv1.0'

export const SparkplugDataType = {
  Int32: 3,
} as const

export type SparkplugDataType = (typeof SparkplugDataType)[keyof typeof SparkplugDataType]

export type SparkplugMetric = {
  name: string
  datatype: SparkplugDataType
  intValue: number | null
  longValue: number | null
  timestamp: number | null
}

export type DecodedSparkplugPayload = {
  timestamp: number | null
  seq: number | null
  metrics: SparkplugMetric[]
}

export type SparkplugTopics = {
  nbirth: string
  ndata: string
  dcmd: string
  dbirth: string
  ddata: string
  ddeath: string
}

export type SparkplugPublishPacket = {
  topicName: string
  qos: 1
  payload: Uint8Array
}

const textEncoder = new TextEncoder()

const appendVarint = (bytes: number[], value: number): void => {
  if (!Number.isInteger(value) || value < 0) {
    throw new Error(`Sparkplug varint value must be a non-negative integer, got ${value}`)
  }

  let remaining = value
  while (true) {
    const nextByte = remaining & 0x7f
    remaining >>>= 7
    if (remaining > 0) {
      bytes.push(nextByte | 0x80)
      continue
    }
    bytes.push(nextByte)
    return
  }
}

const appendKey = (bytes: number[], fieldNumber: number, wireType: number): void => {
  appendVarint(bytes, (fieldNumber << 3) | wireType)
}

const appendBytesField = (bytes: number[], fieldNumber: number, value: Uint8Array): void => {
  appendKey(bytes, fieldNumber, 2)
  appendVarint(bytes, value.byteLength)
  for (const byte of value) {
    bytes.push(byte)
  }
}

const appendStringField = (bytes: number[], fieldNumber: number, value: string): void => {
  appendBytesField(bytes, fieldNumber, textEncoder.encode(value))
}

const appendVarintField = (bytes: number[], fieldNumber: number, value: number): void => {
  appendKey(bytes, fieldNumber, 0)
  appendVarint(bytes, value)
}

const encodeSparkplugMetric = (metric: {
  name: string
  datatype: SparkplugDataType
  intValue?: number
  longValue?: number
  timestamp?: number
}): Uint8Array => {
  const bytes: number[] = []
  appendStringField(bytes, 1, metric.name)
  if (typeof metric.timestamp === 'number') {
    appendVarintField(bytes, 3, metric.timestamp)
  }
  appendVarintField(bytes, 4, metric.datatype)
  if (typeof metric.intValue === 'number') {
    appendVarintField(bytes, 10, metric.intValue)
  } else if (typeof metric.longValue === 'number') {
    appendVarintField(bytes, 11, metric.longValue)
  } else {
    throw new Error(`Sparkplug metric ${metric.name} is missing a value`)
  }
  return Uint8Array.from(bytes)
}

export const encodeSparkplugPayload = (options: {
  timestamp: number
  seq: number
  metrics: Array<{
    name: string
    datatype: SparkplugDataType
    intValue?: number
    longValue?: number
    timestamp?: number
  }>
}): Uint8Array => {
  const bytes: number[] = []
  appendVarintField(bytes, 1, options.timestamp)
  for (const metric of options.metrics) {
    appendBytesField(bytes, 2, encodeSparkplugMetric(metric))
  }
  appendVarintField(bytes, 3, options.seq)
  return Uint8Array.from(bytes)
}

const readVarint = (
  bytes: Uint8Array,
  startOffset: number,
): { value: number; nextOffset: number } => {
  let value = 0
  let shift = 0
  let offset = startOffset
  while (offset < bytes.byteLength) {
    const byte = bytes[offset]
    offset += 1
    value |= (byte & 0x7f) << shift
    if ((byte & 0x80) === 0) {
      return { value, nextOffset: offset }
    }
    shift += 7
    if (shift > 63) {
      throw new Error('Sparkplug varint is too large')
    }
  }
  throw new Error('Unexpected end of Sparkplug payload while reading varint')
}

const readLengthDelimited = (
  bytes: Uint8Array,
  startOffset: number,
): { value: Uint8Array; nextOffset: number } => {
  const { value: length, nextOffset } = readVarint(bytes, startOffset)
  const endOffset = nextOffset + length
  if (endOffset > bytes.byteLength) {
    throw new Error('Unexpected end of Sparkplug payload while reading bytes field')
  }
  return {
    value: bytes.subarray(nextOffset, endOffset),
    nextOffset: endOffset,
  }
}

const skipField = (bytes: Uint8Array, startOffset: number, wireType: number): number => {
  if (wireType === 0) {
    return readVarint(bytes, startOffset).nextOffset
  }
  if (wireType === 1) {
    return startOffset + 8
  }
  if (wireType === 2) {
    return readLengthDelimited(bytes, startOffset).nextOffset
  }
  if (wireType === 5) {
    return startOffset + 4
  }
  throw new Error(`Unsupported Sparkplug wire type ${wireType}`)
}

const decodeSparkplugMetric = (bytes: Uint8Array): SparkplugMetric => {
  let offset = 0
  let name = ''
  let datatype = SparkplugDataType.Int32
  let intValue: number | null = null
  let longValue: number | null = null
  let timestamp: number | null = null

  while (offset < bytes.byteLength) {
    const key = readVarint(bytes, offset)
    offset = key.nextOffset
    const fieldNumber = key.value >> 3
    const wireType = key.value & 0x07

    if (fieldNumber === 1 && wireType === 2) {
      const field = readLengthDelimited(bytes, offset)
      name = new TextDecoder().decode(field.value)
      offset = field.nextOffset
      continue
    }
    if (fieldNumber === 3 && wireType === 0) {
      const field = readVarint(bytes, offset)
      timestamp = field.value
      offset = field.nextOffset
      continue
    }
    if (fieldNumber === 4 && wireType === 0) {
      const field = readVarint(bytes, offset)
      datatype = field.value as SparkplugDataType
      offset = field.nextOffset
      continue
    }
    if (fieldNumber === 10 && wireType === 0) {
      const field = readVarint(bytes, offset)
      intValue = field.value
      offset = field.nextOffset
      continue
    }
    if (fieldNumber === 11 && wireType === 0) {
      const field = readVarint(bytes, offset)
      longValue = field.value
      offset = field.nextOffset
      continue
    }
    offset = skipField(bytes, offset, wireType)
  }

  return {
    name,
    datatype,
    intValue,
    longValue,
    timestamp,
  }
}

export const decodeSparkplugPayload = (payload: Uint8Array): DecodedSparkplugPayload => {
  let offset = 0
  let timestamp: number | null = null
  let seq: number | null = null
  const metrics: SparkplugMetric[] = []

  while (offset < payload.byteLength) {
    const key = readVarint(payload, offset)
    offset = key.nextOffset
    const fieldNumber = key.value >> 3
    const wireType = key.value & 0x07

    if (fieldNumber === 1 && wireType === 0) {
      const field = readVarint(payload, offset)
      timestamp = field.value
      offset = field.nextOffset
      continue
    }
    if (fieldNumber === 2 && wireType === 2) {
      const field = readLengthDelimited(payload, offset)
      metrics.push(decodeSparkplugMetric(field.value))
      offset = field.nextOffset
      continue
    }
    if (fieldNumber === 3 && wireType === 0) {
      const field = readVarint(payload, offset)
      seq = field.value
      offset = field.nextOffset
      continue
    }
    offset = skipField(payload, offset, wireType)
  }

  return {
    timestamp,
    seq,
    metrics,
  }
}

export const buildSparkplugTopics = (
  groupId: string,
  edgeNodeId: string,
  deviceId: string,
): SparkplugTopics => ({
  nbirth: `${SPARKPLUG_NAMESPACE}/${groupId}/NBIRTH/${edgeNodeId}`,
  ndata: `${SPARKPLUG_NAMESPACE}/${groupId}/NDATA/${edgeNodeId}`,
  dcmd: `${SPARKPLUG_NAMESPACE}/${groupId}/DCMD/${edgeNodeId}/${deviceId}`,
  dbirth: `${SPARKPLUG_NAMESPACE}/${groupId}/DBIRTH/${edgeNodeId}/${deviceId}`,
  ddata: `${SPARKPLUG_NAMESPACE}/${groupId}/DDATA/${edgeNodeId}/${deviceId}`,
  ddeath: `${SPARKPLUG_NAMESPACE}/${groupId}/DDEATH/${edgeNodeId}/${deviceId}`,
})

export const buildSparkplugRedconCommandPacket = (
  topics: SparkplugTopics,
  redcon: number,
  seq: number,
  timestamp = Date.now(),
): SparkplugPublishPacket => {
  if (!Number.isInteger(redcon) || redcon < 1 || redcon > 4) {
    throw new Error(`REDCON command must be an integer between 1 and 4, got ${redcon}`)
  }

  return {
    topicName: topics.dcmd,
    qos: 1,
    payload: encodeSparkplugPayload({
      timestamp,
      seq,
      metrics: [
        {
          name: 'redcon',
          datatype: SparkplugDataType.Int32,
          intValue: redcon,
        },
      ],
    }),
  }
}
