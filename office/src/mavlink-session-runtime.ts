import {
  GetIceServerConfigCommand,
  KinesisVideoSignalingClient,
} from '@aws-sdk/client-kinesis-video-signaling'
import { KinesisVideoClient } from '@aws-sdk/client-kinesis-video'
import { createCredentialProvider } from './aws-credentials'
import {
  buildKinesisVideoClientConfig,
  buildKinesisVideoSignalingClientConfig,
  buildRtcIceServers,
  resolveKvsSignalingMetadata,
} from './video-session-runtime'
import { loadKvsWebRtcBrowserSdk, type KvsWebRtcSignalingClient } from './kvs-webrtc-browser'

export type StartMavlinkDataChannelOptions = {
  channelName: string
  label: string
  onMessage: (message: string | Uint8Array) => void
  onStateChange: (state: 'connecting' | 'open' | 'closed' | 'error', message?: string) => void
  region: string
  resolveIdToken: () => Promise<string>
  signal?: AbortSignal
}

export type MavlinkDataChannelRuntimeHandle = {
  close: () => void
  sendBinary: (frame: Uint8Array) => void
  sendText: (message: string) => void
}

const getErrorMessage = (error: unknown, fallback: string): string =>
  error instanceof Error && error.message ? error.message : fallback

const toSignalingCredentials = (
  credentials: Awaited<ReturnType<ReturnType<typeof createCredentialProvider>>>,
): {
  accessKeyId: string
  secretAccessKey: string
  sessionToken?: string
} => ({
  accessKeyId: credentials.accessKeyId,
  secretAccessKey: credentials.secretAccessKey,
  sessionToken: credentials.sessionToken,
})

const toMessageBytes = (data: unknown): Uint8Array | null => {
  if (data instanceof ArrayBuffer) {
    return new Uint8Array(data)
  }
  if (ArrayBuffer.isView(data)) {
    return new Uint8Array(data.buffer, data.byteOffset, data.byteLength)
  }
  return null
}

// This KVS peer intentionally creates no media transceiver and never attaches
// a MediaStream. It is independent from the board-video peer by channel name,
// credentials, signaling client, RTCPeerConnection, and teardown lifecycle.
export const startMavlinkDataChannelRuntime = async (
  options: StartMavlinkDataChannelOptions,
): Promise<MavlinkDataChannelRuntimeHandle> => {
  options.signal?.throwIfAborted()
  options.onStateChange('connecting')
  const sdkPromise = loadKvsWebRtcBrowserSdk()
  void sdkPromise.catch(() => undefined)
  const idToken = await options.resolveIdToken()
  options.signal?.throwIfAborted()
  const credentialProvider = createCredentialProvider(idToken)
  const credentials = await credentialProvider()
  options.signal?.throwIfAborted()
  const kinesisVideoClient = new KinesisVideoClient(buildKinesisVideoClientConfig({
    region: options.region,
    credentials: credentialProvider,
  }))
  const { channelArn, endpoints } = await resolveKvsSignalingMetadata({
    channelName: options.channelName,
    region: options.region,
    kinesisVideoClient,
  })
  options.signal?.throwIfAborted()
  const signalingApiClient = new KinesisVideoSignalingClient(buildKinesisVideoSignalingClientConfig({
    region: options.region,
    endpoint: endpoints.HTTPS,
    credentials: credentialProvider,
  }))
  const clientId = crypto.randomUUID()
  const iceConfig = await signalingApiClient.send(new GetIceServerConfigCommand({
    ChannelARN: channelArn,
    ClientId: clientId,
  }), { abortSignal: options.signal })
  const { Role, SignalingClient } = await sdkPromise
  options.signal?.throwIfAborted()
  const signalingClient = new SignalingClient({
    channelARN: channelArn,
    channelEndpoint: endpoints.WSS,
    role: Role.VIEWER,
    region: options.region,
    clientId,
    credentials: toSignalingCredentials(credentials),
  })
  const peerConnection = new RTCPeerConnection({
    iceServers: buildRtcIceServers(options.region, iceConfig.IceServerList),
  })
  return connectMavlinkPeer(options, peerConnection, signalingClient)
}

