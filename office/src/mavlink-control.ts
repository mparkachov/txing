import { buildMavlinkFrame, parseMavlinkFrame, type MavlinkFrame } from './mavlink-wire'

export const mavlinkWebRtcDataChannelLabel = 'txing.mavlink.v1'
export const mavlinkControlLeaseTtlMs = 5_000
export const mavlinkDriveRefreshMs = 100

const mavlinkGcsSystemId = 255
const mavlinkGcsComponentId = 190
const mavlinkHeartbeatMessageId = 0
const mavlinkManualControlMessageId = 69
const mavlinkCommandLongMessageId = 76
const mavlinkCommandAckMessageId = 77
const mavlinkCommandComponentArmDisarm = 400
const mavlinkCommandDoSetMode = 176
const mavlinkModeManual = 0
const mavlinkModeHold = 4
const mavlinkCustomModeEnabledBaseMode = 1
const mavlinkSafetyArmedFlag = 0x80
const mavlinkAxisInvalid = 0x7fff
const mavlinkRequestTimeoutMs = 7_000

export type MavlinkControlErrorCode = 'control_busy' | 'stale_epoch' | 'invalid_request'

export class MavlinkControlError extends Error {
  public readonly code: MavlinkControlErrorCode

  public constructor(
    code: MavlinkControlErrorCode,
    message: string,
  ) {
    super(message)
    this.name = 'MavlinkControlError'
    this.code = code
  }
}

export type MavlinkActiveControl = {
  actor: string
  epoch: number
  sessionId: string
}

export type MavlinkControlState = {
  activeControl: MavlinkActiveControl | null
  epoch: number
  leaseTtlMs: number
}

export type MavlinkFlightState = {
  armed: boolean | null
  mode: 'hold' | 'manual' | string | null
}

export type MavlinkTelemetry = {
  componentId: number
  messageId: number
  sequence: number
  systemId: number
}

export type MavlinkTarget = {
  componentId: number
  systemId: number
}

export type MavlinkDataChannelHandle = {
  close: () => void
  sendBinary: (frame: Uint8Array) => void
  sendText: (message: string) => void
}

export type MavlinkControlSessionOptions = {
  actor: string
  onControlState: (state: MavlinkControlState, activeHeldByCaller: boolean) => void
  onFlightState: (state: MavlinkFlightState) => void
  onProtocolError: (message: string) => void
  onStateChange?: (state: 'connected' | 'closed') => void
  onTelemetry?: (telemetry: MavlinkTelemetry) => void
  requestId?: () => string
  setTimeout?: typeof window.setTimeout
  clearTimeout?: typeof window.clearTimeout
}

type PendingControlRequest = {
  reject: (error: Error) => void
  resolve: (state: MavlinkControlState, responseType: ControlSuccessType) => void
  timeoutId: number
}

type PendingCommand = {
  command: number
  reject: (error: Error) => void
  resolve: () => void
  timeoutId: number
}

type FlightStateWaiter = {
  predicate: (state: MavlinkFlightState) => boolean
  reject: (error: Error) => void
  resolve: () => void
  timeoutId: number
}

type ControlSuccessType =
  | 'control.state'
  | 'control.activated'
  | 'control.renewed'
  | 'control.released'

type ControlSuccessEnvelope = {
  requestId: string
  state: MavlinkControlState
  type: ControlSuccessType
}

type ControlErrorEnvelope = {
  code: MavlinkControlErrorCode
  message: string
  requestId: string
  type: 'control.error'
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value)

const isControlErrorCode = (value: unknown): value is MavlinkControlErrorCode =>
  value === 'control_busy' || value === 'stale_epoch' || value === 'invalid_request'

const isControlSuccessType = (value: unknown): value is ControlSuccessType =>
  value === 'control.state' ||
  value === 'control.activated' ||
  value === 'control.renewed' ||
  value === 'control.released'

const asNonNegativeInteger = (value: unknown): number | null =>
  typeof value === 'number' && Number.isInteger(value) && value >= 0 ? value : null

