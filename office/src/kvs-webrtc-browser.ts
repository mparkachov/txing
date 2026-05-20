const kvsWebRtcBrowserSdkUrl =
  'https://unpkg.com/amazon-kinesis-video-streams-webrtc@2.6.1/dist/kvs-webrtc.min.js'

const kvsWebRtcBrowserSdkScriptId = 'device-kvs-webrtc-browser-sdk'

type KvsWebRtcRole = {
  VIEWER: string
}

type KvsWebRtcCredentials = {
  accessKeyId: string
  secretAccessKey: string
  sessionToken?: string
}

type SignalingClientConfig = {
  channelARN: string
  channelEndpoint: string
  role: string
  region: string
  clientId: string
  credentials: KvsWebRtcCredentials
}

type SignalingClientEventMap = {
  open: []
  sdpAnswer: [RTCSessionDescriptionInit]
  iceCandidate: [RTCIceCandidateInit]
  error: [unknown]
  close: []
}

export type KvsWebRtcSignalingClient = {
  close: () => void
  open: () => void
  on: <TEventName extends keyof SignalingClientEventMap>(
    eventName: TEventName,
    listener: (...args: SignalingClientEventMap[TEventName]) => void,
  ) => void
  removeAllListeners: () => void
  sendIceCandidate: (candidate: RTCIceCandidate | RTCIceCandidateInit) => void
  sendSdpOffer: (description: RTCSessionDescriptionInit) => void
}

type KvsWebRtcBrowserSdk = {
  Role: KvsWebRtcRole
  SignalingClient: new (config: SignalingClientConfig) => KvsWebRtcSignalingClient
}

declare global {
  interface Window {
    KVSWebRTC?: KvsWebRtcBrowserSdk
  }
}

let browserSdkPromise: Promise<KvsWebRtcBrowserSdk> | null = null

const getGlobalBrowserSdk = (): KvsWebRtcBrowserSdk | null => {
  const sdk = window.KVSWebRTC
  if (!sdk?.Role?.VIEWER || !sdk.SignalingClient) {
    return null
  }
  return sdk
}

const createMissingSdkError = (): Error =>
  new Error('KVS WebRTC browser SDK did not expose window.KVSWebRTC as expected')

const resolveBrowserSdk = (): KvsWebRtcBrowserSdk => {
  const sdk = getGlobalBrowserSdk()
  if (!sdk) {
    throw createMissingSdkError()
  }
  return sdk
}

export const loadKvsWebRtcBrowserSdk = async (): Promise<KvsWebRtcBrowserSdk> => {
  const existingSdk = getGlobalBrowserSdk()
  if (existingSdk) {
    return existingSdk
  }

  if (!browserSdkPromise) {
    browserSdkPromise = new Promise<KvsWebRtcBrowserSdk>((resolve, reject) => {
      let scriptElement = document.getElementById(
        kvsWebRtcBrowserSdkScriptId,
      ) as HTMLScriptElement | null

      const handleLoad = (): void => {
        try {
          resolve(resolveBrowserSdk())
        } catch (error) {
          browserSdkPromise = null
          reject(error)
        }
      }

      const handleError = (): void => {
        scriptElement?.remove()
        browserSdkPromise = null
        reject(
          new Error(
            `Unable to load KVS WebRTC browser SDK from ${kvsWebRtcBrowserSdkUrl}`,
          ),
        )
      }

      if (!scriptElement) {
        scriptElement = document.createElement('script')
        scriptElement.id = kvsWebRtcBrowserSdkScriptId
        scriptElement.src = kvsWebRtcBrowserSdkUrl
        scriptElement.async = true
        scriptElement.crossOrigin = 'anonymous'
      }

      scriptElement.addEventListener('load', handleLoad, { once: true })
      scriptElement.addEventListener('error', handleError, { once: true })

      if (getGlobalBrowserSdk()) {
        handleLoad()
        return
      }

      if (!scriptElement.isConnected) {
        document.head.append(scriptElement)
      }
    })
  }

  return browserSdkPromise
}
