import {
  buildCmdVelTwistFromKeys,
  buildZeroTwist,
  isCmdVelControlKey,
  isCmdVelDirectionalKey,
  isCmdVelStopKey,
  isZeroTwist,
  twistEquals,
  type Twist,
} from './cmd-vel'

type PublishCmdVel = (twist: Twist) => Promise<void> | void

export type CmdVelTeleopControllerOptions = {
  publishCmdVel: PublishCmdVel
}

export class CmdVelTeleopController {
  private readonly publishCmdVel: PublishCmdVel
  private active = false
  private currentTwist = buildZeroTwist()
  private readonly heldKeys = new Set<string>()

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
    this.publishStop()
  }

  handleKeyDown(key: string, _repeat = false): boolean {
    if (!this.active || !isCmdVelControlKey(key)) {
      return false
    }

    if (isCmdVelStopKey(key)) {
      this.publishStop()
      return true
    }

    if (isCmdVelDirectionalKey(key)) {
      this.heldKeys.add(key)
      this.publishNextTwist(buildCmdVelTwistFromKeys(this.heldKeys))
    }
    return true
  }

  handleKeyUp(key: string): boolean {
    if (!this.active || !isCmdVelControlKey(key)) {
      return false
    }
    if (isCmdVelDirectionalKey(key)) {
      this.heldKeys.delete(key)
      this.publishNextTwist(buildCmdVelTwistFromKeys(this.heldKeys))
    }
    return true
  }

  handleBlur(): void {
    if (!this.active) {
      return
    }
    this.publishStop()
  }

  handleVisibilityHidden(): void {
    if (!this.active) {
      return
    }
    this.publishStop()
  }

  tick(): void {
    if (!this.active || isZeroTwist(this.currentTwist)) {
      return
    }
    void this.publishCmdVel(this.currentTwist)
  }

  private publishNextTwist(nextTwist: Twist): void {
    if (twistEquals(nextTwist, this.currentTwist)) {
      return
    }
    this.currentTwist = nextTwist
    void this.publishCmdVel(nextTwist)
  }

  private publishStop(): void {
    const zeroTwist = buildZeroTwist()
    const shouldPublish = !isZeroTwist(this.currentTwist)
    this.heldKeys.clear()
    this.currentTwist = zeroTwist
    if (shouldPublish) {
      void this.publishCmdVel(zeroTwist)
    }
  }
}