export const parseMavlinkControlState = (value: unknown): MavlinkControlState | null => {
  if (!isRecord(value)) {
    return null
  }
  const epoch = asNonNegativeInteger(value.epoch)
  const leaseTtlMs = asNonNegativeInteger(value.leaseTtlMs)
  if (epoch === null || leaseTtlMs !== mavlinkControlLeaseTtlMs) {
    return null
  }
  if (value.activeControl === null) {
    return {
      activeControl: null,
      epoch,
      leaseTtlMs,
    }
  }
  if (!isRecord(value.activeControl)) {
    return null
  }
  const activeEpoch = asNonNegativeInteger(value.activeControl.epoch)
  if (
    typeof value.activeControl.sessionId !== 'string' ||
    value.activeControl.sessionId.trim() === '' ||
    typeof value.activeControl.actor !== 'string' ||
    value.activeControl.actor.trim() === '' ||
    activeEpoch === null
  ) {
    return null
  }
  return {
    activeControl: {
      sessionId: value.activeControl.sessionId,
      actor: value.activeControl.actor,
      epoch: activeEpoch,
    },
    epoch,
    leaseTtlMs,
  }
}

export const parseMavlinkControlEnvelope = (
  value: unknown,
): ControlSuccessEnvelope | ControlErrorEnvelope | null => {
  if (!isRecord(value) || typeof value.type !== 'string' || typeof value.requestId !== 'string') {
    return null
  }
  if (isControlSuccessType(value.type)) {
    const state = parseMavlinkControlState(value.state)
    return state ? { type: value.type, requestId: value.requestId, state } : null
  }
  if (
    value.type === 'control.error' &&
    isControlErrorCode(value.code) &&
    typeof value.message === 'string' &&
    value.message.trim() !== ''
  ) {
    return {
      type: value.type,
      requestId: value.requestId,
      code: value.code,
      message: value.message,
    }
  }
  return null
}

const createRequestId = (): string =>
  typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
    ? crypto.randomUUID()
    : `mavlink-${Date.now()}-${Math.random().toString(16).slice(2)}`

const decodeFlightState = (frame: MavlinkFrame): MavlinkFlightState | null => {
  if (frame.messageId !== mavlinkHeartbeatMessageId || frame.payload.byteLength !== 9) {
    return null
  }
  const view = new DataView(frame.payload.buffer, frame.payload.byteOffset, frame.payload.byteLength)
  const customMode = view.getUint32(0, true)
  return {
    armed: (frame.payload[6] & mavlinkSafetyArmedFlag) !== 0,
    mode:
      customMode === mavlinkModeManual
        ? 'manual'
        : customMode === mavlinkModeHold
          ? 'hold'
          : `custom-${customMode}`,
  }
}

const decodeCommandAck = (frame: MavlinkFrame): { command: number; result: number } | null => {
  if (frame.messageId !== mavlinkCommandAckMessageId || frame.payload.byteLength < 3) {
    return null
  }
  const view = new DataView(frame.payload.buffer, frame.payload.byteOffset, frame.payload.byteLength)
  return {
    command: view.getUint16(0, true),
    result: frame.payload[2],
  }
}

const clampControlAxis = (value: number): number => Math.max(-1000, Math.min(1000, Math.round(value)))

const nextSequence = (sequence: number): number => (sequence + 1) & 0xff

export const buildMavlinkManualControlFrame = ({
  sequence,
  steering,
  target,
  throttle,
}: {
  sequence: number
  steering: number
  target: MavlinkTarget
  throttle: number
}): Uint8Array => {
  const payload = new Uint8Array(11)
  const view = new DataView(payload.buffer)
  // ArduRover uses y for left/right steering and z for forward/reverse
  // throttle. x and r are explicitly invalid rather than silently zeroed.
  view.setInt16(0, mavlinkAxisInvalid, true)
  view.setInt16(2, clampControlAxis(steering), true)
  view.setInt16(4, clampControlAxis(throttle), true)
  view.setInt16(6, mavlinkAxisInvalid, true)
  view.setUint16(8, 0, true)
  payload[10] = target.systemId
  return buildMavlinkFrame({
    componentId: mavlinkGcsComponentId,
    messageId: mavlinkManualControlMessageId,
    payload,
    sequence,
    systemId: mavlinkGcsSystemId,
  })
}

