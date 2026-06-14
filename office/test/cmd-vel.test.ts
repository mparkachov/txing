import { describe, expect, test } from 'bun:test'
import {
  buildCmdVelTwistFromKeys,
  buildZeroTwist,
  cmdVelTeleopAngularTargetRadPerSec,
  cmdVelTeleopLinearTargetMps,
  isCmdVelControlKey,
  isCmdVelDirectionalKey,
  isCmdVelStopKey,
  isZeroTwist,
} from '../src/cmd-vel'

describe('cmd_vel helpers', () => {
  test('builds direct ROS Twist targets from held keys in physical units', () => {
    expect(buildCmdVelTwistFromKeys(['ArrowUp'])).toEqual({
      linear: { x: 0.35, y: 0, z: 0 },
      angular: { x: 0, y: 0, z: 0 },
    })
    expect(buildCmdVelTwistFromKeys(['ArrowDown'])).toEqual({
      linear: { x: -0.35, y: 0, z: 0 },
      angular: { x: 0, y: 0, z: 0 },
    })
    expect(buildCmdVelTwistFromKeys(['ArrowLeft'])).toEqual({
      linear: { x: 0, y: 0, z: 0 },
      angular: { x: 0, y: 0, z: 2.5 },
    })
    expect(buildCmdVelTwistFromKeys(['ArrowUp', 'ArrowLeft'])).toEqual({
      linear: { x: 0.35, y: 0, z: 0 },
      angular: { x: 0, y: 0, z: 2.5 },
    })
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

  test('cancels opposing held keys on each axis', () => {
    expect(buildCmdVelTwistFromKeys(['ArrowUp', 'ArrowDown'])).toEqual(buildZeroTwist())
    expect(buildCmdVelTwistFromKeys(['ArrowLeft', 'ArrowRight'])).toEqual(buildZeroTwist())
    expect(buildCmdVelTwistFromKeys(['ArrowUp', 'ArrowDown', 'ArrowLeft'])).toEqual({
      linear: { x: 0, y: 0, z: 0 },
      angular: { x: 0, y: 0, z: 2.5 },
    })
  })

  test('exports the temporary browser teleop target velocities', () => {
    expect(cmdVelTeleopLinearTargetMps).toBe(0.35)
    expect(cmdVelTeleopAngularTargetRadPerSec).toBe(2.5)
  })
})
