import { afterAll, beforeAll, expect, test } from 'bun:test'
import { VirtualQuadFlight, readQuadPosition } from '../../devices/virtual-quad/web/virtual-quad-flight'
import { buildMavlinkFrame, parseMavlinkFrame, type MavlinkFrame } from '../src/mavlink-wire'

const previousWindow = Object.getOwnPropertyDescriptor(globalThis, 'window')
beforeAll(() => Object.defineProperty(globalThis, 'window', { configurable: true, value: globalThis }))
afterAll(() => {
  if (previousWindow) Object.defineProperty(globalThis, 'window', previousWindow)
  else Reflect.deleteProperty(globalThis, 'window')
})

const flush = async () => { await new Promise((resolve) => setTimeout(resolve, 0)) }

function fixture({ denyArm = false, occupied = false }: { denyArm?: boolean; occupied?: boolean } = {}) {
  let cameraAt = performance.now()
  let canSend = true
  let owner = occupied
  let sequence = 0
  let mode = 0
  let armed = false
  const text: { type: string; takeover?: boolean; epoch?: number }[] = []
  const binary: MavlinkFrame[] = []
  const flight = new VirtualQuadFlight({
    actor: 'Test pilot', videoAt: () => cameraAt, sendQueueEmpty: () => canSend, onClose: () => {},
  })
  const send = (messageId: number, payload: Uint8Array, systemId = 1) => flight.handleMessage(buildMavlinkFrame({
    componentId: 1, messageId, payload, sequence: sequence++, systemId,
  }))
  const telemetry = (landed: number, altitudeMm: number) => {
    const heartbeat = new Uint8Array(9)
    new DataView(heartbeat.buffer).setUint32(0, mode, true)
    heartbeat[6] = armed ? 0x80 : 0
    send(0, heartbeat)
    const position = new Uint8Array(28)
    new DataView(position.buffer).setInt32(16, altitudeMm, true)
    send(33, position)
    send(245, new Uint8Array([0, landed]))
  }
  flight.attach({
    close: () => {},
    sendText: (data) => {
      const request = JSON.parse(data)
      text.push(request)
      const responseType = {
        'control.get_state': 'control.state', 'control.activate': 'control.activated',
        'control.release_active': 'control.released',
      }[request.type as string]
      if (request.type === 'control.activate') owner = true
      if (request.type === 'control.release_active') owner = false
      flight.handleMessage(JSON.stringify({
        type: responseType, requestId: request.requestId,
        state: { epoch: 1, leaseTtlMs: 5_000, activeControl: owner ? { actor: 'Test pilot', epoch: 1, sessionId: 'pilot' } : null },
      }))
    },
    sendBinary: (data) => {
      const frame = parseMavlinkFrame(data)
      binary.push(frame)
      if (frame.messageId !== 76) return
      const payload = new DataView(frame.payload.buffer, frame.payload.byteOffset, frame.payload.byteLength)
      const command = payload.getUint16(28, true)
      queueMicrotask(() => {
        if (command === 400 && denyArm) {
          const status = new Uint8Array(51)
          status[0] = 4
          status.set(new TextEncoder().encode('PreArm: simulated rejection'), 1)
          send(253, status)
          send(77, new Uint8Array([command & 255, command >> 8, 2]))
          return
        }
        send(77, new Uint8Array([command & 255, command >> 8, 2]), 2)
        // A successful MAVLink 2 ACK may omit the trailing zero result.
        send(77, new Uint8Array([command & 255, command >> 8]))
        if (command === 176) mode = payload.getFloat32(4, true)
        if (command === 400) armed = payload.getFloat32(0, true) === 1
        if (mode === 9) armed = false
        telemetry(command === 22 ? 2 : 1, command === 22 ? 2_000 : 0)
      })
    },
  })
  telemetry(1, 0)
  return {
    flight, binary, text,
    loseCamera: () => { cameraAt = -Infinity },
    recoverCamera: () => { cameraAt = performance.now() },
    blockSend: () => { canSend = false },
    altitude: (millimeters: number) => telemetry(2, millimeters),
  }
}

const fields = (frame: MavlinkFrame) => new DataView(frame.payload.buffer, frame.payload.byteOffset, frame.payload.byteLength)

test('decodes flight positions for observation including a trimmed north heading', () => {
  const payload = new Uint8Array(24)
  const position = new DataView(payload.buffer)
  position.setInt32(4, -353632610, true)
  position.setInt32(8, 1491652300, true)
  position.setInt32(16, 2051, true)
  position.setInt16(20, -30, true)
  position.setInt16(22, 40, true)
  expect(readQuadPosition(payload)).toEqual({
    latitude: -35.363261, longitude: 149.16523, altitude: 2.051, heading: 0, speed: 0.5,
  })
})

