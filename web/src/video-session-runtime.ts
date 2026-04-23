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
  isDebugEnabled?: () => boolean
}

export type VideoViewerHandle = {
  close: () => void
}

export type StartMcpDataChannelOptions = {
  channelName: string
  region: string
  label: string
  resolveIdToken: () => Promise<string>
  openTimeoutMs?: number
  debugEnabled?: boolean
  isDebugEnabled?: () => boolean
}

export type McpDataChannelHandle = {
  sessionId: string
  request: (message: Record<string, unknown>, timeoutMs: number) => Promise<unknown>
  notify: (message: Record<string, unknown>) => Promise<void>
  close: () => void
}

export type EndpointMap = Partial<Record<'HTTPS' | 'WSS', string>>
export type ResolvedEndpointMap = Record<'HTTPS' | 'WSS', string>
type SignalingCredentials = {
  accessKeyId: string
  secretAccessKey: string
  sessionToken?: string
}
type InboundVideoStats = RTCInboundRtpStreamStats & {
  mediaType?: string
}
export type KvsSignalingMetadata = {
  channelArn: string
  endpoints: ResolvedEndpointMap
}
type KvsSignalingMetadataCacheEntry = {
  metadata: KvsSignalingMetadata
  expiresAtMs: number
}
type KvsSignalingMetadataFailureEntry = {
  error: Error
  retryAtMs: number
}

const kvsSignalingMetadataCacheTtlMs = 5 * 60_000
const kvsSignalingMetadataFailureCooldownMs = 60_000
const kvsSignalingMetadataCache = new Map<string, KvsSignalingMetadataCacheEntry>()
const kvsSignalingMetadataFailures = new Map<string, KvsSignalingMetadataFailureEntry>()
const pendingKvsSignalingMetadataLoads = new Map<string, Promise<KvsSignalingMetadata>>()

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

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value)

const getKvsSignalingMetadataCacheKey = (region: string, channelName: string): string =>
  `${region}\u0000${channelName}`

const toError = (error: unknown, fallback: string): Error =>
  error instanceof Error ? error : new Error(fallback)

export const clearKvsSignalingMetadataCacheForTests = (): void => {
  kvsSignalingMetadataCache.clear()
  kvsSignalingMetadataFailures.clear()
  pendingKvsSignalingMetadataLoads.clear()
}

export const resolveCachedKvsSignalingMetadata = async ({
  channelName,
  region,
  loadMetadata,
  nowMs = () => Date.now(),
}: {
  channelName: string
  region: string
  loadMetadata: () => Promise<KvsSignalingMetadata>
  nowMs?: () => number
}): Promise<KvsSignalingMetadata> => {
  const cacheKey = getKvsSignalingMetadataCacheKey(region, channelName)
  const now = nowMs()
  const cachedMetadata = kvsSignalingMetadataCache.get(cacheKey)
  if (cachedMetadata && cachedMetadata.expiresAtMs > now) {
    return cachedMetadata.metadata
  }

  const cachedFailure = kvsSignalingMetadataFailures.get(cacheKey)
  if (cachedFailure && cachedFailure.retryAtMs > now) {
    throw cachedFailure.error
  }

  const pendingLoad = pendingKvsSignalingMetadataLoads.get(cacheKey)
  if (pendingLoad) {
    return pendingLoad
  }

  const loadPromise = Promise.resolve()
    .then(loadMetadata)
    .then((metadata) => {
      kvsSignalingMetadataCache.set(cacheKey, {
        metadata,
        expiresAtMs: nowMs() + kvsSignalingMetadataCacheTtlMs,
      })
      kvsSignalingMetadataFailures.delete(cacheKey)
      return metadata
    })
    .catch((caughtError: unknown) => {
      const error = toError(
        caughtError,
        `Unable to resolve KVS signaling channel ${channelName}`,
      )
      kvsSignalingMetadataFailures.set(cacheKey, {
        error,
        retryAtMs: nowMs() + kvsSignalingMetadataFailureCooldownMs,
      })
      throw error
    })
    .finally(() => {
      pendingKvsSignalingMetadataLoads.delete(cacheKey)
    })

  pendingKvsSignalingMetadataLoads.set(cacheKey, loadPromise)
  return loadPromise
}

