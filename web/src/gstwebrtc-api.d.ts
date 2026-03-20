export type GstWebRTCProducer = {
  id: string
  meta: Record<string, unknown>
}

export type GstWebRTCConnectionListener = {
  connected: (clientId: string) => void
  disconnected: () => void
}

export type GstWebRTCProducersListener = {
  producerAdded: (producer: GstWebRTCProducer) => void
  producerRemoved: (producer: GstWebRTCProducer) => void
}

export type GstWebRTCConsumerSession = EventTarget & {
  readonly streams: MediaStream[]
  readonly state: number
  connect: () => boolean
  close: () => void
}

export type GstWebRTCAPIInstance = {
  getAvailableProducers: () => GstWebRTCProducer[]
  registerConnectionListener: (listener: GstWebRTCConnectionListener) => boolean
  unregisterConnectionListener: (listener: GstWebRTCConnectionListener) => boolean
  registerProducersListener: (listener: GstWebRTCProducersListener) => boolean
  unregisterProducersListener: (listener: GstWebRTCProducersListener) => boolean
  createConsumerSession: (producerId: string) => GstWebRTCConsumerSession | null
}

export type GstWebRTCAPIConfig = {
  meta?: Record<string, unknown> | null
  signalingServerUrl?: string
  reconnectionTimeout?: number
  webrtcConfig?: RTCConfiguration
}

export type GstWebRTCAPIConstructor = new (config?: GstWebRTCAPIConfig) => GstWebRTCAPIInstance

declare global {
  interface Window {
    GstWebRTCAPI: GstWebRTCAPIConstructor
  }
}

export {}
