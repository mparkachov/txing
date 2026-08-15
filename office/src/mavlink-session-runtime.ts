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
  options.onStateChange('connecting')
  const sdkPromise = loadKvsWebRtcBrowserSdk()
  const idToken = await options.resolveIdToken()
  const credentialProvider = createCredentialProvider(idToken)
  const credentials = await credentialProvider()
  const kinesisVideoClient = new KinesisVideoClient(buildKinesisVideoClientConfig({
    region: options.region,
    credentials: credentialProvider,
  }))
  const { channelArn, endpoints } = await resolveKvsSignalingMetadata({
    channelName: options.channelName,
    region: options.region,
    kinesisVideoClient,
  })
  const signalingApiClient = new KinesisVideoSignalingClient(buildKinesisVideoSignalingClientConfig({
    region: options.region,
    endpoint: endpoints.HTTPS,
    credentials: credentialProvider,
  }))
  const clientId = crypto.randomUUID()
  const iceConfig = await signalingApiClient.send(new GetIceServerConfigCommand({
    ChannelARN: channelArn,
    ClientId: clientId,
  }))
  const peerConnection = new RTCPeerConnection({
    iceServers: buildRtcIceServers(options.region, iceConfig.IceServerList),
  })
  const dataChannel = peerConnection.createDataChannel(options.label, {
    ordered: true,
  })
  dataChannel.binaryType = 'arraybuffer'
  let closed = false
  let signalingClient: KvsWebRtcSignalingClient | null = null
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
    signalingClient?.removeAllListeners()
    signalingClient?.close()
    dataChannel.close()
    peerConnection.close()
    options.onStateChange(state, message)
    if (!openSettled) {
      openSettled = true
      rejectOpen(new Error(message ?? 'MAVLink data channel closed before opening'))
    }
  }

  dataChannel.addEventListener('open', () => {
    if (!closed) {
      options.onStateChange('open')
      if (!openSettled) {
        openSettled = true
        resolveOpen()
      }
    }
  })
  dataChannel.addEventListener('message', (event) => {
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
    if (candidate && signalingClient) {
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

  const { Role, SignalingClient } = await sdkPromise
  signalingClient = new SignalingClient({
    channelARN: channelArn,
    channelEndpoint: endpoints.WSS,
    role: Role.VIEWER,
    region: options.region,
    clientId,
    credentials: toSignalingCredentials(credentials),
  })
  signalingClient.on('open', () => {
    void (async () => {
      const offer = await peerConnection.createOffer()
      await peerConnection.setLocalDescription(offer)
      if (!peerConnection.localDescription) {
        throw new Error('MAVLink local description was not created')
      }
      signalingClient?.sendSdpOffer(peerConnection.localDescription)
    })().catch((error) => {
      close('error', getErrorMessage(error, 'Unable to create MAVLink KVS offer'))
    })
  })
  signalingClient.on('sdpAnswer', (answer: RTCSessionDescriptionInit) => {
    void peerConnection.setRemoteDescription(answer).catch((error) => {
      close('error', getErrorMessage(error, 'Unable to apply MAVLink KVS answer'))
    })
  })
  signalingClient.on('iceCandidate', (candidate: RTCIceCandidateInit) => {
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
  signalingClient.open()

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