const buildMavlinkCommandLongFrame = ({
  command,
  param1,
  param2,
  sequence,
  target,
}: {
  command: number
  param1: number
  param2: number
  sequence: number
  target: MavlinkTarget
}): Uint8Array => {
  const payload = new Uint8Array(33)
  const view = new DataView(payload.buffer)
  view.setFloat32(0, param1, true)
  view.setFloat32(4, param2, true)
  view.setUint16(28, command, true)
  payload[30] = target.systemId
  payload[31] = target.componentId
  payload[32] = 0
  return buildMavlinkFrame({
    componentId: mavlinkGcsComponentId,
    messageId: mavlinkCommandLongMessageId,
    payload,
    sequence,
    systemId: mavlinkGcsSystemId,
  })
}

export const buildMavlinkArmDisarmFrame = ({
  armed,
  sequence,
  target,
}: {
  armed: boolean
  sequence: number
  target: MavlinkTarget
}): Uint8Array =>
  buildMavlinkCommandLongFrame({
    command: mavlinkCommandComponentArmDisarm,
    param1: armed ? 1 : 0,
    // Force arm/disarm uses a magic value here. The contract requires ordinary
    // commands only, so this field is always zero.
    param2: 0,
    sequence,
    target,
  })

export const buildMavlinkModeFrame = ({
  mode,
  sequence,
  target,
}: {
  mode: 'hold' | 'manual'
  sequence: number
  target: MavlinkTarget
}): Uint8Array =>
  buildMavlinkCommandLongFrame({
    command: mavlinkCommandDoSetMode,
    param1: mavlinkCustomModeEnabledBaseMode,
    param2: mode === 'manual' ? mavlinkModeManual : mavlinkModeHold,
    sequence,
    target,
  })

export class MavlinkControlSession {
  private readonly actor: string
  private readonly clearTimer: typeof window.clearTimeout
  private readonly onControlState: MavlinkControlSessionOptions['onControlState']
  private readonly onFlightState: MavlinkControlSessionOptions['onFlightState']
  private readonly onProtocolError: MavlinkControlSessionOptions['onProtocolError']
  private readonly onStateChange: MavlinkControlSessionOptions['onStateChange']
  private readonly onTelemetry: MavlinkControlSessionOptions['onTelemetry']
  private readonly requestId: () => string
  private readonly setTimer: typeof window.setTimeout
  private activeSessionId: string | null = null
  private controlState: MavlinkControlState = {
    activeControl: null,
    epoch: 0,
    leaseTtlMs: mavlinkControlLeaseTtlMs,
  }
  private flightState: MavlinkFlightState = { armed: null, mode: null }
  private handle: MavlinkDataChannelHandle | null = null
  private leaseRenewTimer: number | null = null
  private pendingCommand: PendingCommand | null = null
  private pendingControl = new Map<string, PendingControlRequest>()
  private readonly flightStateWaiters = new Set<FlightStateWaiter>()
  private sequence = 0
  private closed = false

  public constructor(options: MavlinkControlSessionOptions) {
    this.actor = options.actor.trim() || 'unknown signed-in user'
    this.onControlState = options.onControlState
    this.onFlightState = options.onFlightState
    this.onProtocolError = options.onProtocolError
    this.onStateChange = options.onStateChange
    this.onTelemetry = options.onTelemetry
    this.requestId = options.requestId ?? createRequestId
    this.setTimer = options.setTimeout ?? window.setTimeout.bind(window)
    this.clearTimer = options.clearTimeout ?? window.clearTimeout.bind(window)
  }

  public attach(handle: MavlinkDataChannelHandle): void {
    if (this.closed) {
      handle.close()
      return
    }
    this.handle = handle
    this.onStateChange?.('connected')
  }

  public async getState(): Promise<MavlinkControlState> {
    const { state } = await this.sendControlRequest('control.get_state')
    return state
  }

  public async activate(takeover: boolean): Promise<MavlinkControlState> {
    const { state } = await this.sendControlRequest('control.activate', {
      actor: this.actor,
      takeover,
    })
    if (!state.activeControl) {
      throw new Error('MAVLink control.activate returned no active control')
    }
    this.activeSessionId = state.activeControl.sessionId
    this.publishControlState(state)
    return state
  }

