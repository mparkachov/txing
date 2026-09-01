import { readFileSync } from 'node:fs'
import { describe, expect, test } from 'bun:test'

import {
  MavlinkFrameValidationError,
  parseUnsignedMavlinkV2CommonFrame,
} from '../../devices/common/board/mavlink/typescript/frame'

const heartbeatFrame = Uint8Array.from(
  Buffer.from('fd0900002affbe000000000000000a03000403d131', 'hex'),
)

describe('Board MAVLink common frame contract', () => {
  test('accepts the golden unsigned MAVLink 2 HEARTBEAT frame and preserves it byte-for-byte', () => {
    const frame = parseUnsignedMavlinkV2CommonFrame(heartbeatFrame)

    expect(frame.messageId).toBe(0)
    expect(frame.sequence).toBe(42)
    expect(frame.systemId).toBe(255)
    expect(frame.componentId).toBe(190)
    expect(frame.bytes).toEqual(heartbeatFrame)
  })

  test('rejects signed, malformed, invalid-CRC, and non-common frames', () => {
    const signed = Uint8Array.from([...heartbeatFrame, ...new Uint8Array(13)])
    signed[2] = 1
    expect(() => parseUnsignedMavlinkV2CommonFrame(signed)).toThrow(
      new MavlinkFrameValidationError('signed_frame'),
    )

    const malformed = heartbeatFrame.slice(0, -1)
    expect(() => parseUnsignedMavlinkV2CommonFrame(malformed)).toThrow(
      new MavlinkFrameValidationError('invalid_length'),
    )

    const invalidCrc = heartbeatFrame.slice()
    invalidCrc[invalidCrc.length - 1] ^= 0xff
    expect(() => parseUnsignedMavlinkV2CommonFrame(invalidCrc)).toThrow(
      new MavlinkFrameValidationError('invalid_crc'),
    )

    const unsupported = heartbeatFrame.slice()
    unsupported[7] = 0xff
    unsupported[8] = 0xff
    unsupported[9] = 0x7f
    expect(() => parseUnsignedMavlinkV2CommonFrame(unsupported)).toThrow(
      new MavlinkFrameValidationError('unsupported_message'),
    )
  })

  test('keeps Office free of a runtime MAVLink package', () => {
    const packageJson = JSON.parse(readFileSync(new URL('../package.json', import.meta.url), 'utf8')) as {
      dependencies: Record<string, string>
      devDependencies: Record<string, string>
    }
    const packageNames = [...Object.keys(packageJson.dependencies), ...Object.keys(packageJson.devDependencies)]
    expect(packageNames.some((name) => name.toLowerCase().includes('mavlink'))).toBeFalse()
  })
})
