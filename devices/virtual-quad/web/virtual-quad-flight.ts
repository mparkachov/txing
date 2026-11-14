import {
  MavlinkControlSession,
  type MavlinkDataChannelHandle,
  type MavlinkFlightState,
} from '../../../office/src/mavlink-control'
import { buildMavlinkFrame, type MavlinkFrame } from '../../../office/src/mavlink-wire'
import { centeredSticks, type ControllerSticks } from '../../../office/src/mavlink-controller-input'

const target = { systemId: 1, componentId: 1 }
const guidedMode = 4
const landMode = 9
const takeoffCommand = 22
const flightAltitude = 2
const ground = 1
const inAir = 2
const maxVideoAgeMs = 2_000

type Position = {
  latitude: number
  longitude: number
  altitude: number
  heading: number | null
  speed: number
}
type FlightCommand = 'Taking off' | 'Landing'

const modes: Record<number, string> = { 0: 'Stabilize', 4: 'Guided', 9: 'Land' }
const decodeMode = (mode: number): string => modes[mode] ?? `Mode ${mode}`
const textDecoder = new TextDecoder()

const pad = (payload: Uint8Array, size: number): DataView => {
  const data = new Uint8Array(size)
  data.set(payload)
  return new DataView(data.buffer)
}

export const readQuadPosition = (payload: Uint8Array): Position | null => {
  if (payload.byteLength < 12 || payload.byteLength > 28) return null
  // MAVLink 2 can omit trailing zero bytes, including a north heading of zero.
  const fields = pad(payload, 28)
  const heading = fields.getUint16(26, true)
  return {
    latitude: fields.getInt32(4, true) / 1e7,
    longitude: fields.getInt32(8, true) / 1e7,
    altitude: fields.getInt32(16, true) / 1000,
    heading: heading < 36_000 ? heading / 100 : null,
    speed: Math.hypot(fields.getInt16(20, true), fields.getInt16(22, true)) / 100,
  }
}

const buildQuadVelocity = (
  sequence: number,
  { leftX, leftY, rightX, rightY }: ControllerSticks,
  altitude: number,
): Uint8Array => {
  const horizontalScale = Math.max(1, Math.hypot(rightY, rightX))
  const down = -leftY * 0.5
  const payload = new Uint8Array(53)
  const view = new DataView(payload.buffer)
  view.setFloat32(16, rightY / horizontalScale, true)
  view.setFloat32(20, rightX / horizontalScale, true)
  view.setFloat32(24, down === 0 || altitude >= 3.8 && down < 0 ? 0 : down, true)
  view.setFloat32(44, leftX * Math.PI / 6, true)
  view.setUint16(48, 1479, true) // Use velocity and yaw rate only.
  payload[50] = target.systemId
  payload[51] = target.componentId
  payload[52] = 9 // MAV_FRAME_BODY_OFFSET_NED
  return buildMavlinkFrame({ componentId: 190, messageId: 84, payload, sequence, systemId: 255 })
}

export type QuadFlightView = {
  connected: boolean
  heartbeat: boolean
  camera: boolean
  supported: boolean | null
  held: boolean
  owner: string | null
  position: Position | null
  mode: string | null
  armed: boolean | null
  landed: number | null
  error: string | null
  pending: string | null
  canAcquire: boolean
  canTakeOff: boolean
  canMove: boolean
  canLand: boolean
}

export class VirtualQuadFlight {
  private readonly session: MavlinkControlSession
  private readonly videoAt: () => number
  private readonly sendQueueEmpty: () => boolean
  private connected = false
  private supported: boolean | null = null
  private held = false
  private owner: string | null = null
  private error: string | null = null
  private command: FlightCommand | null = null
  private leaseOperation: 'Acquiring' | 'Releasing' | null = null
  private heartbeatAt = -Infinity
  private positionAt = -Infinity
  private landedAt = -Infinity
  private attitudeAt = -Infinity
  private nextOwnerPoll = Infinity
  private attitudeHeading = 0
  private position: Position | null = null
  private landed: number | null = null
  private state: MavlinkFlightState = { armed: null, mode: null }
  private statusText: { message: string; at: number } | null = null

  public constructor(options: {
    actor: string
    videoAt: () => number
    sendQueueEmpty: () => boolean
    onClose: () => void
  }) {
    this.videoAt = options.videoAt
    this.sendQueueEmpty = options.sendQueueEmpty
    this.session = new MavlinkControlSession({
      actor: options.actor,
      flightTarget: target,
      decodeMode,
      onControlState: (state, held) => {
        this.held = held
        this.owner = state.activeControl?.actor ?? null
      },
      onFlightState: (state) => {
        this.state = state
        this.heartbeatAt = performance.now()
      },
      onFrame: (frame) => this.observe(frame),
      onProtocolError: (message) => {
        if (message.startsWith('MAVLink active-control renewal failed') && this.connected) {
          this.error = message
          this.session.close()
        }
      },
      onStateChange: (state) => {
        this.connected = state === 'connected'
        if (!this.connected) {
          this.held = false
          options.onClose()
        }
      },
    })
  }

  public attach(handle: MavlinkDataChannelHandle): void {
    this.session.attach(handle)
    // Earlier images only stream telemetry. A missing reply leaves the observer connected.
    void this.session.getState({ closeOnTimeout: false }).then(() => {
      this.supported = true
      this.nextOwnerPoll = performance.now() + 2_000
    }).catch(() => { this.supported = false })
  }

  public handleMessage(message: string | Uint8Array): void { this.session.handleMessage(message) }

  public close(): void { this.session.close() }

