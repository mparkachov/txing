import { expect, test } from 'bun:test'
import {
  centeredSticks,
  ControllerButtonTracker,
  ControllerInput,
  ControllerMotion,
  readGamepadSticks,
  readKeyboardSticks,
  readRoverMotion,
} from '../src/mavlink-controller-input'

test('standard gamepad sticks center, scale proportionally and keep diagonals bounded', () => {
  expect(readGamepadSticks([0.08, -0.08, 0.12, 0])).toEqual(centeredSticks)
  const sticks = readGamepadSticks([-0.56, 0, 1, -1])
  expect(sticks.leftX).toBeCloseTo(-0.5)
  expect(sticks.rightX).toBeCloseTo(Math.SQRT1_2)
  expect(sticks.rightY).toBeCloseTo(Math.SQRT1_2)
  expect(readRoverMotion(readGamepadSticks([0, 0.56, 0.56, 0]))).toEqual({
    steering: 500, throttle: -500,
  })
  expect(readRoverMotion(readGamepadSticks([1, 0, 0, -1]))).toEqual({ steering: 0, throttle: 0 })
})

test('input sources take turns without replaying overlapping movement', () => {
  const controller = new ControllerInput()
  const idle = { sticks: centeredSticks, engaged: false }
  const veer = { sticks: { ...centeredSticks, rightX: 0.5 }, engaged: true }
  const forward = { sticks: { ...centeredSticks, rightY: 1 }, engaged: true }
  const inputs = { gamepad: idle, pointer: idle, keyboard: idle }
  controller.sample(inputs)
  expect(controller.sample({ ...inputs, gamepad: veer })).toEqual({ source: 'gamepad', sticks: veer.sticks })
  expect(controller.sample({ ...inputs, gamepad: veer, keyboard: forward }).source).toBe('gamepad')
  expect(controller.sample({ ...inputs, keyboard: forward })).toEqual({ source: null, sticks: centeredSticks })
  expect(controller.sample({ ...inputs, keyboard: forward }).source).toBeNull()
  controller.sample(inputs)
  expect(controller.sample({ ...inputs, keyboard: forward }).source).toBe('keyboard')
  expect(controller.sample({ ...inputs, pointer: veer }).source).toBeNull()
  controller.sample(inputs)
  expect(controller.sample({ ...inputs, pointer: veer }).source).toBe('pointer')
})

test('gamepad changes leave active pointer input alone and require a fresh gamepad deflection', () => {
  const controller = new ControllerInput()
  const idle = { sticks: centeredSticks, engaged: false }
  const veer = { sticks: { ...centeredSticks, rightX: 0.5 }, engaged: true }
  const inputs = { gamepad: idle, pointer: idle, keyboard: idle }
  controller.sample(inputs)
  controller.sample({ ...inputs, pointer: veer })
  controller.resetSource('gamepad')
  expect(controller.sample({ ...inputs, pointer: veer, gamepad: veer }).source).toBe('pointer')
  controller.reset()
  expect(controller.sample({ ...inputs, gamepad: veer }).source).toBeNull()
  controller.sample(inputs)
  expect(controller.sample({ ...inputs, gamepad: veer }).source).toBe('gamepad')
})

test('keyboard shortcuts produce the same axes as the sticks', () => {
  expect(readKeyboardSticks(new Set(['w', 'a', 'r', 'e']), 'quad')).toEqual({
    leftX: 1, leftY: 1, rightX: -1, rightY: 1,
  })
  expect(readKeyboardSticks(new Set(['s', 'd', 'f', 'q']), 'quad')).toEqual({
    leftX: -1, leftY: -1, rightX: 1, rightY: -1,
  })
  expect(readRoverMotion(readKeyboardSticks(new Set(['ArrowUp', 'ArrowLeft']), 'rover'))).toEqual({
    steering: -1_000, throttle: 1_000,
  })
  expect(readKeyboardSticks(new Set(['w', 's']), 'quad')).toEqual(centeredSticks)
})

test('motion is neutral after input loss until a fresh center sample, and absent without authority', () => {
  const motion = new ControllerMotion()
  const forward = { ...centeredSticks, rightY: 0.4 }
  motion.sample(forward, 10)
  expect(motion.current(20, true)).toEqual(centeredSticks)
  motion.sample(centeredSticks, 30)
  expect(motion.isCentered(30)).toBe(true)
  motion.sample(forward, 40)
  expect(motion.current(100, true)).toEqual(forward)
  expect(motion.current(100, false)).toBeNull()
  expect(motion.current(300, true)).toEqual(centeredSticks)
  motion.sample(forward, 301)
  expect(motion.current(301, true)).toEqual(centeredSticks)
  motion.reset()
  motion.sample(forward, 302)
  expect(motion.isCentered(302)).toBe(false)
  expect(motion.current(302, true)).toEqual(centeredSticks)
  motion.sample(centeredSticks, 303)
  motion.sample(forward, 304)
  expect(motion.current(304, true)).toEqual(forward)
})

test('held gamepad buttons cannot replay actions or turn acquisition into release', () => {
  const buttons = new ControllerButtonTracker()
  const menu = new Set(['Menu'] as const)
  const released = new Set<never>()
  const acquire = { Menu: { id: 'acquire', enabled: true, holdMs: 1_000 } }
  const release = { Menu: { id: 'release', enabled: true, holdMs: 0 } }
  expect(buttons.sample(menu, acquire, 0)).toBeNull()
  expect(buttons.sample(menu, acquire, 1_100)).toBeNull()
  buttons.sample(released, acquire, 1_110)
  expect(buttons.sample(menu, acquire, 1_120)).toBeNull()
  expect(buttons.sample(menu, acquire, 2_119)).toBeNull()
  expect(buttons.sample(menu, acquire, 2_120)).toBe('Menu')
  expect(buttons.sample(menu, release, 2_130)).toBeNull()
  buttons.sample(released, release, 2_140)
  expect(buttons.sample(menu, release, 2_150)).toBe('Menu')
})

test('takeoff hold is cancelled when readiness changes and pause takes precedence', () => {
  const buttons = new ControllerButtonTracker()
  const a = new Set(['A'] as const)
  const ready = { A: { id: 'takeoff', enabled: true, holdMs: 1_000 } }
  buttons.sample(new Set(), ready, 0)
  buttons.sample(a, ready, 10)
  buttons.sample(a, { A: { ...ready.A, enabled: false } }, 900)
  expect(buttons.sample(a, ready, 1_100)).toBeNull()
  buttons.sample(new Set(), ready, 1_200)
  buttons.sample(a, ready, 1_210)
  expect(buttons.sample(new Set(['A', 'LB']), {
    ...ready, LB: { id: 'pause', enabled: true, holdMs: 0 },
  }, 2_210)).toBe('LB')
  expect(buttons.sample(a, ready, 2_220)).toBeNull()
})
