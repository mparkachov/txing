import { describe, expect, test } from 'bun:test'
import { CmdVelTeleopController } from '../src/cmd-vel-teleop'
import type { Twist } from '../src/cmd-vel'

describe('cmd_vel teleop controller', () => {
  test('publishes direct ROS Twist targets only while active and stops on keyup', () => {
    const published: Twist[] = []
    const controller = new CmdVelTeleopController({
      publishCmdVel: (twist) => {
        published.push(twist)
      },
    })

    expect(controller.handleKeyDown('ArrowUp')).toBe(false)

    controller.activate()
    expect(controller.handleKeyDown('ArrowUp')).toBe(true)
    expect(controller.handleKeyDown('ArrowUp')).toBe(true)
    expect(controller.handleKeyUp('ArrowUp')).toBe(true)

    expect(published).toEqual([
      {
        linear: { x: 0.35, y: 0, z: 0 },
        angular: { x: 0, y: 0, z: 0 },
      },
      {
        linear: { x: 0, y: 0, z: 0 },
        angular: { x: 0, y: 0, z: 0 },
      },
    ])
  })

  test('consumes browser key repeat events without republishing unchanged held state', () => {
    const published: Twist[] = []
    const controller = new CmdVelTeleopController({
      publishCmdVel: (twist) => {
        published.push(twist)
      },
    })

    controller.activate()
    controller.handleKeyDown('ArrowUp', false)
    controller.handleKeyDown('ArrowUp', true)

    expect(published).toEqual([
      {
        linear: { x: 0.35, y: 0, z: 0 },
        angular: { x: 0, y: 0, z: 0 },
      },
    ])
  })

  test('repeats the last non-zero twist and stops after directional key release', () => {
    const published: Twist[] = []
    const controller = new CmdVelTeleopController({
      publishCmdVel: (twist) => {
        published.push(twist)
      },
    })

    controller.activate()
    controller.handleKeyDown('ArrowUp')
    controller.tick()
    controller.handleKeyUp('ArrowUp')
    controller.tick()

    expect(published).toEqual([
      {
        linear: { x: 0.35, y: 0, z: 0 },
        angular: { x: 0, y: 0, z: 0 },
      },
      {
        linear: { x: 0.35, y: 0, z: 0 },
        angular: { x: 0, y: 0, z: 0 },
      },
      {
        linear: { x: 0, y: 0, z: 0 },
        angular: { x: 0, y: 0, z: 0 },
      },
    ])
  })

  test('updates combined movement immediately as steering keys are pressed and released', () => {
    const published: Twist[] = []
    const controller = new CmdVelTeleopController({
      publishCmdVel: (twist) => {
        published.push(twist)
      },
    })

    controller.activate()
    controller.handleKeyDown('ArrowUp')
    controller.handleKeyDown('ArrowLeft')
    controller.handleKeyUp('ArrowLeft')
    controller.handleKeyUp('ArrowUp')

    expect(published).toEqual([
      {
        linear: { x: 0.35, y: 0, z: 0 },
        angular: { x: 0, y: 0, z: 0 },
      },
      {
        linear: { x: 0.35, y: 0, z: 0 },
        angular: { x: 0, y: 0, z: 2.5 },
      },
      {
        linear: { x: 0.35, y: 0, z: 0 },
        angular: { x: 0, y: 0, z: 0 },
      },
      {
        linear: { x: 0, y: 0, z: 0 },
        angular: { x: 0, y: 0, z: 0 },
      },
    ])
  })

  test('opposing directional keys cancel and recover when one side is released', () => {
    const published: Twist[] = []
    const controller = new CmdVelTeleopController({
      publishCmdVel: (twist) => {
        published.push(twist)
      },
    })

    controller.activate()
    controller.handleKeyDown('ArrowUp')
    controller.handleKeyDown('ArrowDown')
    controller.handleKeyUp('ArrowDown')

    expect(published).toEqual([
      {
        linear: { x: 0.35, y: 0, z: 0 },
        angular: { x: 0, y: 0, z: 0 },
      },
      {
        linear: { x: 0, y: 0, z: 0 },
        angular: { x: 0, y: 0, z: 0 },
      },
      {
        linear: { x: 0.35, y: 0, z: 0 },
        angular: { x: 0, y: 0, z: 0 },
      },
    ])
  })

  test('deactivate publishes stop from the last persistent twist state', () => {
    const published: Twist[] = []
    const controller = new CmdVelTeleopController({
      publishCmdVel: (twist) => {
        published.push(twist)
      },
    })

    controller.activate()
    controller.handleKeyDown('ArrowLeft')
    controller.deactivate()

    expect(published).toEqual([
      {
        linear: { x: 0, y: 0, z: 0 },
        angular: { x: 0, y: 0, z: 2.5 },
      },
      {
        linear: { x: 0, y: 0, z: 0 },
        angular: { x: 0, y: 0, z: 0 },
      },
    ])
  })

  test('stop key clears held keys and prevents keyup from resuming motion', () => {
    const published: Twist[] = []
    const controller = new CmdVelTeleopController({
      publishCmdVel: (twist) => {
        published.push(twist)
      },
    })

    controller.activate()
    controller.handleKeyDown('ArrowUp')
    controller.handleKeyDown('ArrowLeft')
    controller.handleKeyDown('s')
    controller.handleKeyUp('ArrowUp')
    controller.handleKeyUp('ArrowLeft')

    expect(published).toEqual([
      {
        linear: { x: 0.35, y: 0, z: 0 },
        angular: { x: 0, y: 0, z: 0 },
      },
      {
        linear: { x: 0.35, y: 0, z: 0 },
        angular: { x: 0, y: 0, z: 2.5 },
      },
      {
        linear: { x: 0, y: 0, z: 0 },
        angular: { x: 0, y: 0, z: 0 },
      },
    ])
  })

  test('stops immediately on blur and document hide and clears held keys', () => {
    const published: Twist[] = []
    const controller = new CmdVelTeleopController({
      publishCmdVel: (twist) => {
        published.push(twist)
      },
    })

    controller.activate()
    controller.handleKeyDown('ArrowUp')
    controller.handleKeyDown('ArrowLeft')
    controller.handleBlur()
    controller.handleKeyUp('ArrowUp')
    controller.handleKeyUp('ArrowLeft')
    controller.handleKeyDown('ArrowLeft')
    controller.handleVisibilityHidden()

    expect(published).toEqual([
      {
        linear: { x: 0.35, y: 0, z: 0 },
        angular: { x: 0, y: 0, z: 0 },
      },
      {
        linear: { x: 0.35, y: 0, z: 0 },
        angular: { x: 0, y: 0, z: 2.5 },
      },
      {
        linear: { x: 0, y: 0, z: 0 },
        angular: { x: 0, y: 0, z: 0 },
      },
      {
        linear: { x: 0, y: 0, z: 0 },
        angular: { x: 0, y: 0, z: 2.5 },
      },
      {
        linear: { x: 0, y: 0, z: 0 },
        angular: { x: 0, y: 0, z: 0 },
      },
    ])
  })
})
