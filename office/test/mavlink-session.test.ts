import { EventEmitter } from 'node:events'
import { readFileSync } from 'node:fs'
import { describe, expect, test } from 'bun:test'
import { connectMavlinkPeer, startMavlinkDataChannelRuntime } from '../src/mavlink-session-runtime'
import { MavlinkControlSession } from '../src/mavlink-control'

class FakeDataChannel extends EventTarget {
  readyState = 'connecting'
  binaryType = ''
  closeCount = 0
  sent: Array<string | ArrayBuffer> = []

  open(): void {
    this.readyState = 'open'
    this.dispatchEvent(new Event('open'))
  }

  close(): void {
    this.closeCount += 1
    this.readyState = 'closed'
    this.dispatchEvent(new Event('close'))
  }

  send(data: string | ArrayBuffer): void {
    this.sent.push(data)
  }
}

class FakePeerConnection extends EventTarget {
  channel = new FakeDataChannel()
  connectionState = 'new'
  localDescription: RTCSessionDescriptionInit | null = null
  closeCount = 0
  offer: Promise<RTCSessionDescriptionInit> = Promise.resolve({ type: 'offer', sdp: 'data-only' })

  createDataChannel(): FakeDataChannel {
    return this.channel
  }

  createOffer(): Promise<RTCSessionDescriptionInit> {
    return this.offer
  }

  async setLocalDescription(description: RTCSessionDescriptionInit): Promise<void> {
    this.localDescription = description
  }

  async setRemoteDescription(): Promise<void> {}
  async addIceCandidate(): Promise<void> {}

  close(): void {
    this.closeCount += 1
    this.connectionState = 'closed'
    this.dispatchEvent(new Event('connectionstatechange'))
  }
}

class FakeSignalingClient extends EventEmitter {
  closeCount = 0
  openCount = 0
  offers: RTCSessionDescriptionInit[] = []

  open(): void {
    this.openCount += 1
    this.emit('open')
  }

  close(): void {
    this.closeCount += 1
    this.emit('close')
  }

  sendIceCandidate(): void {}

  sendSdpOffer(description: RTCSessionDescriptionInit): void {
    this.offers.push(description)
  }
}

const createPeer = (signal?: AbortSignal) => {
  const peer = new FakePeerConnection()
  const signaling = new FakeSignalingClient()
  const states: Array<{ state: string; message?: string }> = []
  const messages: Array<string | Uint8Array> = []
  const opening = connectMavlinkPeer({
    label: 'txing.mavlink.v1',
    onMessage: (message) => messages.push(message),
    onStateChange: (state, message) => states.push({ state, message }),
    signal,
  }, peer as unknown as RTCPeerConnection, signaling, 5)
  // Capture failures immediately, including cancellation before awaiting them.
  void opening.catch(() => undefined)
  return { messages, opening, peer, signaling, states }
}

const openingOutcome = async (opening: Promise<unknown>): Promise<string> =>
  Promise.race([
    opening.then(() => 'open', (error: Error) => error.message),
    Bun.sleep(40).then(() => 'still connecting'),
  ])

