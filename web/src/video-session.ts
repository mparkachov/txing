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

type EndpointMap = Partial<Record<'HTTPS' | 'WSS', string>>
type ResourceEndpointLike = {
  Protocol?: string | null
  ResourceEndpoint?: string | null
}
type IceServerLike = {
  Password?: string | null
  Uris?: string[] | null
  Username?: string | null
}
type VideoSessionRuntimeModule = typeof import('./video-session-runtime')

let videoSessionRuntimePromise: Promise<VideoSessionRuntimeModule> | null = null

const loadVideoSessionRuntime = (): Promise<VideoSessionRuntimeModule> => {
  if (!videoSessionRuntimePromise) {
    videoSessionRuntimePromise = import('./video-session-runtime')
  }

  return videoSessionRuntimePromise
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
  endpoints: ResourceEndpointLike[] | undefined,
): EndpointMap =>
  (endpoints ?? []).reduce<EndpointMap>((result, item) => {
    if (item.Protocol === 'HTTPS' && item.ResourceEndpoint) {
      result.HTTPS = item.ResourceEndpoint
    }
    if (item.Protocol === 'WSS' && item.ResourceEndpoint) {
      result.WSS = item.ResourceEndpoint
    }
    return result
  }, {})

export const buildRtcIceServers = (
  region: string,
  iceServers: IceServerLike[] | undefined,
): RTCIceServer[] => {
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
      username: server.Username ?? undefined,
      credential: server.Password ?? undefined,
    })
  }

  return rtcIceServers
}

export const startBoardVideoViewer = async (
  options: StartVideoViewerOptions,
): Promise<VideoViewerHandle> => {
  const { startBoardVideoViewerRuntime } = await loadVideoSessionRuntime()
  return startBoardVideoViewerRuntime(options)
}

export const startBoardMcpDataChannel = async (
  options: StartMcpDataChannelOptions,
): Promise<McpDataChannelHandle> => {
  const { startBoardMcpDataChannelRuntime } = await loadVideoSessionRuntime()
  return startBoardMcpDataChannelRuntime(options)
}
