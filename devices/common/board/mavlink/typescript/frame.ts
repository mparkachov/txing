import { messageRegistry } from './generated/message-registry'

export const MAVLINK_V2_MAGIC = 0xfd
export const MAVLINK_V2_HEADER_LENGTH = 10
export const MAVLINK_V2_CHECKSUM_LENGTH = 2
export const MAVLINK_V2_SIGNED_FRAME_LENGTH = 13

export type MavlinkFrameValidationCode =
  | 'invalid_magic'
  | 'signed_frame'
  | 'invalid_length'
  | 'unsupported_message'
  | 'invalid_crc'

export class MavlinkFrameValidationError extends Error {
  public constructor(public readonly code: MavlinkFrameValidationCode) {
    super(code)
    this.name = 'MavlinkFrameValidationError'
  }
}

export interface MavlinkV2Frame {
  readonly bytes: Uint8Array
  readonly sequence: number
  readonly systemId: number
  readonly componentId: number
  readonly messageId: number
  readonly payload: Uint8Array
}

export interface UnsignedMavlinkV2FrameInput {
  readonly componentId: number
  readonly messageId: number
  readonly payload: Uint8Array
  readonly sequence: number
  readonly systemId: number
}

const crcExtraByMessageId: ReadonlyMap<number, number> = new Map(
  messageRegistry.map(([messageId, Message]): [number, number] => {
    const message = new Message(0, 0)
    return [messageId, message._crc_extra]
  }),
)

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

const assertByte = (value: number, field: string): void => {
  if (!Number.isInteger(value) || value < 0 || value > 0xff) {
    throw new Error(`${field} must be an unsigned byte`)
  }
}

// Builds exactly one unsigned MAVLink 2 common-dialect frame. Callers own the
// sequence number and forward the returned bytes without rewriting them.
export const buildUnsignedMavlinkV2CommonFrame = ({
  componentId,
  messageId,
  payload,
  sequence,
  systemId,
}: UnsignedMavlinkV2FrameInput): Uint8Array => {
  assertByte(componentId, 'componentId')
  assertByte(sequence, 'sequence')
  assertByte(systemId, 'systemId')
  if (!Number.isInteger(messageId) || messageId < 0 || messageId > 0xffffff) {
    throw new Error('messageId must be a 24-bit unsigned integer')
  }
  if (payload.byteLength > 0xff) {
    throw new Error('MAVLink payload must not exceed 255 bytes')
  }
  const crcExtra = crcExtraByMessageId.get(messageId)
  if (crcExtra === undefined) {
    throw new MavlinkFrameValidationError('unsupported_message')
  }

  const frame = new Uint8Array(MAVLINK_V2_HEADER_LENGTH + payload.byteLength + MAVLINK_V2_CHECKSUM_LENGTH)
  frame[0] = MAVLINK_V2_MAGIC
  frame[1] = payload.byteLength
  frame[2] = 0
  frame[3] = 0
  frame[4] = sequence
  frame[5] = systemId
  frame[6] = componentId
  frame[7] = messageId & 0xff
  frame[8] = (messageId >>> 8) & 0xff
  frame[9] = (messageId >>> 16) & 0xff
  frame.set(payload, MAVLINK_V2_HEADER_LENGTH)
  const checksumOffset = MAVLINK_V2_HEADER_LENGTH + payload.byteLength
  const checksum = mavlinkCrc(frame.slice(1, checksumOffset), crcExtra)
  frame[checksumOffset] = checksum & 0xff
  frame[checksumOffset + 1] = checksum >>> 8
  return frame
}

// Validates one complete unsigned MAVLink 2 common-dialect frame. The caller
// forwards the returned bytes without changing sequence, source, target,
// payload, or checksum.
export const parseUnsignedMavlinkV2CommonFrame = (bytes: Uint8Array): MavlinkV2Frame => {
  if (bytes[0] !== MAVLINK_V2_MAGIC) {
    throw new MavlinkFrameValidationError('invalid_magic')
  }
  if ((bytes[2] & 0x01) !== 0) {
    throw new MavlinkFrameValidationError('signed_frame')
  }
  const payloadLength = bytes[1]
  const expectedLength = MAVLINK_V2_HEADER_LENGTH + payloadLength + MAVLINK_V2_CHECKSUM_LENGTH
  if (bytes.byteLength !== expectedLength) {
    throw new MavlinkFrameValidationError('invalid_length')
  }
  const messageId = bytes[7] | (bytes[8] << 8) | (bytes[9] << 16)
  const crcExtra = crcExtraByMessageId.get(messageId)
  if (crcExtra === undefined) {
    throw new MavlinkFrameValidationError('unsupported_message')
  }
  const checksumOffset = MAVLINK_V2_HEADER_LENGTH + payloadLength
  const expectedCrc = mavlinkCrc(bytes.slice(1, checksumOffset), crcExtra)
  const actualCrc = bytes[checksumOffset] | (bytes[checksumOffset + 1] << 8)
  if (actualCrc !== expectedCrc) {
    throw new MavlinkFrameValidationError('invalid_crc')
  }
  return {
    bytes,
    sequence: bytes[4],
    systemId: bytes[5],
    componentId: bytes[6],
    messageId,
    payload: bytes.slice(MAVLINK_V2_HEADER_LENGTH, checksumOffset),
  }
}
