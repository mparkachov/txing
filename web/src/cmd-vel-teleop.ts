import {
  buildTwistFromPressedKeys,
  buildZeroTwist,
  isCmdVelControlKey,
  isZeroTwist,
  twistEquals,
  type Twist,
} from './cmd-vel'

type PublishCmdVel = (twist: Twist) => Promise<void> | void

export type CmdVelTeleopControllerOptions = {
  publishCmdVel: PublishCmdVel
}

export class CmdVelTeleopController {
  private readonly pressedKeys = new Set<string>()
  private readonly publishCmdVel: PublishCmdVel
  private active = false
  private currentTwist = buildZeroTwist()

  constructor(options: CmdVelTeleopControllerOptions) {
    this.publishCmdVel = options.publishCmdVel
  }

  activate(): void {
    this.active = true
  }

  deactivate(): void {
    if (!this.active) {
      return
    }
    this.active = false
    this.publishStop(true)
  }

  handleKeyDown(key: string): boolean {
    if (!this.active || !isCmdVelControlKey(key)) {
      return false
    }

    const sizeBefore = this.pressedKeys.size
    this.pressedKeys.add(key)
    if (this.pressedKeys.size !== sizeBefore) {
      this.publishCurrentTwist()
    }
    return true
  }

  handleKeyUp(key: string): boolean {
    if (!this.active || !isCmdVelControlKey(key)) {
      return false
    }

    if (this.pressedKeys.delete(key)) {
      this.publishCurrentTwist()
    }
    return true
  }

  handleBlur(): void {
    if (!this.active) {
      return
    }
    this.publishStop(true)
  }

  handleVisibilityHidden(): void {
    if (!this.active) {
      return
    }
    this.publishStop(true)
  }

  tick(): void {
    if (!this.active || isZeroTwist(this.currentTwist)) {
      return
    }
    void this.publishCmdVel(this.currentTwist)
  }

  private publishCurrentTwist(): void {
    const nextTwist = buildTwistFromPressedKeys(this.pressedKeys)
    if (twistEquals(nextTwist, this.currentTwist)) {
      return
    }
    this.currentTwist = nextTwist
    void this.publishCmdVel(nextTwist)
  }

  private publishStop(forcePublish: boolean): void {
    this.pressedKeys.clear()
    const zeroTwist = buildZeroTwist()
    const shouldPublish = forcePublish || !isZeroTwist(this.currentTwist)
    this.currentTwist = zeroTwist
    if (shouldPublish) {
      void this.publishCmdVel(zeroTwist)
    }
  }
}