export const connectMavlinkPeer = async (
  options: Pick<StartMavlinkDataChannelOptions, 'label' | 'onMessage' | 'onStateChange' | 'signal'>,
  peerConnection: RTCPeerConnection,
  signalingClient: KvsWebRtcSignalingClient,
  openTimeoutMs = 20_000,
): Promise<MavlinkDataChannelRuntimeHandle> => {
  const dataChannel = peerConnection.createDataChannel(options.label, {
    ordered: true,
  })
  dataChannel.binaryType = 'arraybuffer'
  let closed = false
  let openTimerId: ReturnType<typeof setTimeout> | undefined
  let openSettled = false
  let resolveOpen: () => void = () => undefined
  let rejectOpen: (error: Error) => void = () => undefined
  const openPromise = new Promise<void>((resolve, reject) => {
    resolveOpen = resolve
    rejectOpen = reject
  })
  void openPromise.catch(() => undefined)

  const close = (state: 'closed' | 'error', message?: string): void => {
    if (closed) {
      return
    }
    closed = true
    clearTimeout(openTimerId)
    options.signal?.removeEventListener('abort', abort)
    signalingClient.removeAllListeners()
    signalingClient.close()
    dataChannel.close()
    peerConnection.close()
    options.onStateChange(state, message)
    if (!openSettled) {
      openSettled = true
      rejectOpen(new Error(message ?? 'MAVLink data channel closed before opening'))
    }
  }
  const abort = (): void => close('closed', 'MAVLink connection cancelled')

  dataChannel.addEventListener('open', () => {
    if (!closed) {
      options.onStateChange('open')
      if (!openSettled) {
        openSettled = true
        clearTimeout(openTimerId)
        resolveOpen()
      }
    }
  })
  dataChannel.addEventListener('message', (event) => {
    if (closed) {
      return
    }
    if (typeof event.data === 'string') {
      options.onMessage(event.data)
      return
    }
    const bytes = toMessageBytes(event.data)
    if (bytes) {
      options.onMessage(bytes)
    }
  })
  dataChannel.addEventListener('close', () => {
    close('closed')
  })
  dataChannel.addEventListener('error', () => {
    close('error', 'MAVLink data channel error')
  })
  peerConnection.addEventListener('icecandidate', ({ candidate }) => {
    if (!closed && candidate) {
      signalingClient.sendIceCandidate(candidate)
    }
  })
  peerConnection.addEventListener('connectionstatechange', () => {
    if (
      peerConnection.connectionState === 'failed' ||
      peerConnection.connectionState === 'disconnected' ||
      peerConnection.connectionState === 'closed'
    ) {
      close('error', `MAVLink peer connection ${peerConnection.connectionState}`)
    }
  })

  signalingClient.on('open', () => {
    void (async () => {
      const offer = await peerConnection.createOffer()
      if (closed) {
        return
      }
      await peerConnection.setLocalDescription(offer)
      if (closed) {
        return
      }
      if (!peerConnection.localDescription) {
        throw new Error('MAVLink local description was not created')
      }
      signalingClient?.sendSdpOffer(peerConnection.localDescription)
    })().catch((error) => {
      close('error', getErrorMessage(error, 'Unable to create MAVLink KVS offer'))
    })
  })
  signalingClient.on('sdpAnswer', (answer: RTCSessionDescriptionInit) => {
    if (closed) {
      return
    }
    void peerConnection.setRemoteDescription(answer).catch((error) => {
      close('error', getErrorMessage(error, 'Unable to apply MAVLink KVS answer'))
    })
  })
  signalingClient.on('iceCandidate', (candidate: RTCIceCandidateInit) => {
    if (closed) {
      return
    }
    void peerConnection.addIceCandidate(candidate).catch(() => undefined)
  })
  signalingClient.on('error', (error) => {
    close('error', getErrorMessage(error, 'MAVLink KVS signaling failed'))
  })
  signalingClient.on('close', () => {
    if (dataChannel.readyState !== 'open') {
      close('closed', 'MAVLink KVS signaling closed')
    }
  })
  options.signal?.addEventListener('abort', abort, { once: true })
  if (options.signal?.aborted) {
    abort()
  } else {
    openTimerId = setTimeout(() => {
      close('error', 'MAVLink data channel opening timed out')
    }, openTimeoutMs)
    try {
      signalingClient.open()
    } catch (error) {
      close('error', getErrorMessage(error, 'Unable to open MAVLink KVS signaling'))
    }
  }

  await openPromise

  return {
    sendText: (message) => {
      if (closed || dataChannel.readyState !== 'open') {
        throw new Error('MAVLink data channel is not open')
      }
      dataChannel.send(message)
    },
    sendBinary: (frame) => {
      if (closed || dataChannel.readyState !== 'open') {
        throw new Error('MAVLink data channel is not open')
      }
      const copy = new Uint8Array(frame)
      dataChannel.send(copy.buffer as ArrayBuffer)
    },
    close: () => close('closed'),
  }
}
