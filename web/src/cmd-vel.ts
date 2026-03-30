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
const controlKeys = new Set(['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'])

const createZeroVector = (): Vector3 => ({
  x: 0,
  y: 0,
  z: 0,
})

export const isCmdVelControlKey = (key: string): boolean => controlKeys.has(key)

export const buildCmdVelTopic = (thingName: string): string => `${thingName}/board/cmd_vel`

export const buildZeroTwist = (): Twist => ({
  linear: createZeroVector(),
  angular: createZeroVector(),
})

export const buildTwistFromPressedKeys = (pressedKeys: Iterable<string>): Twist => {
  let linearX = 0
  let angularZ = 0

  for (const key of pressedKeys) {
    switch (key) {
      case 'ArrowUp':
        linearX += 1
        break
      case 'ArrowDown':
        linearX -= 1
        break
      case 'ArrowLeft':
        angularZ += 1
        break
      case 'ArrowRight':
        angularZ -= 1
        break
      default:
        break
    }
  }

  return {
    linear: {
      x: Math.max(-1, Math.min(1, linearX)),
      y: 0,
      z: 0,
    },
    angular: {
      x: 0,
      y: 0,
      z: Math.max(-1, Math.min(1, angularZ)),
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