describe('MAVLink connection after board wake', () => {
  test('waits for the projected MAVLink capability before opening a peer', () => {
    const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8')
    const enabled = appSource.match(/const isMavlinkControlEnabled =([\s\S]*?)\n {2}const /)?.[1]
    expect(enabled).toContain("extractSparkplugCapabilityAvailability(displayShadowDocument, 'mavlink') === true")
  })

  test('ends an unanswered offer and frees every resource so a fresh attempt can open', async () => {
    const first = createPeer()
    try {
      expect(await openingOutcome(first.opening)).toContain('timed out')
      expect(first.signaling.offers).toHaveLength(1)
      expect(first.signaling.closeCount).toBe(1)
      expect(first.peer.closeCount).toBe(1)
      expect(first.peer.channel.closeCount).toBe(1)
      expect(first.states.at(-1)?.state).toBe('error')

      const retry = createPeer()
      retry.peer.channel.open()
      const handle = await retry.opening
      expect(retry.states.at(-1)?.state).toBe('open')
      handle.close()
    } finally {
      if (first.peer.closeCount === 0) {
        first.signaling.emit('error', new Error('test cleanup'))
      }
    }
  })

  test('cancels an in-flight peer when the device sleeps or the route changes', async () => {
    const controller = new AbortController()
    const fixture = createPeer(controller.signal)
    controller.abort()
    try {
      expect(await openingOutcome(fixture.opening)).toContain('cancelled')
      expect(fixture.peer.closeCount).toBe(1)
      expect(fixture.signaling.closeCount).toBe(1)
      fixture.peer.channel.open()
      fixture.peer.channel.dispatchEvent(new MessageEvent('message', { data: 'late telemetry' }))
      expect(fixture.states.map(({ state }) => state)).toEqual(['closed'])
      expect(fixture.messages).toEqual([])
      expect(fixture.signaling.offers).toEqual([])
    } finally {
      if (fixture.peer.closeCount === 0) {
        fixture.signaling.emit('error', new Error('test cleanup'))
      }
    }
  })

  test('does not begin AWS or WebRTC setup for an already cancelled connection', async () => {
    const controller = new AbortController()
    controller.abort()
    let tokenRequests = 0
    await expect(startMavlinkDataChannelRuntime({
      channelName: 'tbot-test-mavlink',
      label: 'txing.mavlink.v1',
      onMessage: () => {},
      onStateChange: () => { throw new Error('cancelled startup must stay idle') },
      region: 'eu-central-1',
      resolveIdToken: async () => { tokenRequests += 1; return 'token' },
      signal: controller.signal,
    })).rejects.toHaveProperty('name', 'AbortError')
    expect(tokenRequests).toBe(0)
  })

  test('does not send an old offer after cancellation during local SDP preparation', async () => {
    const controller = new AbortController()
    const peer = new FakePeerConnection()
    const signaling = new FakeSignalingClient()
    let finishLocalDescription = (): void => {}
    const localDescriptionPending = new Promise<void>((resolve) => {
      finishLocalDescription = resolve
    })
    peer.setLocalDescription = async (description) => {
      await localDescriptionPending
      peer.localDescription = description
    }
    const opening = connectMavlinkPeer({
      label: 'txing.mavlink.v1',
      onMessage: () => {},
      onStateChange: () => {},
      signal: controller.signal,
    }, peer as unknown as RTCPeerConnection, signaling)
    await Promise.resolve()
    controller.abort()
    finishLocalDescription()
    await expect(opening).rejects.toThrow('cancelled')
    expect(signaling.offers).toEqual([])
    expect(peer.closeCount).toBe(1)
  })

  test('preserves an open observer beyond the negotiation timeout and closes on later cancellation', async () => {
    const controller = new AbortController()
    const fixture = createPeer(controller.signal)
    fixture.peer.channel.open()
    const handle = await fixture.opening
    const session = new MavlinkControlSession({
      actor: 'operator@example.test',
      onControlState: () => {},
      onFlightState: () => {},
      onProtocolError: (message) => { throw new Error(message) },
      requestId: () => 'observer-state',
      setTimeout: (() => 1) as typeof window.setTimeout,
      clearTimeout: (() => undefined) as typeof window.clearTimeout,
    })
    session.attach(handle)
    const state = session.getState()
    session.handleMessage(JSON.stringify({
      type: 'control.state',
      requestId: 'observer-state',
      state: { epoch: 0, leaseTtlMs: 5_000, activeControl: null },
    }))
    await state
    await Bun.sleep(15)
    expect(fixture.peer.closeCount).toBe(0)
    expect(fixture.peer.channel.sent).toHaveLength(1)
    expect(JSON.parse(String(fixture.peer.channel.sent[0])).type).toBe('control.get_state')

    controller.abort()
    expect(fixture.peer.closeCount).toBe(1)
    session.close()
    expect(fixture.peer.closeCount).toBe(1)
  })

  test('frees the peer if signaling throws while opening', async () => {
    const peer = new FakePeerConnection()
    const signaling = new FakeSignalingClient()
    signaling.open = () => { throw new Error('signaling startup failed') }
    await expect(connectMavlinkPeer({
      label: 'txing.mavlink.v1',
      onMessage: () => {},
      onStateChange: () => {},
    }, peer as unknown as RTCPeerConnection, signaling)).rejects.toThrow('signaling startup failed')
    expect(peer.closeCount).toBe(1)
    expect(signaling.closeCount).toBe(1)
  })
})
