import { describe, expect, test } from 'bun:test'
import {
  applyCmdVelStep,
  buildCmdVelPublishPacket,
  buildCmdVelTopic,
  buildZeroTwist,
  cmdVelAngularStepRadPerSec,
  cmdVelLinearStepMps,
  cmdVelMaxAngularZRadPerSec,
  cmdVelMaxLinearXMps,
  isCmdVelControlKey,
  isCmdVelDirectionalKey,
  isCmdVelStopKey,
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

  test('applies stepped ROS Twist changes in physical units', () => {
    const afterFirstUp = applyCmdVelStep(buildZeroTwist(), 'ArrowUp')
    const afterSecondUp = applyCmdVelStep(afterFirstUp, 'ArrowUp')
    const afterLeft = applyCmdVelStep(afterSecondUp, 'ArrowLeft')
    const afterStop = applyCmdVelStep(afterLeft, 's')

    expect(afterFirstUp).toEqual({
      linear: { x: 0.1, y: 0, z: 0 },
      angular: { x: 0, y: 0, z: 0 },
    })
    expect(afterSecondUp).toEqual({
      linear: { x: 0.2, y: 0, z: 0 },
      angular: { x: 0, y: 0, z: 0 },
    })
    expect(afterLeft).toEqual({
      linear: { x: 0.2, y: 0, z: 0 },
      angular: { x: 0, y: 0, z: 0.2 },
    })
    expect(afterStop).toEqual(buildZeroTwist())
  })

  test('recognizes only the supported teleop keys and zero twists', () => {
    expect(isCmdVelControlKey('ArrowUp')).toBe(true)
    expect(isCmdVelControlKey('s')).toBe(true)
    expect(isCmdVelDirectionalKey('ArrowLeft')).toBe(true)
    expect(isCmdVelDirectionalKey('s')).toBe(false)
    expect(isCmdVelStopKey('s')).toBe(true)
    expect(isCmdVelStopKey('S')).toBe(true)
    expect(isCmdVelControlKey('KeyW')).toBe(false)
    expect(isZeroTwist(buildZeroTwist())).toBe(true)
    expect(
      isZeroTwist({
        linear: { x: 0, y: 0, z: 0 },
        angular: { x: 0, y: 0, z: 1 },
      }),
    ).toBe(false)
  })

  test('clamps stepped twist state at the configured physical limits', () => {
    let twist = buildZeroTwist()
    for (let index = 0; index < 10; index += 1) {
      twist = applyCmdVelStep(twist, 'ArrowUp')
    }
    expect(twist.linear.x).toBe(cmdVelMaxLinearXMps)

    for (let index = 0; index < 10; index += 1) {
      twist = applyCmdVelStep(twist, 'ArrowRight')
    }
    expect(twist.angular.z).toBe(-cmdVelMaxAngularZRadPerSec)
  })

  test('exports the temporary browser teleop step sizes', () => {
    expect(cmdVelLinearStepMps).toBe(0.1)
    expect(cmdVelAngularStepRadPerSec).toBe(0.2)
  })
})