  public async release(): Promise<MavlinkControlState> {
    const epoch = this.requireActiveEpoch()
    const { state } = await this.sendControlRequest('control.release_active', { epoch })
    this.activeSessionId = null
    this.publishControlState(state)
    return state
  }

  public async sendManualControl(
    target: MavlinkTarget,
    steering: number,
    throttle: number,
  ): Promise<void> {
    this.requireActiveEpoch()
    this.sendFrame(buildMavlinkManualControlFrame({
      sequence: this.nextFrameSequence(),
      steering,
      target,
      throttle,
    }))
  }

  public async sendNeutral(target: MavlinkTarget): Promise<void> {
    await this.sendManualControl(target, 0, 0)
  }

  public async armDisarm(target: MavlinkTarget, armed: boolean): Promise<void> {
    this.requireActiveEpoch()
    const acknowledgement = this.waitForCommand(mavlinkCommandComponentArmDisarm)
    const confirmation = this.waitForFlightState((state) => state.armed === armed)
    try {
      this.sendFrame(buildMavlinkArmDisarmFrame({
        armed,
        sequence: this.nextFrameSequence(),
        target,
      }))
      await Promise.all([acknowledgement, confirmation])
    } finally {
      this.clearPendingCommand()
      this.clearFlightStateWaiters()
    }
  }

  public async selectMode(target: MavlinkTarget, mode: 'hold' | 'manual'): Promise<void> {
    this.requireActiveEpoch()
    const acknowledgement = this.waitForCommand(mavlinkCommandDoSetMode)
    const confirmation = this.waitForFlightState((state) => state.mode === mode)
    try {
      this.sendFrame(buildMavlinkModeFrame({
        mode,
        sequence: this.nextFrameSequence(),
        target,
      }))
      await Promise.all([acknowledgement, confirmation])
    } finally {
      this.clearPendingCommand()
      this.clearFlightStateWaiters()
    }
  }

  public handleMessage(message: string | Uint8Array): void {
    if (typeof message === 'string') {
      this.handleControlResponse(message)
      return
    }
    this.handleTelemetry(message)
  }

  public close(): void {
    if (this.closed) {
      return
    }
    this.closed = true
    this.clearLeaseRenewTimer()
    this.clearPendingCommand(new Error('MAVLink data channel closed'))
    this.clearFlightStateWaiters(new Error('MAVLink data channel closed'))
    for (const [requestId, pending] of this.pendingControl) {
      this.pendingControl.delete(requestId)
      this.clearTimer(pending.timeoutId)
      pending.reject(new Error('MAVLink data channel closed'))
    }
    this.handle?.close()
    this.handle = null
    this.activeSessionId = null
    this.onStateChange?.('closed')
  }

  private async renewActive(): Promise<void> {
    if (this.closed || !this.activeSessionId || !this.controlState.activeControl) {
      return
    }
    try {
      const { state } = await this.sendControlRequest('control.renew_active', {
        epoch: this.controlState.activeControl.epoch,
      })
      this.publishControlState(state)
    } catch (error) {
      this.activeSessionId = null
      this.publishControlState(this.controlState)
      this.onProtocolError(
        error instanceof Error ? `MAVLink active-control renewal failed: ${error.message}` : 'MAVLink active-control renewal failed',
      )
    }
  }

  private handleControlResponse(raw: string): void {
    let parsed: unknown
    try {
      parsed = JSON.parse(raw)
    } catch {
      this.onProtocolError('MAVLink control channel received invalid JSON')
      return
    }
    const envelope = parseMavlinkControlEnvelope(parsed)
    if (!envelope) {
      this.onProtocolError('MAVLink control channel received an invalid control envelope')
      return
    }
    const pending = this.pendingControl.get(envelope.requestId)
    if (!pending) {
      return
    }
    this.pendingControl.delete(envelope.requestId)
    this.clearTimer(pending.timeoutId)
    if (envelope.type === 'control.error') {
      pending.reject(new MavlinkControlError(envelope.code, envelope.message))
      return
    }
    this.publishControlState(envelope.state)
    pending.resolve(envelope.state, envelope.type)
  }

