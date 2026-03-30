import { describe, expect, test } from 'bun:test'
import { CmdVelTeleopController } from '../src/cmd-vel-teleop'
import type { Twist } from '../src/cmd-vel'

describe('cmd_vel teleop controller', () => {
  test('publishes on key transitions only while active', () => {
    const published: Twist[] = []
    const controller = new CmdVelTeleopController({
      publishCmdVel: (twist) => {
        published.push(twist)
      },
    })

    expect(controller.handleKeyDown('ArrowUp')).toBe(false)

    controller.activate()
    expect(controller.handleKeyDown('ArrowUp')).toBe(true)
    expect(controller.handleKeyUp('ArrowUp')).toBe(true)

    expect(published).toEqual([
      {
        linear: { x: 1, y: 0, z: 0 },
        angular: { x: 0, y: 0, z: 0 },
      },
      {
        linear: { x: 0, y: 0, z: 0 },
        angular: { x: 0, y: 0, z: 0 },
      },
    ])
  })

  test('repeats active non-zero twists and stops on blur', () => {
    const published: Twist[] = []
    const controller = new CmdVelTeleopController({
      publishCmdVel: (twist) => {
        published.push(twist)
      },
    })

    controller.activate()
    controller.handleKeyDown('ArrowUp')
    controller.tick()
    controller.handleBlur()
    controller.tick()

    expect(published).toEqual([
      {
        linear: { x: 1, y: 0, z: 0 },
        angular: { x: 0, y: 0, z: 0 },
      },
      {
        linear: { x: 1, y: 0, z: 0 },
        angular: { x: 0, y: 0, z: 0 },
      },
      {
        linear: { x: 0, y: 0, z: 0 },
        angular: { x: 0, y: 0, z: 0 },
      },
    ])
  })

  test('deactivate publishes a stop and visibility hidden clears pressed keys', () => {
    const published: Twist[] = []
    const controller = new CmdVelTeleopController({
      publishCmdVel: (twist) => {
        published.push(twist)
      },
    })

    controller.activate()
    controller.handleKeyDown('ArrowLeft')
    controller.handleVisibilityHidden()
    controller.deactivate()

    expect(published).toEqual([
      {
        linear: { x: 0, y: 0, z: 0 },
        angular: { x: 0, y: 0, z: 1 },
      },
      {
        linear: { x: 0, y: 0, z: 0 },
        angular: { x: 0, y: 0, z: 0 },
      },
      {
        linear: { x: 0, y: 0, z: 0 },
        angular: { x: 0, y: 0, z: 0 },
      },
    ])
  })
})
