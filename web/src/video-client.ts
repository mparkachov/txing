import '@tomoxv/gstwebrtc-api/src/index.js'
import type {
  GstWebRTCAPIInstance,
  GstWebRTCConnectionListener,
  GstWebRTCConsumerSession,
  GstWebRTCProducer,
  GstWebRTCProducersListener,
} from './gstwebrtc-api'

const STREAMING_STATE = 2

export type BoardVideoStatus =
  | 'idle'
  | 'connecting'
  | 'waiting'
  | 'streaming'
  | 'closed'
  | 'error'

type BoardVideoClientOptions = {
  signallingUrl: string
  streamName: string
  onStateChange?: (status: BoardVideoStatus, message: string) => void
}

export class BoardVideoClient {
  private readonly api: GstWebRTCAPIInstance
  private readonly signallingUrl: string
  private readonly streamName: string
  private readonly onStateChange?: (status: BoardVideoStatus, message: string) => void
  private readonly streamNameLower: string
  private readonly connectionListener: GstWebRTCConnectionListener
  private readonly producersListener: GstWebRTCProducersListener
  private consumerSession: GstWebRTCConsumerSession | null = null
  private streamResolve: ((stream: MediaStream) => void) | null = null
  private streamReject: ((reason?: unknown) => void) | null = null
  private producerTimeoutId: number | null = null
  private closed = false

  constructor({ signallingUrl, streamName, onStateChange }: BoardVideoClientOptions) {
    this.signallingUrl = signallingUrl
    this.streamName = streamName
    this.streamNameLower = streamName.trim().toLowerCase()
    this.onStateChange = onStateChange
    this.api = new window.GstWebRTCAPI({
      meta: {
        name: `txing-web-${Date.now()}`,
      },
      signalingServerUrl: signallingUrl,
      reconnectionTimeout: 0,
      webrtcConfig: {
        iceServers: [],
      },
    })

    this.connectionListener = {
      connected: () => {
        this.emitState('waiting', `Connected to ${this.signallingUrl}`)
        this.tryConnectToProducer(this.api.getAvailableProducers())
      },
      disconnected: () => {
        if (this.closed) {
          return
        }
        this.emitState('closed', 'Disconnected from board video signaling')
        this.rejectPending(new Error('Disconnected from signaling server'))
      },
    }

    this.producersListener = {
      producerAdded: (producer: GstWebRTCProducer) => {
        this.tryConnectToProducer([producer])
      },
      producerRemoved: (producer: GstWebRTCProducer) => {
        const producerName = this.getProducerName(producer)
        if (producerName !== this.streamNameLower || this.closed) {
          return
        }
        if (this.consumerSession) {
          this.consumerSession.close()
          this.consumerSession = null
        }
        this.emitState('closed', `Board stream ${this.streamName} went away`)
      },
    }

    this.api.registerConnectionListener(this.connectionListener)
    this.api.registerProducersListener(this.producersListener)
  }

  connect(): Promise<MediaStream> {
    if (this.closed) {
      return Promise.reject(new Error('Board video client is already closed'))
    }

    this.emitState('connecting', `Connecting to ${this.signallingUrl}`)
    return new Promise<MediaStream>((resolve, reject) => {
      this.streamResolve = resolve
      this.streamReject = reject
      this.producerTimeoutId = window.setTimeout(() => {
        this.producerTimeoutId = null
        this.rejectPending(
          new Error(`Timed out waiting for stream ${this.streamName} on ${this.signallingUrl}`),
        )
        this.emitState('error', `Timed out waiting for stream ${this.streamName}`)
      }, 15000)
    })
  }

  disconnect(): void {
    if (this.closed) {
      return
    }
    this.closed = true
    this.clearProducerTimeout()
    this.rejectPending(new Error('Board video client closed'))
    if (this.consumerSession) {
      this.consumerSession.close()
      this.consumerSession = null
    }
    this.api.unregisterConnectionListener(this.connectionListener)
    this.api.unregisterProducersListener(this.producersListener)
    const apiWithChannel = this.api as GstWebRTCAPIInstance & {
      _channel?: {
        close: () => void
      }
    }
    apiWithChannel._channel?.close()
    this.emitState('closed', 'Board video disconnected')
  }

  private tryConnectToProducer(producers: GstWebRTCProducer[]): void {
    if (this.closed || this.consumerSession) {
      return
    }

    const matchingProducer = producers.find(
      (producer) => this.getProducerName(producer) === this.streamNameLower,
    )
    if (!matchingProducer) {
      return
    }

    const consumerSession = this.api.createConsumerSession(matchingProducer.id)
    if (!consumerSession) {
      this.emitState('error', `Unable to open consumer session for ${this.streamName}`)
      this.rejectPending(new Error(`Unable to open consumer session for ${this.streamName}`))
      return
    }

    this.consumerSession = consumerSession
    consumerSession.addEventListener('streamsChanged', () => {
      const mediaStream = consumerSession.streams[0]
      if (mediaStream) {
        this.clearProducerTimeout()
        this.emitState('streaming', `Streaming ${this.streamName}`)
        if (this.streamResolve) {
          this.streamResolve(mediaStream)
          this.streamResolve = null
          this.streamReject = null
        }
      }
    })
    consumerSession.addEventListener('stateChanged', () => {
      if (consumerSession.state === STREAMING_STATE) {
        this.emitState('streaming', `Streaming ${this.streamName}`)
        return
      }
      this.emitState('connecting', `Negotiating ${this.streamName}`)
    })
    consumerSession.addEventListener('error', (event: Event) => {
      const errorEvent = event as ErrorEvent
      const message = errorEvent.message || `Board stream ${this.streamName} failed`
      this.emitState('error', message)
      this.rejectPending(errorEvent.error ?? new Error(message))
    })
    consumerSession.addEventListener('closed', () => {
      if (this.closed) {
        return
      }
      this.consumerSession = null
      this.emitState('closed', `Board stream ${this.streamName} closed`)
    })

    if (!consumerSession.connect()) {
      this.emitState('error', `Unable to start stream ${this.streamName}`)
      this.rejectPending(new Error(`Unable to start stream ${this.streamName}`))
    }
  }

  private getProducerName(producer: GstWebRTCProducer): string {
    const name = producer.meta.name
    return typeof name === 'string' ? name.trim().toLowerCase() : ''
  }

  private emitState(status: BoardVideoStatus, message: string): void {
    this.onStateChange?.(status, message)
  }

  private clearProducerTimeout(): void {
    if (this.producerTimeoutId !== null) {
      window.clearTimeout(this.producerTimeoutId)
      this.producerTimeoutId = null
    }
  }

  private rejectPending(error: unknown): void {
    if (!this.streamReject) {
      return
    }
    this.streamReject(error)
    this.streamResolve = null
    this.streamReject = null
    this.clearProducerTimeout()
  }
}