  private handleTelemetry(raw: Uint8Array): void {
    let frame: MavlinkFrame
    try {
      frame = parseMavlinkFrame(raw)
    } catch (error) {
      this.onProtocolError(
        error instanceof Error ? `MAVLink telemetry frame rejected: ${error.message}` : 'MAVLink telemetry frame rejected',
      )
      return
    }
    this.onTelemetry?.({
      componentId: frame.componentId,
      messageId: frame.messageId,
      sequence: frame.sequence,
      systemId: frame.systemId,
    })
    const flightState = decodeFlightState(frame)
    if (flightState) {
      this.flightState = flightState
      this.onFlightState(flightState)
      for (const waiter of [...this.flightStateWaiters]) {
        if (!waiter.predicate(flightState)) {
          continue
        }
        this.flightStateWaiters.delete(waiter)
        this.clearTimer(waiter.timeoutId)
        waiter.resolve()
      }
      return
    }
    const acknowledgement = decodeCommandAck(frame)
    if (!acknowledgement || !this.pendingCommand || acknowledgement.command !== this.pendingCommand.command) {
      return
    }
    const pending = this.pendingCommand
    this.pendingCommand = null
    this.clearTimer(pending.timeoutId)
    if (acknowledgement.result !== 0) {
      pending.reject(new Error(`MAVLink command ${acknowledgement.command} was rejected (${acknowledgement.result})`))
      return
    }
    pending.resolve()
  }

  private sendControlRequest(
    type: 'control.get_state' | 'control.activate' | 'control.renew_active' | 'control.release_active',
    fields: Record<string, unknown> = {},
  ): Promise<{ responseType: ControlSuccessType; state: MavlinkControlState }> {
    const handle = this.handle
    if (this.closed || !handle) {
      return Promise.reject(new Error('MAVLink data channel is not connected'))
    }
    const requestId = this.requestId()
    return new Promise((resolve, reject) => {
      const timeoutId = this.setTimer(() => {
        this.pendingControl.delete(requestId)
        reject(new Error(`Timed out waiting for ${type}`))
      }, mavlinkRequestTimeoutMs)
      this.pendingControl.set(requestId, {
        timeoutId,
        resolve: (state, responseType) => resolve({ state, responseType }),
        reject,
      })
      try {
        handle.sendText(JSON.stringify({ type, requestId, ...fields }))
      } catch (error) {
        this.pendingControl.delete(requestId)
        this.clearTimer(timeoutId)
        reject(error instanceof Error ? error : new Error(`Unable to send ${type}`))
      }
    })
  }

  private publishControlState(state: MavlinkControlState): void {
    this.controlState = state
    const activeHeldByCaller =
      this.activeSessionId !== null && state.activeControl?.sessionId === this.activeSessionId
    if (!activeHeldByCaller && state.activeControl?.sessionId !== this.activeSessionId) {
      this.activeSessionId = null
    }
    this.onControlState(state, activeHeldByCaller)
    this.clearLeaseRenewTimer()
    if (activeHeldByCaller) {
      const renewAfterMs = Math.max(1_000, state.leaseTtlMs - 1_500)
      this.leaseRenewTimer = this.setTimer(() => {
        this.leaseRenewTimer = null
        void this.renewActive()
      }, renewAfterMs)
    }
  }

  private requireActiveEpoch(): number {
    const active = this.controlState.activeControl
    if (!active || !this.activeSessionId || active.sessionId !== this.activeSessionId) {
      throw new MavlinkControlError('stale_epoch', 'MAVLink active control is required')
    }
    return active.epoch
  }

  private sendFrame(frame: Uint8Array): void {
    const handle = this.handle
    if (this.closed || !handle) {
      throw new Error('MAVLink data channel is not connected')
    }
    handle.sendBinary(frame)
  }

  private nextFrameSequence(): number {
    const next = this.sequence
    this.sequence = nextSequence(this.sequence)
    return next
  }

