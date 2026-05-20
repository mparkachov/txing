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
type KinesisVideoClientConfig = NonNullable<ConstructorParameters<typeof KinesisVideoClient>[0]>
type KinesisVideoSignalingClientConfig = NonNullable<
  ConstructorParameters<typeof KinesisVideoSignalingClient>[0]
>

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
      urls: `stun:stun.kinesisvideo.${region}.api.aws:443`,
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

export const buildKinesisVideoClientConfig = ({
  credentials,
  region,
}: {
  credentials: ReturnType<typeof createCredentialProvider>
  region: string
}): KinesisVideoClientConfig => ({
  region,
  credentials,
  useDualstackEndpoint: true,
})

export const buildKinesisVideoSignalingClientConfig = ({
  credentials,
  endpoint,
  region,
}: {
  credentials: ReturnType<typeof createCredentialProvider>
  endpoint: string
  region: string
}): KinesisVideoSignalingClientConfig => ({
  region,
  endpoint,
  credentials,
})

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

type BoardRtcVideoConsumer = {
  onRemoteStream: (stream: MediaStream) => void
  onUiEvent: (event: ViewerUiEvent) => void
}

type SharedBoardRtcSession = {
  sessionId: string
  addVideoConsumer: (consumer: BoardRtcVideoConsumer) => () => void
  acquireMcpHandle: () => McpDataChannelHandle
  close: () => void
}

type SharedBoardRtcSessionOptions = {
  channelName: string
  region: string
  label: string
  resolveIdToken: () => Promise<string>
  debugEnabled?: boolean
  isDebugEnabled?: () => boolean
}

const sharedBoardRtcSessions = new Map<string, Promise<SharedBoardRtcSession>>()

const sharedBoardRtcSessionKey = (
  region: string,
  channelName: string,
  label: string,
): string => `${region}\u0000${channelName}\u0000${label}`

