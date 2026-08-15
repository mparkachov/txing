export const mavlinkV2Magic = 0xfd
const headerLength = 10
const checksumLength = 2

export type MavlinkFrame = {
  bytes: Uint8Array
  componentId: number
  messageId: number
  payload: Uint8Array
  sequence: number
  systemId: number
}

const crcExtras = new Map<number, number>([
  [0, 50], // HEARTBEAT
  [11, 89], // SET_MODE
  [69, 243], // MANUAL_CONTROL
  [76, 152], // COMMAND_LONG
  [77, 143], // COMMAND_ACK
])

const accumulateX25 = (crc: number, byte: number): number => {
  let tmp = byte ^ (crc & 0xff)
  tmp ^= (tmp << 4) & 0xff
  return ((crc >>> 8) ^ (tmp << 8) ^ (tmp << 3) ^ (tmp >>> 4)) & 0xffff
}

const mavlinkCrc = (bytes: Uint8Array, crcExtra: number): number => {
  let crc = 0xffff
  for (const byte of bytes) {
    crc = accumulateX25(crc, byte)
  }
  return accumulateX25(crc, crcExtra)
}

const requireByte = (value: number, field: string): void => {
  if (!Number.isInteger(value) || value < 0 || value > 0xff) {
    throw new Error(`${field} must be an unsigned byte`)
  }
}

export const parseMavlinkFrame = (bytes: Uint8Array): MavlinkFrame => {
  if (bytes.byteLength < headerLength + checksumLength || bytes[0] !== mavlinkV2Magic) {
    throw new Error('invalid MAVLink 2 frame header')
  }
  if ((bytes[2] & 0x01) !== 0) {
    throw new Error('signed MAVLink frame')
  }
  const payloadLength = bytes[1]
  const checksumOffset = headerLength + payloadLength
  if (bytes.byteLength !== checksumOffset + checksumLength) {
    throw new Error('invalid MAVLink 2 frame length')
  }
  const messageId = bytes[7] | (bytes[8] << 8) | (bytes[9] << 16)
  const crcExtra = crcExtras.get(messageId)
  if (crcExtra === undefined) {
    // The board is the common-dialect authority. Office preserves unfamiliar
    // telemetry as an observation rather than attempting to rewrite it.
    return {
      bytes,
      sequence: bytes[4],
      systemId: bytes[5],
      componentId: bytes[6],
      messageId,
      payload: bytes.slice(headerLength, checksumOffset),
    }
  }
  const expected = mavlinkCrc(bytes.slice(1, checksumOffset), crcExtra)
  const actual = bytes[checksumOffset] | (bytes[checksumOffset + 1] << 8)
  if (actual !== expected) {
    throw new Error('invalid MAVLink frame CRC')
  }
  return {
    bytes,
    sequence: bytes[4],
    systemId: bytes[5],
    componentId: bytes[6],
    messageId,
    payload: bytes.slice(headerLength, checksumOffset),
  }
}

export const buildMavlinkFrame = ({
  componentId,
  messageId,
  payload,
  sequence,
  systemId,
}: {
  componentId: number
  messageId: number
  payload: Uint8Array
  sequence: number
  systemId: number
}): Uint8Array => {
  requireByte(componentId, 'componentId')
  requireByte(sequence, 'sequence')
  requireByte(systemId, 'systemId')
  if (!Number.isInteger(messageId) || messageId < 0 || messageId > 0xffffff) {
    throw new Error('messageId must be a 24-bit unsigned integer')
  }
  if (payload.byteLength > 0xff) {
    throw new Error('MAVLink payload must not exceed 255 bytes')
  }
  const crcExtra = crcExtras.get(messageId)
  if (crcExtra === undefined) {
    throw new Error(`MAVLink message ${messageId} is not approved for Office uplink`)
  }
  const frame = new Uint8Array(headerLength + payload.byteLength + checksumLength)
  frame[0] = mavlinkV2Magic
  frame[1] = payload.byteLength
  frame[2] = 0
  frame[3] = 0
  frame[4] = sequence
  frame[5] = systemId
  frame[6] = componentId
  frame[7] = messageId & 0xff
  frame[8] = (messageId >>> 8) & 0xff
  frame[9] = (messageId >>> 16) & 0xff
  frame.set(payload, headerLength)
  const checksumOffset = headerLength + payload.byteLength
  const checksum = mavlinkCrc(frame.slice(1, checksumOffset), crcExtra)
  frame[checksumOffset] = checksum & 0xff
  frame[checksumOffset + 1] = checksum >>> 8
  return frame
}
