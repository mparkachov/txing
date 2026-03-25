import {
  ChannelProtocol,
  DescribeSignalingChannelCommand,
  GetSignalingChannelEndpointCommand,
  KinesisVideoClient,
  type ResourceEndpointListItem,
} from '@aws-sdk/client-kinesis-video'
import {
  GetIceServerConfigCommand,
  KinesisVideoSignalingClient,
  type IceServer,
} from '@aws-sdk/client-kinesis-video-signaling'
import {
  Role,
  SignalingClient,
} from 'amazon-kinesis-video-streams-webrtc'
import { createCredentialProvider } from './aws-credentials'

export type ViewerUiState = {
  status: 'idle' | 'connecting' | 'streaming' | 'error'
  error: string
}

export type ViewerUiEvent =
  | { type: 'reset' }
  | { type: 'connecting' }
  | { type: 'streaming' }
  | { type: 'error'; message: string }

export type StartVideoViewerOptions = {
  channelName: string
  region: string
  resolveIdToken: () => Promise<string>
  onRemoteStream: (stream: MediaStream) => void
  onUiEvent: (event: ViewerUiEvent) => void
}

export type VideoViewerHandle = {
  close: () => void
}

type EndpointMap = Partial<Record<'HTTPS' | 'WSS', string>>
type SignalingCredentials = {
  accessKeyId: string
  secretAccessKey: string
  sessionToken?: string
}

export const reduceViewerUiState = (
  _state: ViewerUiState,
  event: ViewerUiEvent,
): ViewerUiState => {
  switch (event.type) {
    case 'reset':
      return { status: 'idle', error: '' }
    case 'connecting':
      return { status: 'connecting', error: '' }
    case 'streaming':
      return { status: 'streaming', error: '' }
    case 'error':
      return { status: 'error', error: event.message }
  }
}

export const mapSignalingEndpoints = (
  endpoints: ResourceEndpointListItem[] | undefined,
): EndpointMap =>
  (endpoints ?? []).reduce<EndpointMap>((result, item) => {
    if (item.Protocol === ChannelProtocol.HTTPS && item.ResourceEndpoint) {
      result.HTTPS = item.ResourceEndpoint
    }
    if (item.Protocol === ChannelProtocol.WSS && item.ResourceEndpoint) {
      result.WSS = item.ResourceEndpoint
    }
    return result
  }, {})

export const buildRtcIceServers = (region: string, iceServers: IceServer[] | undefined): RTCIceServer[] => {
  const rtcIceServers: RTCIceServer[] = [
    {
      urls: `stun:stun.kinesisvideo.${region}.amazonaws.com:443`,
    },
  ]

  for (const server of iceServers ?? []) {
    if (!server.Uris || server.Uris.length === 0) {
      continue
    }
    rtcIceServers.push({
      urls: server.Uris,
      username: server.Username,
      credential: server.Password,
    })
  }

  return rtcIceServers
}

const toSignalingCredentials = (credentials: Awaited<ReturnType<ReturnType<typeof createCredentialProvider>>>): SignalingCredentials => ({
  accessKeyId: credentials.accessKeyId,
  secretAccessKey: credentials.secretAccessKey,
  sessionToken: credentials.sessionToken,
})

const getErrorMessage = (error: unknown, fallback = 'Board video viewer failed'): string => {
  if (error instanceof Error) {
    if (error.message) {
      return error.message
    }
  }
  return fallback
}

