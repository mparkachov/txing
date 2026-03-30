export type Vector3 = {
  x: number
  y: number
  z: number
}

export type Twist = {
  linear: Vector3
  angular: Vector3
}

export type CmdVelPublishPacket = {
  topicName: string
  qos: 0
  retain: false
  payload: Uint8Array
}

const encoder = new TextEncoder()
const directionalKeys = new Set(['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'])
// Temporary browser teleop defaults; the MQTT contract stays strict ROS Twist semantics.
export const cmdVelLinearStepMps = 0.1
export const cmdVelAngularStepRadPerSec = 0.2
export const cmdVelMaxLinearXMps = 0.5
export const cmdVelMaxAngularZRadPerSec = 1.0
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

export const buildCmdVelTopic = (thingName: string): string => `${thingName}/board/cmd_vel`

export const buildZeroTwist = (): Twist => ({
  linear: createZeroVector(),
  angular: createZeroVector(),
})

const clampAxis = (value: number, limit: number): number => Math.max(-limit, Math.min(limit, value))

const normalizeAxis = (value: number, limit: number): number =>
  Math.round(clampAxis(value, limit) * 10 ** cmdVelAxisPrecision) / 10 ** cmdVelAxisPrecision

export const applyCmdVelStep = (
  currentTwist: Twist,
  key: string,
): Twist => {
  if (isCmdVelStopKey(key)) {
    return buildZeroTwist()
  }

  let linearX = currentTwist.linear.x
  let angularZ = currentTwist.angular.z

  switch (key) {
    case 'ArrowUp':
      linearX += cmdVelLinearStepMps
      break
    case 'ArrowDown':
      linearX -= cmdVelLinearStepMps
      break
    case 'ArrowLeft':
      angularZ += cmdVelAngularStepRadPerSec
      break
    case 'ArrowRight':
      angularZ -= cmdVelAngularStepRadPerSec
      break
    default:
      return currentTwist
  }

  return {
    linear: {
      x: normalizeAxis(linearX, cmdVelMaxLinearXMps),
      y: 0,
      z: 0,
    },
    angular: {
      x: 0,
      y: 0,
      z: normalizeAxis(angularZ, cmdVelMaxAngularZRadPerSec),
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

export const buildCmdVelPublishPacket = (
  thingName: string,
  twist: Twist,
): CmdVelPublishPacket => ({
  topicName: buildCmdVelTopic(thingName),
  qos: 0,
  retain: false,
  payload: encoder.encode(JSON.stringify(twist)),
})
