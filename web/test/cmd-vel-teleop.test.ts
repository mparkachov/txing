import { describe, expect, test } from 'bun:test'
import { CmdVelTeleopController } from '../src/cmd-vel-teleop'
import type { Twist } from '../src/cmd-vel'

describe('cmd_vel teleop controller', () => {
  test('publishes stepped ROS Twist updates only while active and ignores keyup state changes', () => {
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
        linear: { x: 0.1, y: 0, z: 0 },
        angular: { x: 0, y: 0, z: 0 },
      },
      {
        linear: { x: 0.2, y: 0, z: 0 },
        angular: { x: 0, y: 0, z: 0 },
      },
    ])
  })

  test('ignores browser key repeat events so one held press only increments once', () => {
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
        linear: { x: 0.1, y: 0, z: 0 },
        angular: { x: 0, y: 0, z: 0 },
      },
    ])
  })

  test('repeats the last non-zero twist and stops only on explicit stop/deactivate', () => {
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
    controller.handleKeyDown('s')
    controller.tick()

    expect(published).toEqual([
      {
        linear: { x: 0.1, y: 0, z: 0 },
        angular: { x: 0, y: 0, z: 0 },
      },
      {
        linear: { x: 0.1, y: 0, z: 0 },
        angular: { x: 0, y: 0, z: 0 },
      },
      {
        linear: { x: 0.1, y: 0, z: 0 },
        angular: { x: 0, y: 0, z: 0 },
      },
      {
        linear: { x: 0, y: 0, z: 0 },
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
        angular: { x: 0, y: 0, z: 0.2 },
      },
      {
        linear: { x: 0, y: 0, z: 0 },
        angular: { x: 0, y: 0, z: 0 },
      },
    ])
  })

  test('stops immediately on blur and document hide', () => {
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
    controller.handleKeyDown('ArrowLeft')
    controller.handleVisibilityHidden()

    expect(published).toEqual([
      {
        linear: { x: 0.1, y: 0, z: 0 },
        angular: { x: 0, y: 0, z: 0 },
      },
      {
        linear: { x: 0.1, y: 0, z: 0 },
        angular: { x: 0, y: 0, z: 0.2 },
      },
      {
        linear: { x: 0, y: 0, z: 0 },
        angular: { x: 0, y: 0, z: 0 },
      },
      {
        linear: { x: 0, y: 0, z: 0 },
        angular: { x: 0, y: 0, z: 0.2 },
      },
      {
        linear: { x: 0, y: 0, z: 0 },
        angular: { x: 0, y: 0, z: 0 },
      },
    ])
  })
})