export const startBoardVideoViewer = async (
  options: StartVideoViewerOptions,
): Promise<VideoViewerHandle> => {
  options.onUiEvent({ type: 'connecting' })

  const idToken = await options.resolveIdToken()
  const credentialProvider = createCredentialProvider(idToken)
  const credentials = await credentialProvider()
  const kinesisVideoClient = new KinesisVideoClient({
    region: options.region,
    credentials: credentialProvider,
  })
  const describeResponse = await kinesisVideoClient.send(
    new DescribeSignalingChannelCommand({
      ChannelName: options.channelName,
    }),
  )
  const channelArn = describeResponse.ChannelInfo?.ChannelARN
  if (!channelArn) {
    throw new Error(`KVS signaling channel ${options.channelName} was not found`)
  }

  const endpointResponse = await kinesisVideoClient.send(
    new GetSignalingChannelEndpointCommand({
      ChannelARN: channelArn,
      SingleMasterChannelEndpointConfiguration: {
        Protocols: [ChannelProtocol.WSS, ChannelProtocol.HTTPS],
        Role: 'VIEWER',
      },
    }),
  )
  const endpoints = mapSignalingEndpoints(endpointResponse.ResourceEndpointList)
  if (!endpoints.HTTPS || !endpoints.WSS) {
    throw new Error(`KVS signaling channel ${options.channelName} did not return HTTPS and WSS endpoints`)
  }

  const signalingApiClient = new KinesisVideoSignalingClient({
    region: options.region,
    endpoint: endpoints.HTTPS,
    credentials: credentialProvider,
  })
  const clientId = crypto.randomUUID()
  const iceConfigResponse = await signalingApiClient.send(
    new GetIceServerConfigCommand({
      ChannelARN: channelArn,
      ClientId: clientId,
    }),
  )

  const peerConnection = new RTCPeerConnection({
    iceServers: buildRtcIceServers(options.region, iceConfigResponse.IceServerList),
  })
  peerConnection.addTransceiver('video', { direction: 'recvonly' })

  const signalingClient = new SignalingClient({
    channelARN: channelArn,
    channelEndpoint: endpoints.WSS,
    role: Role.VIEWER,
    region: options.region,
    clientId,
    credentials: toSignalingCredentials(credentials),
  })

  const handlePeerConnectionStateChange = (): void => {
    if (
      peerConnection.connectionState === 'failed' ||
      peerConnection.connectionState === 'disconnected' ||
      peerConnection.connectionState === 'closed'
    ) {
      options.onUiEvent({
        type: 'error',
        message: `Board video connection ${peerConnection.connectionState}`,
      })
    }
  }

  const handleTrack = (event: RTCTrackEvent): void => {
    const remoteStream = event.streams[0]
    if (!remoteStream) {
      return
    }
    options.onRemoteStream(remoteStream)
    options.onUiEvent({ type: 'streaming' })
  }

  const handleIceCandidate = ({ candidate }: RTCPeerConnectionIceEvent): void => {
    if (candidate) {
      signalingClient.sendIceCandidate(candidate)
    }
  }

  const handleOpen = async (): Promise<void> => {
    const offer = await peerConnection.createOffer()
    await peerConnection.setLocalDescription(offer)
    if (!peerConnection.localDescription) {
      throw new Error('Viewer local description was not created')
    }
    signalingClient.sendSdpOffer(peerConnection.localDescription)
  }

  const handleSdpAnswer = async (answer: RTCSessionDescriptionInit): Promise<void> => {
    await peerConnection.setRemoteDescription(answer)
  }

  const handleRemoteIceCandidate = async (candidate: RTCIceCandidateInit): Promise<void> => {
    await peerConnection.addIceCandidate(candidate)
  }

  const handleError = (error: unknown): void => {
    options.onUiEvent({
      type: 'error',
      message: getErrorMessage(error),
    })
  }

  peerConnection.addEventListener('connectionstatechange', handlePeerConnectionStateChange)
  peerConnection.addEventListener('track', handleTrack)
  peerConnection.addEventListener('icecandidate', handleIceCandidate)
  signalingClient.on('open', () => {
    void handleOpen().catch(handleError)
  })
  signalingClient.on('sdpAnswer', (answer: RTCSessionDescriptionInit) => {
    void handleSdpAnswer(answer).catch(handleError)
  })
  signalingClient.on('iceCandidate', (candidate: RTCIceCandidateInit) => {
    void handleRemoteIceCandidate(candidate).catch(handleError)
  })
  signalingClient.on('error', handleError)
  signalingClient.on('close', () => {
    options.onUiEvent({
      type: 'error',
      message: 'Board video signaling closed',
    })
  })
  signalingClient.open()

  return {
    close: () => {
      signalingClient.removeAllListeners()
      signalingClient.close()
      peerConnection.removeEventListener('connectionstatechange', handlePeerConnectionStateChange)
      peerConnection.removeEventListener('track', handleTrack)
      peerConnection.removeEventListener('icecandidate', handleIceCandidate)
      peerConnection.getReceivers().forEach((receiver) => {
        receiver.track?.stop()
      })
      peerConnection.close()
      options.onUiEvent({ type: 'reset' })
    },
  }
}
