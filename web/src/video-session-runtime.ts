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
import { createCredentialProvider } from './aws-credentials'
import {
  loadKvsWebRtcBrowserSdk,
  type KvsWebRtcSignalingClient,
} from './kvs-webrtc-browser'

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
  debugEnabled?: boolean
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
type InboundVideoStats = RTCInboundRtpStreamStats & {
  mediaType?: string
}

const extractCandidateType = (candidate: string): string | null => {
  const match = / typ ([a-z]+)/.exec(candidate)
  return match?.[1] ?? null
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

export const startBoardVideoViewerRuntime = async (
  options: StartVideoViewerOptions,
): Promise<VideoViewerHandle> => {
  const logVideoDebug = (message: string, details?: unknown): void => {
    if (options.debugEnabled !== true) {
      return
    }
    if (details === undefined) {
      console.info('[device-video]', message)
      return
    }
    console.info('[device-video]', message, details)
  }

  options.onUiEvent({ type: 'connecting' })
  logVideoDebug('viewer start', {
    channelName: options.channelName,
    region: options.region,
  })

  const kvsWebRtcBrowserSdkPromise = loadKvsWebRtcBrowserSdk()

  const idToken = await options.resolveIdToken()
  const credentialProvider = createCredentialProvider(idToken)
  const credentials = await credentialProvider()
  logVideoDebug('viewer credentials resolved')
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
  logVideoDebug('signaling channel described', { channelArn })

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
  logVideoDebug('signaling endpoints resolved', endpoints)

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
  logVideoDebug('ICE server config resolved', {
    clientId,
    iceServerCount: iceConfigResponse.IceServerList?.length ?? 0,
  })

  const peerConnection = new RTCPeerConnection({
    iceServers: buildRtcIceServers(options.region, iceConfigResponse.IceServerList),
  })
  let statsIntervalId: number | null = null
  peerConnection.addTransceiver('video', { direction: 'recvonly' })
  logVideoDebug('peer connection created', {
    iceServers: buildRtcIceServers(options.region, iceConfigResponse.IceServerList).map((server) => server.urls),
  })

  const { Role, SignalingClient } = await kvsWebRtcBrowserSdkPromise
  logVideoDebug('KVS WebRTC browser SDK loaded')

  const signalingClient: KvsWebRtcSignalingClient = new SignalingClient({
    channelARN: channelArn,
    channelEndpoint: endpoints.WSS,
    role: Role.VIEWER,
    region: options.region,
    clientId,
    credentials: toSignalingCredentials(credentials),
  })

  const handlePeerConnectionStateChange = (): void => {
    logVideoDebug('peer connection state', {
      connectionState: peerConnection.connectionState,
      iceConnectionState: peerConnection.iceConnectionState,
      signalingState: peerConnection.signalingState,
    })
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

  const handleIceConnectionStateChange = (): void => {
    logVideoDebug('peer ICE connection state', {
      iceConnectionState: peerConnection.iceConnectionState,
    })
  }

  const handleIceGatheringStateChange = (): void => {
    logVideoDebug('peer ICE gathering state', {
      iceGatheringState: peerConnection.iceGatheringState,
    })
  }

  const handleSignalingStateChange = (): void => {
    logVideoDebug('peer signaling state', {
      signalingState: peerConnection.signalingState,
    })
  }

  const handleTrack = (event: RTCTrackEvent): void => {
    const remoteStream = event.streams[0]
    if (!remoteStream) {
      logVideoDebug('remote track received without stream', {
        trackId: event.track.id,
        kind: event.track.kind,
      })
      return
    }
    logVideoDebug('remote track received', {
      trackId: event.track.id,
      kind: event.track.kind,
      streamId: remoteStream.id,
      muted: event.track.muted,
      readyState: event.track.readyState,
    })
    event.track.addEventListener('mute', () => {
      logVideoDebug('remote track muted', { trackId: event.track.id })
    })
    event.track.addEventListener('unmute', () => {
      logVideoDebug('remote track unmuted', { trackId: event.track.id })
    })
    event.track.addEventListener('ended', () => {
      logVideoDebug('remote track ended', { trackId: event.track.id })
    })
    options.onRemoteStream(remoteStream)
  }

  const handleIceCandidate = ({ candidate }: RTCPeerConnectionIceEvent): void => {
    const candidateSdp = candidate?.candidate.trim() ?? ''
    if (candidate && candidateSdp !== '') {
      logVideoDebug('local ICE candidate', {
        type: extractCandidateType(candidateSdp),
        sdpMid: candidate.sdpMid,
      })
      signalingClient.sendIceCandidate(candidate)
      return
    }
    if (candidate) {
      logVideoDebug('local ICE candidate skipped', {
        reason: 'empty-candidate',
        sdpMid: candidate.sdpMid,
      })
    }
    logVideoDebug('local ICE candidate gathering complete')
  }

  const handleOpen = async (): Promise<void> => {
    logVideoDebug('signaling open')
    const offer = await peerConnection.createOffer()
    await peerConnection.setLocalDescription(offer)
    if (!peerConnection.localDescription) {
      throw new Error('Viewer local description was not created')
    }
    logVideoDebug('local SDP offer created', {
      type: peerConnection.localDescription.type,
      sdpLength: peerConnection.localDescription.sdp?.length ?? 0,
    })
    signalingClient.sendSdpOffer(peerConnection.localDescription)
  }

  const handleSdpAnswer = async (answer: RTCSessionDescriptionInit): Promise<void> => {
    logVideoDebug('remote SDP answer received', {
      type: answer.type,
      sdpLength: answer.sdp?.length ?? 0,
    })
    await peerConnection.setRemoteDescription(answer)
  }

  const handleRemoteIceCandidate = async (candidate: RTCIceCandidateInit): Promise<void> => {
    logVideoDebug('remote ICE candidate received', {
      type: candidate.candidate ? extractCandidateType(candidate.candidate) : null,
      sdpMid: candidate.sdpMid,
    })
    await peerConnection.addIceCandidate(candidate)
  }

  const handleError = (error: unknown): void => {
    logVideoDebug('viewer error', error)
    options.onUiEvent({
      type: 'error',
      message: getErrorMessage(error),
    })
  }

  peerConnection.addEventListener('connectionstatechange', handlePeerConnectionStateChange)
  peerConnection.addEventListener('iceconnectionstatechange', handleIceConnectionStateChange)
  peerConnection.addEventListener('icegatheringstatechange', handleIceGatheringStateChange)
  peerConnection.addEventListener('signalingstatechange', handleSignalingStateChange)
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
    logVideoDebug('signaling close')
    options.onUiEvent({
      type: 'error',
      message: 'Board video signaling closed',
    })
  })
  signalingClient.open()

  statsIntervalId = window.setInterval(() => {
    void peerConnection.getStats().then((stats) => {
      for (const report of stats.values()) {
        const inbound = report as InboundVideoStats
        const isInboundVideo =
          report.type === 'inbound-rtp' &&
          (inbound.kind === 'video' || inbound.mediaType === 'video')
        if (!isInboundVideo) {
          continue
        }

        logVideoDebug('inbound video stats', {
          bytesReceived: inbound.bytesReceived,
          framesDecoded: inbound.framesDecoded,
          keyFramesDecoded: inbound.keyFramesDecoded,
          framesPerSecond: inbound.framesPerSecond,
          frameWidth: inbound.frameWidth,
          frameHeight: inbound.frameHeight,
          packetsLost: inbound.packetsLost,
          pliCount: inbound.pliCount,
          firCount: inbound.firCount,
          decoderImplementation: inbound.decoderImplementation,
        })
      }
    }).catch((error) => {
      logVideoDebug('getStats failed', error)
    })
  }, 5000)

  return {
    close: () => {
      if (statsIntervalId !== null) {
        window.clearInterval(statsIntervalId)
        statsIntervalId = null
      }
      signalingClient.removeAllListeners()
      signalingClient.close()
      peerConnection.removeEventListener('connectionstatechange', handlePeerConnectionStateChange)
      peerConnection.removeEventListener('iceconnectionstatechange', handleIceConnectionStateChange)
      peerConnection.removeEventListener('icegatheringstatechange', handleIceGatheringStateChange)
      peerConnection.removeEventListener('signalingstatechange', handleSignalingStateChange)
      peerConnection.removeEventListener('track', handleTrack)
      peerConnection.removeEventListener('icecandidate', handleIceCandidate)
      peerConnection.getReceivers().forEach((receiver) => {
        receiver.track?.stop()
      })
      peerConnection.close()
      logVideoDebug('viewer closed')
      options.onUiEvent({ type: 'reset' })
    },
  }
}
