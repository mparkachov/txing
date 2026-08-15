import { readFileSync } from 'node:fs'
import { describe, expect, test } from 'bun:test'
import {
  MavlinkControlError,
  MavlinkControlSession,
  MavlinkDriveTeleopController,
  buildMavlinkControlAxes,
  buildMavlinkManualControlFrame,
  mavlinkDriveRefreshMs,
  parseMavlinkControlEnvelope,
  type MavlinkDataChannelHandle,
  type MavlinkTelemetry,
} from '../src/mavlink-control'
import { buildMavlinkFrame, parseMavlinkFrame } from '../src/mavlink-wire'

const target = { systemId: 1, componentId: 1 }

const controlState = ({
  activeControl = null,
  epoch = activeControl?.epoch ?? 0,
}: {
  activeControl?: { actor: string; epoch: number; sessionId: string } | null
  epoch?: number
} = {}) => ({
  epoch,
  leaseTtlMs: 5_000,
  activeControl,
})

const controlResponse = (
  requestId: string,
  state: ReturnType<typeof controlState>,
  type: 'control.activated' | 'control.released' | 'control.renewed' | 'control.state' = 'control.state',
): string => JSON.stringify({ type, requestId, state })

const heartbeatFrame = ({ armed, mode = 0 }: { armed: boolean; mode?: number }): Uint8Array => {
  const payload = new Uint8Array(9)
  const view = new DataView(payload.buffer)
  view.setUint32(0, mode, true)
  payload[6] = armed ? 0x80 : 0
  return buildMavlinkFrame({
    componentId: 1,
    messageId: 0,
    payload,
    sequence: 1,
    systemId: 1,
  })
}

const commandAckFrame = (command: number, result = 0): Uint8Array => {
  const payload = new Uint8Array(3)
  new DataView(payload.buffer).setUint16(0, command, true)
  payload[2] = result
  return buildMavlinkFrame({
    componentId: 1,
    messageId: 77,
    payload,
    sequence: 2,
    systemId: 1,
  })
}

const createSession = () => {
  const textMessages: string[] = []
  const binaryFrames: Uint8Array[] = []
  const states: Array<{ held: boolean; state: ReturnType<typeof controlState> }> = []
  const telemetry: MavlinkTelemetry[] = []
  const session = new MavlinkControlSession({
    actor: 'operator@example.test',
    requestId: (() => {
      let next = 0
      return () => `request-${++next}`
    })(),
    setTimeout: (() => 1) as typeof window.setTimeout,
    clearTimeout: (() => undefined) as typeof window.clearTimeout,
    onControlState: (state, held) => states.push({ state, held }),
    onFlightState: () => {},
    onTelemetry: (frame) => telemetry.push(frame),
    onProtocolError: (message) => {
      throw new Error(message)
    },
  })
  const handle: MavlinkDataChannelHandle = {
    close: () => {},
    sendBinary: (frame) => binaryFrames.push(frame),
    sendText: (message) => textMessages.push(message),
  }
  session.attach(handle)
  return { binaryFrames, session, states, telemetry, textMessages }
}

const lastRequest = (messages: string[]): Record<string, unknown> =>
  JSON.parse(messages[messages.length - 1] ?? '{}') as Record<string, unknown>