  private waitForCommand(command: number): Promise<void> {
    this.clearPendingCommand()
    return new Promise((resolve, reject) => {
      const timeoutId = this.setTimer(() => {
        if (this.pendingCommand?.command === command) {
          this.pendingCommand = null
        }
        reject(new Error(`Timed out waiting for MAVLink command ${command} acknowledgement`))
      }, mavlinkRequestTimeoutMs)
      this.pendingCommand = { command, resolve, reject, timeoutId }
    })
  }

  private waitForFlightState(predicate: (state: MavlinkFlightState) => boolean): Promise<void> {
    if (predicate(this.flightState)) {
      return Promise.resolve()
    }
    return new Promise((resolve, reject) => {
      const waiter: FlightStateWaiter = {
        predicate,
        resolve,
        reject,
        timeoutId: 0,
      }
      waiter.timeoutId = this.setTimer(() => {
        this.flightStateWaiters.delete(waiter)
        reject(new Error('Timed out waiting for MAVLink heartbeat state confirmation'))
      }, mavlinkRequestTimeoutMs)
      this.flightStateWaiters.add(waiter)
    })
  }

  private clearLeaseRenewTimer(): void {
    if (this.leaseRenewTimer !== null) {
      this.clearTimer(this.leaseRenewTimer)
      this.leaseRenewTimer = null
    }
  }

  private clearPendingCommand(error?: Error): void {
    const pending = this.pendingCommand
    if (!pending) {
      return
    }
    this.pendingCommand = null
    this.clearTimer(pending.timeoutId)
    if (error) {
      pending.reject(error)
    }
  }

  private clearFlightStateWaiters(error?: Error): void {
    for (const waiter of this.flightStateWaiters) {
      this.flightStateWaiters.delete(waiter)
      this.clearTimer(waiter.timeoutId)
      if (error) {
        waiter.reject(error)
      }
    }
  }
}

export class MavlinkDriveTeleopController {
  private readonly heldKeys = new Set<string>()
  private readonly sendControl: (steering: number, throttle: number) => Promise<void> | void
  private active = false

  public constructor(options: {
    sendControl: (steering: number, throttle: number) => Promise<void> | void
  }) {
    this.sendControl = options.sendControl
  }

  public activate(): void {
    this.active = true
  }

  public deactivate(): void {
    if (!this.active) {
      return
    }
    this.active = false
    this.sendNeutral()
  }

  public handleKeyDown(key: string): boolean {
    if (!this.active || !isMavlinkControlKey(key)) {
      return false
    }
    if (isMavlinkStopKey(key)) {
      this.sendNeutral()
      return true
    }
    this.heldKeys.add(key)
    this.sendCurrentControl()
    return true
  }

  public handleKeyUp(key: string): boolean {
    if (!this.active || !isMavlinkDirectionalKey(key)) {
      return false
    }
    this.heldKeys.delete(key)
    this.sendCurrentControl()
    return true
  }

  public handleSafetyStop(): void {
    if (this.active) {
      this.sendNeutral()
    }
  }

  public tick(): void {
    if (!this.active || this.heldKeys.size === 0) {
      return
    }
    this.sendCurrentControl()
  }

  private sendCurrentControl(): void {
    const { steering, throttle } = buildMavlinkControlAxes(this.heldKeys)
    void this.sendControl(steering, throttle)
  }

  private sendNeutral(): void {
    this.heldKeys.clear()
    void this.sendControl(0, 0)
  }
}

const mavlinkDirectionalKeys = new Set(['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'])

export const isMavlinkDirectionalKey = (key: string): boolean => mavlinkDirectionalKeys.has(key)

export const isMavlinkStopKey = (key: string): boolean => key.toLowerCase() === 's'

export const isMavlinkControlKey = (key: string): boolean =>
  isMavlinkDirectionalKey(key) || isMavlinkStopKey(key)

export const buildMavlinkControlAxes = (keys: Iterable<string>): {
  steering: number
  throttle: number
} => {
  const held = new Set(keys)
  return {
    steering: (held.has('ArrowRight') ? 1000 : 0) - (held.has('ArrowLeft') ? 1000 : 0),
    throttle: (held.has('ArrowUp') ? 1000 : 0) - (held.has('ArrowDown') ? 1000 : 0),
  }
}
