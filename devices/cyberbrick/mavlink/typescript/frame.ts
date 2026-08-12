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
