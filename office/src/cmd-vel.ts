export type Vector3 = {
  x: number
  y: number
  z: number
}

export type Twist = {
  linear: Vector3
  angular: Vector3
}

const directionalKeys = new Set(['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'])
// Temporary browser teleop defaults; the MQTT contract stays strict ROS Twist semantics.
export const cmdVelTeleopLinearTargetMps = 0.35
export const cmdVelTeleopAngularTargetRadPerSec = 2.5
const cmdVelAxisPrecision = 3

const createZeroVector = (): Vector3 => ({
  x: 0,
  y: 0,
  z: 0,
})

export const isCmdVelDirectionalKey = (key: string): boolean => directionalKeys.has(key)

export const isCmdVelStopKey = (key: string): boolean => key.toLowerCase() === 's'

export const isCmdVelControlKey = (key: string): boolean =>
  isCmdVelDirectionalKey(key) || isCmdVelStopKey(key)

export const buildZeroTwist = (): Twist => ({
  linear: createZeroVector(),
  angular: createZeroVector(),
})

const clampAxis = (value: number, limit: number): number => Math.max(-limit, Math.min(limit, value))

const normalizeAxis = (value: number, limit: number): number =>
  Math.round(clampAxis(value, limit) * 10 ** cmdVelAxisPrecision) / 10 ** cmdVelAxisPrecision

const getKeyAxisDirection = (
  keys: ReadonlySet<string>,
  positiveKey: string,
  negativeKey: string,
): number => {
  const positive = keys.has(positiveKey) ? 1 : 0
  const negative = keys.has(negativeKey) ? 1 : 0
  return positive - negative
}

export const buildCmdVelTwistFromKeys = (keys: Iterable<string>): Twist => {
  const heldKeys = new Set(keys)
  const linearX =
    getKeyAxisDirection(heldKeys, 'ArrowUp', 'ArrowDown') * cmdVelTeleopLinearTargetMps
  const angularZ =
    getKeyAxisDirection(heldKeys, 'ArrowLeft', 'ArrowRight') *
    cmdVelTeleopAngularTargetRadPerSec

  return {
    linear: {
      x: normalizeAxis(linearX, cmdVelTeleopLinearTargetMps),
      y: 0,
      z: 0,
    },
    angular: {
      x: 0,
      y: 0,
      z: normalizeAxis(angularZ, cmdVelTeleopAngularTargetRadPerSec),
    },
  }
}

export const isZeroTwist = (twist: Twist): boolean =>
  twist.linear.x === 0 &&
  twist.linear.y === 0 &&
  twist.linear.z === 0 &&
  twist.angular.x === 0 &&
  twist.angular.y === 0 &&
  twist.angular.z === 0

export const twistEquals = (left: Twist, right: Twist): boolean =>
  left.linear.x === right.linear.x &&
  left.linear.y === right.linear.y &&
  left.linear.z === right.linear.z &&
  left.angular.x === right.angular.x &&
  left.angular.y === right.angular.y &&
  left.angular.z === right.angular.z