  public view(): QuadFlightView {
    const now = performance.now()
    const heartbeat = this.connected && now - this.heartbeatAt < 2_500
    const camera = now - this.videoAt() < maxVideoAgeMs
    const position = heartbeat && now - this.positionAt < 2_000 ? this.position : null
    const landed = heartbeat && now - this.landedAt < 2_000 ? this.landed : null
    const armed = heartbeat ? this.state.armed : null
    const mode = heartbeat ? this.state.mode : null
    const ready = camera && position !== null && landed !== null
    const pending = this.leaseOperation ?? this.command
    const held = this.held && this.leaseOperation !== 'Releasing'
    return {
      connected: this.connected, heartbeat, camera, supported: this.supported,
      held, owner: this.owner, error: this.error, pending, armed, mode, landed,
      position: position && position.heading === null && now - this.attitudeAt < 2_000
        ? { ...position, heading: this.attitudeHeading } : position,
      canAcquire: ready && this.supported === true && !held && !this.owner && !pending,
      canTakeOff: ready && held && !pending && armed === false && landed === ground,
      canMove: ready && held && !pending && armed === true && landed === inAir && mode === modes[guidedMode],
      canLand: ready && held && !pending && armed === true && landed !== ground && mode !== modes[landMode],
    }
  }

  public async acquire(): Promise<void> {
    if (!this.view().canAcquire) return
    this.error = null
    this.leaseOperation = 'Acquiring'
    try {
      await this.session.activate(false)
    } catch (error) {
      this.error = error instanceof Error ? error.message : 'Unable to acquire flight control'
      this.nextOwnerPoll = performance.now()
    } finally {
      this.leaseOperation = null
    }
  }

  public async release(reason?: string): Promise<void> {
    if (!this.held || this.leaseOperation === 'Releasing') return
    this.sendMotion(centeredSticks)
    this.leaseOperation = 'Releasing'
    if (reason) this.error = reason
    try {
      await this.session.release()
      this.nextOwnerPoll = performance.now() + 2_000
    } catch {
      this.close()
    } finally {
      this.leaseOperation = null
    }
  }

  public async takeOff(): Promise<void> {
    if (!this.view().canTakeOff) return
    await this.perform('Taking off', async () => {
      await this.session.selectCustomMode(target, guidedMode)
      this.requireFlightLink()
      await this.session.armDisarm(target, true)
      this.requireFlightLink()
      await this.session.runCommand(target, takeoffCommand, { param7: flightAltitude })
      await this.confirm((view) => view.armed === true && view.landed === inAir &&
        view.position !== null && Math.abs(view.position.altitude - flightAltitude) <= 0.5)
    })
  }

  public async land(): Promise<void> {
    if (!this.view().canLand) return
    this.sendMotion(centeredSticks)
    await this.perform('Landing', async () => {
      await this.session.selectCustomMode(target, landMode)
      await this.confirm((view) => view.armed === false && view.landed === ground)
    })
  }

  public tick(): void {
    const view = this.view()
    if (view.held && (!view.camera || !view.heartbeat || view.position === null || view.landed === null)) {
      void this.release(view.camera ? 'Flight control released · telemetry lost' : 'Flight control released · camera lost')
    }
    if (this.connected && !this.held && !this.leaseOperation && performance.now() >= this.nextOwnerPoll) {
      this.nextOwnerPoll = Infinity
      void this.session.getState().catch(() => undefined).finally(() => {
        this.nextOwnerPoll = performance.now() + 2_000
      })
    }
  }

  private observe({ messageId, payload }: MavlinkFrame): void {
    const now = performance.now()
    if (messageId === 33) {
      this.position = readQuadPosition(payload)
      if (this.position) this.positionAt = now
    } else if (messageId === 245) {
      this.landed = payload[1] >= 1 && payload[1] <= 4 ? payload[1] : null
      this.landedAt = now
    } else if (messageId === 30 && payload.byteLength >= 4 && payload.byteLength <= 28) {
      const yaw = pad(payload, 28).getFloat32(12, true)
      if (Number.isFinite(yaw)) {
        this.attitudeHeading = (yaw * 180 / Math.PI + 360) % 360
        this.attitudeAt = now
      }
    } else if (messageId === 253 && payload[0] <= 4) {
      const message = textDecoder.decode(payload.subarray(1, 51)).split('\0', 1)[0].trim()
      if (message) this.statusText = { message, at: now }
    }
  }

  private requireFlightLink(): void {
    const view = this.view()
    if (!view.held || !view.camera || !view.heartbeat || view.position === null || view.landed === null) {
      throw new Error('Flight control or live telemetry lost')
    }
  }

  private async confirm(predicate: (view: QuadFlightView) => boolean): Promise<void> {
    const deadline = performance.now() + 20_000
    while (performance.now() < deadline) {
      this.requireFlightLink()
      if (predicate(this.view())) return
      await new Promise((resolve) => window.setTimeout(resolve, 100))
    }
    throw new Error('Timed out waiting for flight telemetry')
  }

  private async perform(command: FlightCommand, run: () => Promise<void>): Promise<void> {
    this.command = command
    this.error = null
    try {
      await run()
    } catch (error) {
      const detail = error instanceof Error ? error.message : 'MAVLink command failed'
      const status = this.statusText && performance.now() - this.statusText.at < 8_000 ? this.statusText.message : null
      this.error ??= `${command} failed · ${detail}${status ? ` · ${status}` : ''}`
      await this.release()
    } finally {
      this.command = null
    }
  }

  public sendMotion(sticks: ControllerSticks): void {
    const view = this.view()
    if (!view.canMove || !view.position || !this.sendQueueEmpty()) return
    const altitude = view.position.altitude
    try {
      this.session.sendActiveFrame((sequence) => buildQuadVelocity(sequence, sticks, altitude))
    } catch {
      this.close()
    }
  }
}
