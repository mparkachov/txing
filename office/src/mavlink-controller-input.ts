export type ControllerSticks = {
  leftX: number
  leftY: number
  rightX: number
  rightY: number
}

export const centeredSticks: ControllerSticks = { leftX: 0, leftY: 0, rightX: 0, rightY: 0 }
export const areSticksCentered = ({ leftX, leftY, rightX, rightY }: ControllerSticks): boolean =>
  leftX === 0 && leftY === 0 && rightX === 0 && rightY === 0

const clamp = (value: number): number => Number.isFinite(value) ? Math.max(-1, Math.min(1, value)) : 0

export function normalizeStick(x: number, y: number, deadZone = 0.12): { x: number; y: number } {
  x = clamp(x)
  y = clamp(y)
  const magnitude = Math.hypot(x, y)
  if (magnitude <= deadZone) return { x: 0, y: 0 }
  const scale = (Math.min(magnitude, 1) - deadZone) / ((1 - deadZone) * magnitude)
  return { x: x * scale || 0, y: y * scale || 0 }
}

export function readGamepadSticks(axes: readonly number[]): ControllerSticks {
  const left = normalizeStick(axes[0], -axes[1])
  const right = normalizeStick(axes[2], -axes[3])
  return { leftX: left.x, leftY: left.y, rightX: right.x, rightY: right.y }
}

export function sticksForProfile(sticks: ControllerSticks, profile: 'quad' | 'rover'): ControllerSticks {
  return profile === 'quad' ? sticks : { ...centeredSticks, leftY: sticks.leftY, rightX: sticks.rightX }
}

export function readRoverMotion({ leftY, rightX }: ControllerSticks): { steering: number; throttle: number } {
  return { steering: Math.round(clamp(rightX) * 1_000) || 0, throttle: Math.round(clamp(leftY) * 1_000) || 0 }
}

const motionSources = ['pointer', 'keyboard', 'gamepad'] as const
export type MotionSource = typeof motionSources[number]
type MotionSample = { sticks: ControllerSticks; engaged: boolean }

export class ControllerInput {
  private active: MotionSource | null = null
  private readonly blocked = new Set<MotionSource>(motionSources)

  public reset(): void {
    for (const source of motionSources) this.resetSource(source)
  }

  public resetSource(source: MotionSource): void {
    if (this.active === source) this.active = null
    this.blocked.add(source)
  }

  public sample(inputs: Record<MotionSource, MotionSample>): { source: MotionSource | null; sticks: ControllerSticks } {
    for (const source of motionSources) {
      if (!inputs[source].engaged) this.blocked.delete(source)
    }
    // Remember inputs pressed while another source was engaged, even on its release frame.
    if (this.active) {
      for (const source of motionSources) {
        if (source !== this.active && inputs[source].engaged) this.blocked.add(source)
      }
      if (!inputs[this.active].engaged) this.active = null
    }
    this.active ??= motionSources.find((source) => inputs[source].engaged && !this.blocked.has(source)) ?? null
    for (const source of motionSources) {
      if (source !== this.active && inputs[source].engaged) this.blocked.add(source)
    }
    return { source: this.active, sticks: this.active ? inputs[this.active].sticks : centeredSticks }
  }
}

export class ControllerMotion {
  private awaitingCenter = true
  private sampledAt = -Infinity
  private sticks = centeredSticks

  public reset(): void {
    this.awaitingCenter = true
    this.sticks = centeredSticks
    this.sampledAt = -Infinity
  }

  public isFresh(now: number): boolean {
    return now - this.sampledAt <= 250
  }

  public sample(sticks: ControllerSticks, now: number): void {
    if (!this.isFresh(now)) this.awaitingCenter = true
    if (areSticksCentered(sticks)) this.awaitingCenter = false
    this.sticks = sticks
    this.sampledAt = now
  }

  public isCentered(now: number): boolean {
    return this.isFresh(now) && !this.awaitingCenter && areSticksCentered(this.sticks)
  }

  public current(now: number, enabled: boolean): ControllerSticks | null {
    if (!enabled) return null
    return this.isFresh(now) && !this.awaitingCenter ? this.sticks : centeredSticks
  }
}

export function readKeyboardSticks(keys: ReadonlySet<string>, profile: 'quad' | 'rover'): ControllerSticks {
  const axis = (positive: string, negative: string) => Number(keys.has(positive)) - Number(keys.has(negative))
  return profile === 'quad'
    ? { leftX: axis('e', 'q'), leftY: axis('r', 'f'), rightX: axis('d', 'a'), rightY: axis('w', 's') }
    : { ...centeredSticks, leftY: axis('ArrowUp', 'ArrowDown'), rightX: axis('ArrowRight', 'ArrowLeft') }
}

export const controllerButtons = { A: 0, B: 1, LB: 4, Menu: 9 } as const
export type ControllerButton = keyof typeof controllerButtons

type ButtonAction = { id: string; enabled: boolean; holdMs: number }
type Press = { actionId: string | null; startedAt: number }

export class ControllerButtonTracker {
  private readonly presses = new Map<ControllerButton, Press>()
  private awaitingRelease = true

  public reset(): void {
    this.presses.clear()
    this.awaitingRelease = true
  }

  public sample(
    down: ReadonlySet<ControllerButton>,
    actions: Readonly<Partial<Record<ControllerButton, ButtonAction>>>,
    now: number,
  ): ControllerButton | null {
    if (this.awaitingRelease) {
      if (down.size === 0) this.awaitingRelease = false
      return null
    }
    let triggered: ControllerButton | null = null
    // Pause wins if two buttons reach their activation point in the same sample.
    for (const button of ['LB', 'Menu', 'B', 'A'] as const) {
      if (!down.has(button)) {
        this.presses.delete(button)
        continue
      }
      const action = actions[button]
      const eligibleId = action?.enabled ? action.id : null
      const press = this.presses.get(button) ?? { actionId: eligibleId, startedAt: now }
      if (!action || press.actionId !== eligibleId || triggered !== null) press.actionId = null
      if (press.actionId !== null && action && now - press.startedAt >= action.holdMs) {
        triggered = button
        press.actionId = null
      }
      this.presses.set(button, press)
    }
    return triggered
  }
}