const resolveKvsSignalingMetadata = async ({
  channelName,
  region,
  kinesisVideoClient,
}: {
  channelName: string
  region: string
  kinesisVideoClient: KinesisVideoClient
}): Promise<KvsSignalingMetadata> =>
  resolveCachedKvsSignalingMetadata({
    channelName,
    region,
    loadMetadata: async () => {
      const describeResponse = await kinesisVideoClient.send(
        new DescribeSignalingChannelCommand({
          ChannelName: channelName,
        }),
      )
      const channelArn = describeResponse.ChannelInfo?.ChannelARN
      if (!channelArn) {
        throw new Error(`KVS signaling channel ${channelName} was not found`)
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
        throw new Error(`KVS signaling channel ${channelName} did not return HTTPS and WSS endpoints`)
      }

      return {
        channelArn,
        endpoints: {
          HTTPS: endpoints.HTTPS,
          WSS: endpoints.WSS,
        },
      }
    },
  })

export const startBoardVideoViewerRuntime = async (
  options: StartVideoViewerOptions,
): Promise<VideoViewerHandle> => {
  const logVideoDebug = (message: string, details?: unknown): void => {
    if ((options.isDebugEnabled?.() ?? options.debugEnabled) !== true) {
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
  const { channelArn, endpoints } = await resolveKvsSignalingMetadata({
    channelName: options.channelName,
    region: options.region,
    kinesisVideoClient,
  })
  logVideoDebug('signaling metadata resolved', { channelArn, endpoints })

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

export const startBoardMcpDataChannelRuntime = async (
  options: StartMcpDataChannelOptions,
): Promise<McpDataChannelHandle> => {
  const logMcpDebug = (message: string, details?: unknown): void => {
    if ((options.isDebugEnabled?.() ?? options.debugEnabled) !== true) {
      return
    }
    if (details === undefined) {
      console.info('[device-mcp-webrtc]', message)
      return
    }
    console.info('[device-mcp-webrtc]', message, details)
  }

  const kvsWebRtcBrowserSdkPromise = loadKvsWebRtcBrowserSdk()
  const idToken = await options.resolveIdToken()
  const credentialProvider = createCredentialProvider(idToken)
  const credentials = await credentialProvider()
  const kinesisVideoClient = new KinesisVideoClient({
    region: options.region,
    credentials: credentialProvider,
  })
  const { channelArn, endpoints } = await resolveKvsSignalingMetadata({
    channelName: options.channelName,
    region: options.region,
    kinesisVideoClient,
  })

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
  const dataChannel = peerConnection.createDataChannel(options.label)
  peerConnection.addTransceiver('video', { direction: 'recvonly' })
  logMcpDebug('peer connection created', { clientId, label: options.label })

  const pendingRequests = new Map<
    number,
    {
      resolve: (result: unknown) => void
      reject: (error: Error) => void
      timeoutId: number
    }
  >()
  let closed = false
  let signalingClient: KvsWebRtcSignalingClient | null = null

  const rejectPending = (error: Error): void => {
    for (const [requestId, pending] of [...pendingRequests.entries()]) {
      pendingRequests.delete(requestId)
      window.clearTimeout(pending.timeoutId)
      pending.reject(error)
    }
  }

  const closePeer = (): void => {
    if (closed) {
      return
    }
    closed = true
    rejectPending(new Error('MCP WebRTC data channel closed'))
    signalingClient?.removeAllListeners()
    signalingClient?.close()
    dataChannel.close()
    peerConnection.getReceivers().forEach((receiver) => {
      receiver.track?.stop()
    })
    peerConnection.close()
    logMcpDebug('closed')
  }

  const handleDataChannelMessage = (event: MessageEvent): void => {
    if (typeof event.data !== 'string') {
      return
    }
    let parsed: unknown
    try {
      parsed = JSON.parse(event.data)
    } catch {
      return
    }
    if (!isRecord(parsed) || typeof parsed.id !== 'number') {
      return
    }
    const pending = pendingRequests.get(parsed.id)
    if (!pending) {
      return
    }
    pendingRequests.delete(parsed.id)
    window.clearTimeout(pending.timeoutId)
    if (isRecord(parsed.error)) {
      const message =
        typeof parsed.error.message === 'string'
          ? parsed.error.message
          : `MCP request failed with code ${String(parsed.error.code ?? 'unknown')}`
      pending.reject(new Error(message))
      return
    }
    pending.resolve(parsed.result)
  }

  dataChannel.addEventListener('message', handleDataChannelMessage)
  dataChannel.addEventListener('close', () => {
    if (!closed) {
      closePeer()
    }
  })
  dataChannel.addEventListener('error', () => {
    if (!closed) {
      closePeer()
    }
  })

  const { Role, SignalingClient } = await kvsWebRtcBrowserSdkPromise
  const createdSignalingClient: KvsWebRtcSignalingClient = new SignalingClient({
    channelARN: channelArn,
    channelEndpoint: endpoints.WSS,
    role: Role.VIEWER,
    region: options.region,
    clientId,
    credentials: toSignalingCredentials(credentials),
  })
  signalingClient = createdSignalingClient

  peerConnection.addEventListener('icecandidate', ({ candidate }) => {
    const candidateSdp = candidate?.candidate.trim() ?? ''
    if (candidate && candidateSdp !== '') {
      createdSignalingClient.sendIceCandidate(candidate)
    }
  })
  peerConnection.addEventListener('connectionstatechange', () => {
    if (
      peerConnection.connectionState === 'failed' ||
      peerConnection.connectionState === 'disconnected' ||
      peerConnection.connectionState === 'closed'
    ) {
      closePeer()
    }
  })
  peerConnection.addEventListener('track', (event) => {
    event.track.stop()
  })

  const openPromise = new Promise<McpDataChannelHandle>((resolve, reject) => {
    dataChannel.addEventListener(
      'open',
      () => {
        logMcpDebug('data channel open', { clientId })
        resolve({
          sessionId: clientId,
          request: (message, timeoutMs) => {
            if (closed || dataChannel.readyState !== 'open') {
              return Promise.reject(new Error('MCP WebRTC data channel is not open'))
            }
            const requestId = message.id
            if (typeof requestId !== 'number') {
              return Promise.reject(new Error('MCP WebRTC request id must be numeric'))
            }
            return new Promise<unknown>((requestResolve, requestReject) => {
              const timeoutId = window.setTimeout(() => {
                pendingRequests.delete(requestId)
                requestReject(new Error('Timed out waiting for MCP WebRTC response'))
              }, timeoutMs)
              pendingRequests.set(requestId, {
                resolve: requestResolve,
                reject: requestReject,
                timeoutId,
              })
              try {
                dataChannel.send(JSON.stringify(message))
              } catch (caughtError) {
                pendingRequests.delete(requestId)
                window.clearTimeout(timeoutId)
                requestReject(
                  new Error(`Unable to send MCP WebRTC request: ${getErrorMessage(caughtError)}`),
                )
              }
            })
          },
          notify: async (message) => {
            if (closed || dataChannel.readyState !== 'open') {
              throw new Error('MCP WebRTC data channel is not open')
            }
            dataChannel.send(JSON.stringify(message))
          },
          close: closePeer,
        })
      },
      { once: true },
    )
    dataChannel.addEventListener(
      'error',
      () => reject(new Error('MCP WebRTC data channel failed before opening')),
      { once: true },
    )
    dataChannel.addEventListener(
      'close',
      () => reject(new Error('MCP WebRTC data channel closed before opening')),
      { once: true },
    )
  })

  createdSignalingClient.on('open', () => {
    void (async () => {
      const offer = await peerConnection.createOffer()
      await peerConnection.setLocalDescription(offer)
      if (!peerConnection.localDescription) {
        throw new Error('MCP WebRTC local description was not created')
      }
      createdSignalingClient.sendSdpOffer(peerConnection.localDescription)
    })().catch((error) => {
      closePeer()
      logMcpDebug('offer failed', error)
    })
  })
  createdSignalingClient.on('sdpAnswer', (answer: RTCSessionDescriptionInit) => {
    void peerConnection.setRemoteDescription(answer).catch(() => closePeer())
  })
  createdSignalingClient.on('iceCandidate', (candidate: RTCIceCandidateInit) => {
    void peerConnection.addIceCandidate(candidate).catch(() => undefined)
  })
  createdSignalingClient.on('error', () => closePeer())
  createdSignalingClient.on('close', () => closePeer())
  createdSignalingClient.open()

  let openTimeoutId: number | null = null
  const openTimeoutPromise =
    options.openTimeoutMs && options.openTimeoutMs > 0
      ? new Promise<McpDataChannelHandle>((_resolve, reject) => {
          openTimeoutId = window.setTimeout(() => {
            closePeer()
            reject(new Error('Timed out opening MCP WebRTC data channel'))
          }, options.openTimeoutMs)
        })
      : null

  try {
    const handle = await (openTimeoutPromise
      ? Promise.race([openPromise, openTimeoutPromise])
      : openPromise)
    if (openTimeoutId !== null) {
      window.clearTimeout(openTimeoutId)
      openTimeoutId = null
    }
    return handle
  } catch (error) {
    if (openTimeoutId !== null) {
      window.clearTimeout(openTimeoutId)
      openTimeoutId = null
    }
    closePeer()
    throw error
  }
}
