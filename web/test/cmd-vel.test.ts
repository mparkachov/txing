import { describe, expect, test } from 'bun:test'
import {
  buildCmdVelPublishPacket,
  buildCmdVelTopic,
  buildTwistFromPressedKeys,
  buildZeroTwist,
  isCmdVelControlKey,
  isZeroTwist,
} from '../src/cmd-vel'

const decoder = new TextDecoder()

describe('cmd_vel helpers', () => {
  test('builds the exact cmd_vel topic and qos0 packet', () => {
    const packet = buildCmdVelPublishPacket('txing', {
      linear: { x: 1, y: 0, z: 0 },
      angular: { x: 0, y: 0, z: -1 },
    })

    expect(buildCmdVelTopic('txing')).toBe('txing/board/cmd_vel')
    expect(packet.topicName).toBe('txing/board/cmd_vel')
    expect(packet.qos).toBe(0)
    expect(packet.retain).toBe(false)
    expect(JSON.parse(decoder.decode(packet.payload))).toEqual({
      linear: { x: 1, y: 0, z: 0 },
      angular: { x: 0, y: 0, z: -1 },
    })
  })

  test('maps pressed arrow keys into ROS-style Twist values', () => {
    expect(buildTwistFromPressedKeys(['ArrowUp'])).toEqual({
      linear: { x: 1, y: 0, z: 0 },
      angular: { x: 0, y: 0, z: 0 },
    })
    expect(buildTwistFromPressedKeys(['ArrowDown', 'ArrowRight'])).toEqual({
      linear: { x: -1, y: 0, z: 0 },
      angular: { x: 0, y: 0, z: -1 },
    })
    expect(buildTwistFromPressedKeys(['ArrowUp', 'ArrowDown', 'ArrowLeft'])).toEqual({
      linear: { x: 0, y: 0, z: 0 },
      angular: { x: 0, y: 0, z: 1 },
    })
  })

  test('recognizes only the supported teleop keys and zero twists', () => {
    expect(isCmdVelControlKey('ArrowUp')).toBe(true)
    expect(isCmdVelControlKey('KeyW')).toBe(false)
    expect(isZeroTwist(buildZeroTwist())).toBe(true)
    expect(
      isZeroTwist({
        linear: { x: 0, y: 0, z: 0 },
        angular: { x: 0, y: 0, z: 1 },
      }),
    ).toBe(false)
  })
})