const createSharedBoardRtcSession = async (
  key: string,
  options: SharedBoardRtcSessionOptions,
): Promise<SharedBoardRtcSession> => {
  const logDebug = (message: string, details?: unknown): void => {
    if ((options.isDebugEnabled?.() ?? options.debugEnabled) !== true) {
      return
    }
    if (details === undefined) {
      console.info('[device-rtc]', message)
      return
    }
    console.info('[device-rtc]', message, details)
  }

  const kvsWebRtcBrowserSdkPromise = loadKvsWebRtcBrowserSdk()
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
  const dataChannel = peerConnection.createDataChannel(options.label)
  const videoConsumers = new Set<BoardRtcVideoConsumer>()
  const pendingRequests = new Map<
    number,
    {
      resolve: (result: unknown) => void
      reject: (error: Error) => void
      timeoutId: number
    }
  >()
  let mcpConsumerCount = 0
  let closed = false
  let dataChannelOpened = false
  let remoteStream: MediaStream | null = null
  let signalingClient: KvsWebRtcSignalingClient | null = null

  const rejectPending = (error: Error): void => {
    for (const [requestId, pending] of [...pendingRequests.entries()]) {
      pendingRequests.delete(requestId)
      window.clearTimeout(pending.timeoutId)
      pending.reject(error)
    }
  }

  const closePeer = (notifyVideoError = false, errorMessage = 'Board RTC session closed'): void => {
    if (closed) {
      return
    }
    closed = true
    sharedBoardRtcSessions.delete(key)
    rejectPending(new Error('MCP WebRTC data channel closed'))
    signalingClient?.removeAllListeners()
    signalingClient?.close()
    dataChannel.close()
    peerConnection.getReceivers().forEach((receiver) => {
      receiver.track?.stop()
    })
    peerConnection.close()
    if (notifyVideoError) {
      for (const consumer of videoConsumers) {
        consumer.onUiEvent({ type: 'error', message: errorMessage })
      }
    }
    videoConsumers.clear()
    logDebug('shared RTC session closed', { clientId, errorMessage })
  }

  const closeIfUnused = (): void => {
    if (videoConsumers.size === 0 && mcpConsumerCount === 0) {
      closePeer(false)
    }
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

  const deliverRemoteStream = (
    consumer: BoardRtcVideoConsumer,
    stream: MediaStream,
  ): void => {
    consumer.onRemoteStream(new MediaStream(stream.getTracks().map((track) => track.clone())))
  }

  const session: SharedBoardRtcSession = {
    sessionId: clientId,
    addVideoConsumer: (consumer) => {
      if (closed) {
        consumer.onUiEvent({ type: 'error', message: 'Board RTC session is closed' })
        return () => undefined
      }
      videoConsumers.add(consumer)
      consumer.onUiEvent({ type: 'connecting' })
      if (remoteStream) {
        deliverRemoteStream(consumer, remoteStream)
      }
      return () => {
        videoConsumers.delete(consumer)
        consumer.onUiEvent({ type: 'reset' })
        closeIfUnused()
      }
    },
    acquireMcpHandle: () => {
      if (closed || !dataChannelOpened || dataChannel.readyState !== 'open') {
        throw new Error('MCP WebRTC data channel is not open')
      }
      let released = false
      mcpConsumerCount += 1
      return {
        sessionId: clientId,
        request: (message, timeoutMs) => {
          if (closed || dataChannel.readyState !== 'open') {
            return Promise.reject(new Error('MCP WebRTC data channel is not open'))
          }
          const requestId = message.id
          if (typeof requestId !== 'number') {
            return Promise.reject(new Error('MCP WebRTC request id must be numeric'))
          }
          return new Promise<unknown>((resolve, reject) => {
            const timeoutId = window.setTimeout(() => {
              pendingRequests.delete(requestId)
              reject(new Error('Timed out waiting for MCP WebRTC response'))
            }, timeoutMs)
            pendingRequests.set(requestId, { resolve, reject, timeoutId })
            try {
              dataChannel.send(JSON.stringify(message))
            } catch (caughtError) {
              pendingRequests.delete(requestId)
              window.clearTimeout(timeoutId)
              reject(new Error(`Unable to send MCP WebRTC request: ${getErrorMessage(caughtError)}`))
            }
          })
        },
        notify: async (message) => {
          if (closed || dataChannel.readyState !== 'open') {
            throw new Error('MCP WebRTC data channel is not open')
          }
          dataChannel.send(JSON.stringify(message))
        },
        close: () => {
          if (released) {
            return
          }
          released = true
          mcpConsumerCount = Math.max(0, mcpConsumerCount - 1)
          closeIfUnused()
        },
      }
    },
    close: () => closePeer(false),
  }

  peerConnection.addEventListener('track', (event) => {
    const stream = event.streams[0]
    if (!stream) {
      logDebug('remote track received without stream', {
        trackId: event.track.id,
        kind: event.track.kind,
      })
      return
    }
    remoteStream = stream
    logDebug('remote stream received', {
      streamId: stream.id,
      trackIds: stream.getTracks().map((track) => track.id),
    })
    for (const consumer of videoConsumers) {
      deliverRemoteStream(consumer, stream)
    }
  })
  peerConnection.addEventListener('icecandidate', ({ candidate }) => {
    const candidateSdp = candidate?.candidate.trim() ?? ''
    if (candidate && candidateSdp !== '' && signalingClient) {
      logDebug('local ICE candidate', {
        type: extractCandidateType(candidateSdp),
        sdpMid: candidate.sdpMid,
      })
      signalingClient.sendIceCandidate(candidate)
    }
  })
  peerConnection.addEventListener('connectionstatechange', () => {
    logDebug('peer connection state', {
      connectionState: peerConnection.connectionState,
      iceConnectionState: peerConnection.iceConnectionState,
    })
    if (
      peerConnection.connectionState === 'failed' ||
      peerConnection.connectionState === 'disconnected' ||
      peerConnection.connectionState === 'closed'
    ) {
      closePeer(true, `Board RTC connection ${peerConnection.connectionState}`)
    }
  })
  dataChannel.addEventListener('message', handleDataChannelMessage)
  dataChannel.addEventListener('close', () => {
    closePeer(true, 'MCP WebRTC data channel closed')
  })
  dataChannel.addEventListener('error', () => {
    closePeer(true, 'MCP WebRTC data channel error')
  })

  const { Role, SignalingClient } = await kvsWebRtcBrowserSdkPromise
  signalingClient = new SignalingClient({
    channelARN: channelArn,
    channelEndpoint: endpoints.WSS,
    role: Role.VIEWER,
    region: options.region,
    clientId,
    credentials: toSignalingCredentials(credentials),
  })

  const openPromise = new Promise<SharedBoardRtcSession>((resolve, reject) => {
    dataChannel.addEventListener(
      'open',
      () => {
        dataChannelOpened = true
        logDebug('MCP data channel open', { clientId })
        resolve(session)
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

  signalingClient.on('open', () => {
    void (async () => {
      const offer = await peerConnection.createOffer()
      await peerConnection.setLocalDescription(offer)
      if (!peerConnection.localDescription) {
        throw new Error('Board RTC local description was not created')
      }
      signalingClient?.sendSdpOffer(peerConnection.localDescription)
    })().catch((error) => {
      closePeer(true, getErrorMessage(error, 'Unable to create board RTC offer'))
    })
  })
  signalingClient.on('sdpAnswer', (answer: RTCSessionDescriptionInit) => {
    void peerConnection.setRemoteDescription(answer).catch((error) => {
      closePeer(true, getErrorMessage(error, 'Unable to apply board RTC answer'))
    })
  })
  signalingClient.on('iceCandidate', (candidate: RTCIceCandidateInit) => {
    void peerConnection.addIceCandidate(candidate).catch(() => undefined)
  })
  signalingClient.on('error', (error) => {
    logDebug('signaling error', error)
    if (!dataChannelOpened) {
      closePeer(true, getErrorMessage(error, 'Board RTC signaling failed'))
    }
  })
  signalingClient.on('close', () => {
    logDebug('signaling close')
    if (!dataChannelOpened) {
      closePeer(true, 'Board RTC signaling closed')
    }
  })
  signalingClient.open()

  return openPromise
}

const getSharedBoardRtcSession = (
  options: SharedBoardRtcSessionOptions,
): Promise<SharedBoardRtcSession> => {
  const key = sharedBoardRtcSessionKey(options.region, options.channelName, options.label)
  const existing = sharedBoardRtcSessions.get(key)
  if (existing) {
    return existing
  }

  const created = createSharedBoardRtcSession(key, options).catch((error: unknown) => {
    if (sharedBoardRtcSessions.get(key) === created) {
      sharedBoardRtcSessions.delete(key)
    }
    throw error
  })
  sharedBoardRtcSessions.set(key, created)
  return created
}

const startSharedBoardVideoViewerRuntime = async (
  options: StartVideoViewerOptions,
): Promise<VideoViewerHandle> => {
  options.onUiEvent({ type: 'connecting' })
  const session = await getSharedBoardRtcSession({
    channelName: options.channelName,
    region: options.region,
    label: 'txing.mcp.v1',
    resolveIdToken: options.resolveIdToken,
    debugEnabled: options.debugEnabled,
    isDebugEnabled: options.isDebugEnabled,
  })
  const release = session.addVideoConsumer({
    onRemoteStream: options.onRemoteStream,
    onUiEvent: options.onUiEvent,
  })
  return {
    close: release,
  }
}

const startSharedBoardMcpDataChannelRuntime = async (
  options: StartMcpDataChannelOptions,
): Promise<McpDataChannelHandle> => {
  const sessionPromise = getSharedBoardRtcSession(options)
  const openTimeoutPromise =
    options.openTimeoutMs && options.openTimeoutMs > 0
      ? new Promise<SharedBoardRtcSession>((_resolve, reject) => {
          window.setTimeout(() => {
            reject(new Error('Timed out opening MCP WebRTC data channel'))
          }, options.openTimeoutMs)
        })
      : null

  try {
    const session = await (openTimeoutPromise
      ? Promise.race([sessionPromise, openTimeoutPromise])
      : sessionPromise)
    return session.acquireMcpHandle()
  } catch (error) {
    void sessionPromise.then((session) => session.close()).catch(() => undefined)
    throw error
  }
}

export const startBoardVideoViewerRuntime = async (
  options: StartVideoViewerOptions,
): Promise<VideoViewerHandle> => startSharedBoardVideoViewerRuntime(options)

export const startBoardMcpDataChannelRuntime = async (
  options: StartMcpDataChannelOptions,
): Promise<McpDataChannelHandle> => startSharedBoardMcpDataChannelRuntime(options)