describe('Cyberbrick MAVLink Office control', () => {
  test('negotiates a separate data-only peer with no video transceiver or VideoPanel lifecycle', () => {
    const runtime = readFileSync(new URL('../src/mavlink-session-runtime.ts', import.meta.url), 'utf8')
    const panel = readFileSync(
      new URL('../../devices/cyberbrick/web/MavlinkControlPanel.tsx', import.meta.url),
      'utf8',
    )

    expect(runtime).toContain("peerConnection.createDataChannel(options.label, {")
    expect(runtime).toContain('ordered: true')
    expect(runtime).not.toContain('addTransceiver')
    expect(runtime).not.toContain('getReceivers')
    expect(panel).not.toContain('VideoPanel')
  })

  test('lets an observer read state without transmitting a control frame', async () => {
    const { binaryFrames, session, telemetry, textMessages } = createSession()

    const statePromise = session.getState()
    const request = lastRequest(textMessages)
    session.handleMessage(controlResponse(String(request.requestId), controlState({
      activeControl: { sessionId: 'mavlink-8', actor: 'other@example.test', epoch: 8 },
    })))

    await expect(statePromise).resolves.toEqual(controlState({
      activeControl: { sessionId: 'mavlink-8', actor: 'other@example.test', epoch: 8 },
    }))
    session.handleMessage(heartbeatFrame({ armed: false }))
    expect(telemetry).toEqual([{
      componentId: 1,
      messageId: 0,
      sequence: 1,
      systemId: 1,
    }])
    expect(binaryFrames).toEqual([])
  })

  test('uses stable acquire, busy, takeover, stale-epoch, and release envelopes', async () => {
    const { session, states, textMessages } = createSession()

    const busy = session.activate(false)
    const acquireRequest = lastRequest(textMessages)
    expect(acquireRequest).toMatchObject({
      type: 'control.activate',
      actor: 'operator@example.test',
      takeover: false,
    })
    session.handleMessage(JSON.stringify({
      type: 'control.error',
      requestId: acquireRequest.requestId,
      code: 'control_busy',
      message: 'active control busy',
    }))
    await expect(busy).rejects.toEqual(new MavlinkControlError('control_busy', 'active control busy'))

    const takeover = session.activate(true)
    const takeoverRequest = lastRequest(textMessages)
    expect(takeoverRequest).toMatchObject({ type: 'control.activate', takeover: true })
    const owned = { sessionId: 'mavlink-9', actor: 'operator@example.test', epoch: 9 }
    session.handleMessage(controlResponse(String(takeoverRequest.requestId), controlState({ activeControl: owned }), 'control.activated'))
    await takeover
    expect(states.at(-1)).toEqual({ state: controlState({ activeControl: owned }), held: true })

    const release = session.release()
    const releaseRequest = lastRequest(textMessages)
    expect(releaseRequest).toMatchObject({ type: 'control.release_active', epoch: 9 })
    session.handleMessage(controlResponse(String(releaseRequest.requestId), controlState({ epoch: 9 }), 'control.released'))
    await release

    await expect(session.sendNeutral(target)).rejects.toMatchObject({ code: 'stale_epoch' })
  })

  test('allows only the active session to arm or disarm and requires acknowledgement plus heartbeat confirmation', async () => {
    const { binaryFrames, session, textMessages } = createSession()
    await expect(session.armDisarm(target, true)).rejects.toMatchObject({ code: 'stale_epoch' })

    const activate = session.activate(false)
    const activateRequest = lastRequest(textMessages)
    const owned = { sessionId: 'mavlink-1', actor: 'operator@example.test', epoch: 1 }
    session.handleMessage(controlResponse(String(activateRequest.requestId), controlState({ activeControl: owned }), 'control.activated'))
    await activate

    let completed = false
    const arm = session.armDisarm(target, true).then(() => {
      completed = true
    })
    const armFrame = parseMavlinkFrame(binaryFrames.at(-1) ?? new Uint8Array())
    expect(armFrame.messageId).toBe(76)
    const payload = new DataView(armFrame.payload.buffer, armFrame.payload.byteOffset, armFrame.payload.byteLength)
    expect(payload.getFloat32(0, true)).toBe(1)
    expect(payload.getFloat32(4, true)).toBe(0)
    session.handleMessage(commandAckFrame(400))
    await Promise.resolve()
    expect(completed).toBe(false)
    session.handleMessage(heartbeatFrame({ armed: true }))
    await arm
    expect(completed).toBe(true)

    const disarm = session.armDisarm(target, false)
    session.handleMessage(commandAckFrame(400))
    session.handleMessage(heartbeatFrame({ armed: false }))
    await expect(disarm).resolves.toBeUndefined()
  })

  test('maps Rover steering to y, throttle to z, and marks x/r invalid', () => {
    expect(buildMavlinkControlAxes(['ArrowLeft', 'ArrowUp'])).toEqual({
      steering: -1000,
      throttle: 1000,
    })
    expect(buildMavlinkControlAxes(['ArrowRight', 'ArrowDown'])).toEqual({
      steering: 1000,
      throttle: -1000,
    })
    const frame = parseMavlinkFrame(buildMavlinkManualControlFrame({
      sequence: 3,
      steering: -1000,
      throttle: 1000,
      target,
    }))
    const view = new DataView(frame.payload.buffer, frame.payload.byteOffset, frame.payload.byteLength)
    expect(view.getInt16(0, true)).toBe(0x7fff)
    expect(view.getInt16(2, true)).toBe(-1000)
    expect(view.getInt16(4, true)).toBe(1000)
    expect(view.getInt16(6, true)).toBe(0x7fff)
    expect(frame.payload[10]).toBe(1)
  })

  test('refreshes held drive input at 10 Hz and sends neutral on stop, blur, and deactivation', () => {
    const controls: Array<{ steering: number; throttle: number }> = []
    const teleop = new MavlinkDriveTeleopController({
      sendControl: (steering, throttle) => controls.push({ steering, throttle }),
    })
    teleop.activate()
    teleop.handleKeyDown('ArrowUp')
    teleop.tick()
    teleop.handleKeyUp('ArrowUp')
    teleop.handleSafetyStop()
    teleop.deactivate()

    expect(mavlinkDriveRefreshMs).toBe(100)
    expect(controls).toEqual([
      { steering: 0, throttle: 1000 },
      { steering: 0, throttle: 1000 },
      { steering: 0, throttle: 0 },
      { steering: 0, throttle: 0 },
      { steering: 0, throttle: 0 },
    ])
  })

  test('rejects invalid control envelopes before they can mutate active control state', () => {
    expect(parseMavlinkControlEnvelope({
      type: 'control.activated',
      requestId: 'request-1',
      state: { epoch: 1, leaseTtlMs: 3_000, activeControl: null },
    })).toBeNull()
    expect(parseMavlinkControlEnvelope({
      type: 'control.error',
      requestId: 'request-1',
      code: 'stale_epoch',
      message: 'old owner',
    })).toEqual({
      type: 'control.error',
      requestId: 'request-1',
      code: 'stale_epoch',
      message: 'old owner',
    })
  })
})