test('explicit acquire, takeoff, body-relative flight, hover and landed confirmation', async () => {
  const { flight, binary, text, altitude, blockSend } = fixture()
  try {
    await flush()
    expect(flight.view()).toMatchObject({ held: false, canAcquire: true, armed: false })
    await flight.acquire()
    expect(text.at(-1)).toMatchObject({ type: 'control.activate', takeover: false })
    expect(binary).toHaveLength(0)
    await flight.takeOff()
    expect(binary.map((frame) => fields(frame).getUint16(28, true))).toEqual([176, 400, 22])
    expect(fields(binary[0]).getFloat32(4, true)).toBe(4)
    expect(fields(binary[1]).getFloat32(4, true)).toBe(0)
    expect(fields(binary[2]).getFloat32(24, true)).toBe(2)
    expect(flight.view()).toMatchObject({ mode: 'Guided', armed: true, canMove: true, landed: 2 })

    flight.setInput('w', 'forward')
    flight.setInput('d', 'right')
    flight.setInput('r', 'up')
    flight.setInput('e', 'yawRight')
    flight.tick()
    const move = binary.at(-1)!
    expect(move.messageId).toBe(84)
    expect(move.payload[52]).toBe(9)
    expect(fields(move).getUint16(48, true)).toBe(1479)
    expect(fields(move).getFloat32(16, true)).toBeCloseTo(Math.SQRT1_2)
    expect(fields(move).getFloat32(20, true)).toBeCloseTo(Math.SQRT1_2)
    expect(fields(move).getFloat32(24, true)).toBe(-0.5)
    expect(fields(move).getFloat32(44, true)).toBeCloseTo(Math.PI / 6)
    altitude(3_800)
    flight.tick()
    expect(fields(binary.at(-1)!).getFloat32(24, true)).toBe(0)
    flight.clearInput()
    const hover = fields(binary.at(-1)!)
    for (const offset of [16, 20, 24, 44]) expect(hover.getFloat32(offset, true)).toBe(0)
    const beforeBlockedSend = binary.length
    blockSend()
    flight.tick()
    expect(binary).toHaveLength(beforeBlockedSend)

    await flight.land()
    expect(fields(binary.at(-1)!).getFloat32(4, true)).toBe(9)
    expect(flight.view()).toMatchObject({ mode: 'Land', armed: false, landed: 1, canMove: false })
  } finally {
    flight.close()
  }
})

test('camera loss in flight releases the lease, stops movement, and requires explicit reacquisition', async () => {
  const { flight, loseCamera, recoverCamera, text, binary } = fixture()
  try {
    await flush()
    await flight.acquire()
    await flight.takeOff()
    flight.setInput('w', 'forward')
    flight.tick()
    const move = binary.at(-1)!
    expect(move.messageId).toBe(84)
    expect(fields(move).getFloat32(16, true)).toBe(1)
    const writesBeforeLoss = binary.length
    loseCamera()
    flight.tick()
    await flush()
    expect(text.at(-1)).toMatchObject({ type: 'control.release_active', epoch: 1 })
    expect(flight.view()).toMatchObject({ held: false, camera: false, canAcquire: false, canMove: false })
    recoverCamera()
    flight.setInput('w', 'forward')
    flight.tick()
    expect(flight.view()).toMatchObject({ held: false, camera: true, canAcquire: true, canMove: false })
    expect(binary).toHaveLength(writesBeforeLoss)
    expect(text.filter(({ type }) => type === 'control.activate')).toHaveLength(1)
  } finally {
    flight.close()
  }
})

test('an arm rejection is shown with the autopilot reason and prevents takeoff', async () => {
  const { flight, text, binary } = fixture({ denyArm: true })
  try {
    await flush()
    await flight.acquire()
    await flight.takeOff()
    expect(binary.map((frame) => fields(frame).getUint16(28, true))).toEqual([176, 400])
    expect(text.at(-1)).toMatchObject({ type: 'control.release_active', epoch: 1 })
    expect(flight.view()).toMatchObject({ held: false, armed: false })
    expect(flight.view().error).toContain('PreArm: simulated rejection')
  } finally {
    flight.close()
  }
})

test('a new connection with the same actor stays view only when the previous lease is still visible', async () => {
  const { flight, text, binary } = fixture({ occupied: true })
  try {
    await flush()
    expect(flight.view()).toMatchObject({ held: false, owner: 'Test pilot', canAcquire: false, canTakeOff: false })
    await flight.acquire()
    await flight.takeOff()
    expect(text.map(({ type }) => type)).toEqual(['control.get_state'])
    expect(binary).toHaveLength(0)
  } finally {
    flight.close()
  }
})
