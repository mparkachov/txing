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

const accumulateX25 = (crc: number, byte: number): number => {
  let temporary = byte ^ (crc & 0xff)
  temporary ^= (temporary << 4) & 0xff
  return ((crc >>> 8) ^ (temporary << 8) ^ (temporary << 3) ^ (temporary >>> 4)) & 0xffff
}

const mavlinkCrc = (bytes: Uint8Array, crcExtra: number): number => {
  let crc = 0xffff
  for (const byte of bytes) {
    crc = accumulateX25(crc, byte)
  }
  return accumulateX25(crc, crcExtra)
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
  return { binaryFrames, handle, session, states, telemetry, textMessages }
}

const lastRequest = (messages: string[]): Record<string, unknown> =>
  JSON.parse(messages[messages.length - 1] ?? '{}') as Record<string, unknown>

describe('shared MAVLink Office control', () => {
  test('explicit manual takeover ignores a stale empty owner cache and uses ordinary Manual/Arm commands', async () => {
    const fixture = createSession()
    fixture.handle.sendText = (message) => {
      fixture.textMessages.push(message)
      const request = lastRequest(fixture.textMessages)
      expect(request).toMatchObject({ type: 'control.activate', takeover: true })
      fixture.session.handleMessage(controlResponse(String(request.requestId), controlState({
        activeControl: { actor: 'human@example.test', sessionId: 'office-owner', epoch: 12 },
      }), 'control.activated'))
    }
    fixture.handle.sendBinary = (frame) => {
      fixture.binaryFrames.push(frame)
      const parsed = parseMavlinkFrame(frame)
      const payload = new DataView(parsed.payload.buffer, parsed.payload.byteOffset, parsed.payload.byteLength)
      const command = payload.getUint16(28, true)
      queueMicrotask(() => {
        fixture.session.handleMessage(commandAckFrame(command))
        fixture.session.handleMessage(heartbeatFrame({ armed: command === 400, mode: 0 }))
      })
    }
    expect(fixture.states).toEqual([])
    await fixture.session.takeManualControl(target)
    expect(fixture.binaryFrames.map((frame) => {
      const parsed = parseMavlinkFrame(frame)
      return new DataView(parsed.payload.buffer, parsed.payload.byteOffset).getUint16(28, true)
    })).toEqual([176, 400])
    const arm = parseMavlinkFrame(fixture.binaryFrames[1])
    expect(new DataView(arm.payload.buffer, arm.payload.byteOffset).getFloat32(4, true)).toBe(0)
    expect(fixture.states.at(-1)?.held).toBe(true)
    fixture.session.close()
  })

  test('releases a granted takeover when ordinary Manual preparation fails, without sending Arm', async () => {
    const fixture = createSession()
    fixture.handle.sendText = (message) => {
      fixture.textMessages.push(message)
      const request = lastRequest(fixture.textMessages)
      fixture.session.handleMessage(controlResponse(String(request.requestId), controlState({
        activeControl: request.type === 'control.activate'
          ? { actor: 'human@example.test', sessionId: 'office-owner', epoch: 12 }
          : null,
        epoch: 12,
      }), request.type === 'control.activate' ? 'control.activated' : 'control.released'))
    }
    fixture.handle.sendBinary = (frame) => {
      fixture.binaryFrames.push(frame)
      queueMicrotask(() => {
        fixture.session.handleMessage(commandAckFrame(176, 2))
        fixture.session.handleMessage(heartbeatFrame({ armed: false, mode: 0 }))
      })
    }
    await expect(fixture.session.takeManualControl(target)).rejects.toThrow('was rejected')
    expect(fixture.textMessages.map((message) => JSON.parse(message).type)).toEqual([
      'control.activate', 'control.release_active',
    ])
    expect(fixture.binaryFrames).toHaveLength(1)
    expect(fixture.states.at(-1)?.held).toBe(false)
    fixture.session.close()
  })

  test('retires an unanswered activation channel and fences late replies until a fresh explicit attempt', async () => {
    const timers = new Map<number, { delay: number; run: () => void }>()
    let nextTimer = 0
    let closeCount = 0
    let lateTelemetry = 0
    const messages: string[] = []
    const connectionStates: string[] = []
    const session = new MavlinkControlSession({
      actor: 'human@example.test',
      requestId: () => 'unanswered-activation',
      setTimeout: ((run: () => void, delay: number) => {
        const id = ++nextTimer
        timers.set(id, { run, delay })
        return id
      }) as typeof window.setTimeout,
      clearTimeout: ((id: number) => { timers.delete(id) }) as typeof window.clearTimeout,
      onControlState: () => {},
      onFlightState: () => {},
      onTelemetry: () => { lateTelemetry += 1 },
      onProtocolError: () => {},
      onStateChange: (state) => { connectionStates.push(state) },
    })
    session.attach({
      close: () => { closeCount += 1 },
      sendBinary: () => { throw new Error('timeout must not send flight commands') },
      sendText: (message) => { messages.push(message) },
    })
    const activation = session.activate(true)
    void activation.catch(() => undefined)
    const timeout = [...timers.values()].find(({ delay }) => delay === 7_000)
    expect(timeout).toBeDefined()
    timeout?.run()
    await expect(activation).rejects.toThrow('Timed out waiting for control.activate')
    expect(closeCount).toBe(1)
    expect(connectionStates.at(-1)).toBe('closed')
    session.handleMessage(controlResponse('unanswered-activation', controlState({
      activeControl: { actor: 'human@example.test', sessionId: 'late-owner', epoch: 5 },
    }), 'control.activated'))
    session.handleMessage(heartbeatFrame({ armed: true }))
    expect(lateTelemetry).toBe(0)
    const retryOnOldChannel = session.activate(true)
    void retryOnOldChannel.catch(() => undefined)
    expect(messages).toHaveLength(1)
    session.close()
    await expect(retryOnOldChannel).rejects.toThrow('MAVLink data channel')

    const fresh = createSession()
    expect(fresh.textMessages).toEqual([])
    const explicitRetry = fresh.session.activate(true)
    const request = lastRequest(fresh.textMessages)
    expect(request).toMatchObject({ type: 'control.activate', takeover: true })
    fresh.session.handleMessage(controlResponse(String(request.requestId), controlState({
      activeControl: { actor: 'human@example.test', sessionId: 'new-owner', epoch: 6 },
    }), 'control.activated'))
    await explicitRetry
    expect(fresh.states.at(-1)?.held).toBe(true)
    fresh.session.close()
  })

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

  test('observes a signed MAVLink 2 frame without treating it as an Office protocol error', () => {
    const { session, telemetry } = createSession()
    const unsigned = heartbeatFrame({ armed: false })
    const signed = new Uint8Array(unsigned.byteLength + 13)
    signed.set(unsigned)
    signed[2] |= 0x01
    const checksumOffset = 10 + signed[1]
    const checksum = mavlinkCrc(signed.slice(1, checksumOffset), 50)
    signed[checksumOffset] = checksum & 0xff
    signed[checksumOffset + 1] = checksum >>> 8

    session.handleMessage(signed)

    expect(telemetry).toEqual([{
      componentId: 1,
      messageId: 0,
      sequence: 1,
      systemId: 1,
    }])
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

  test('uses ordinary Manual and Hold mode commands with acknowledgement and heartbeat confirmation', async () => {
    const { binaryFrames, session, textMessages } = createSession()
    const activate = session.activate(false)
    const activateRequest = lastRequest(textMessages)
    const owned = { sessionId: 'mavlink-2', actor: 'operator@example.test', epoch: 2 }
    session.handleMessage(controlResponse(String(activateRequest.requestId), controlState({ activeControl: owned }), 'control.activated'))
    await activate

    const manual = session.selectMode(target, 'manual')
    const manualFrame = parseMavlinkFrame(binaryFrames.at(-1) ?? new Uint8Array())
    const manualPayload = new DataView(
      manualFrame.payload.buffer,
      manualFrame.payload.byteOffset,
      manualFrame.payload.byteLength,
    )
    expect(manualFrame.messageId).toBe(76)
    expect(manualPayload.getUint16(28, true)).toBe(176)
    expect(manualPayload.getFloat32(0, true)).toBe(1)
    expect(manualPayload.getFloat32(4, true)).toBe(0)
    session.handleMessage(commandAckFrame(176))
    session.handleMessage(heartbeatFrame({ armed: false, mode: 0 }))
    await expect(manual).resolves.toBeUndefined()

    const hold = session.selectMode(target, 'hold')
    const holdFrame = parseMavlinkFrame(binaryFrames.at(-1) ?? new Uint8Array())
    const holdPayload = new DataView(
      holdFrame.payload.buffer,
      holdFrame.payload.byteOffset,
      holdFrame.payload.byteLength,
    )
    expect(holdPayload.getUint16(28, true)).toBe(176)
    expect(holdPayload.getFloat32(0, true)).toBe(1)
    expect(holdPayload.getFloat32(4, true)).toBe(4)
    session.handleMessage(commandAckFrame(176))
    session.handleMessage(heartbeatFrame({ armed: false, mode: 4 }))
    await expect(hold).resolves.toBeUndefined()
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

  test('refreshes drive input at 10 Hz, including neutral while control remains active', () => {
    const controls: Array<{ steering: number; throttle: number }> = []
    const teleop = new MavlinkDriveTeleopController({
      sendControl: (steering, throttle) => controls.push({ steering, throttle }),
    })
    teleop.activate()
    teleop.tick()
    teleop.handleKeyDown('ArrowUp')
    teleop.tick()
    teleop.handleKeyUp('ArrowUp')
    teleop.handleSafetyStop()
    teleop.deactivate()

    expect(mavlinkDriveRefreshMs).toBe(100)
    expect(controls).toEqual([
      { steering: 0, throttle: 0 },
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
