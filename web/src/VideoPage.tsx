import { useEffect, useEffectEvent, useReducer, useRef } from 'react'
import type { AuthUser } from './auth'
import { resolveViewerChannelName } from './app-model'
import { appConfig } from './config'
import {
  reduceViewerUiState,
  startBoardVideoViewer,
  type ViewerUiState,
} from './video-session'

type VideoPageProps = {
  authUser: AuthUser | null
  resolveIdToken: () => Promise<string>
  onSignOut: () => void
}
type VideoElementWithFrameCallback = HTMLVideoElement & {
  requestVideoFrameCallback?: (callback: VideoFrameRequestCallback) => number
}

const logVideoUiDebug = (message: string, details?: unknown): void => {
  if (details === undefined) {
    console.info('[txing-video-ui]', message)
    return
  }
  console.info('[txing-video-ui]', message, details)
}

const initialViewerUiState: ViewerUiState = {
  status: 'idle',
  error: '',
}

const getViewerStatusLabel = (state: ViewerUiState): string => {
  switch (state.status) {
    case 'idle':
      return 'Waiting to open board video...'
    case 'connecting':
      return 'Connecting to board video...'
    case 'streaming':
      return 'Board video live'
    case 'error':
      return 'Board video unavailable'
  }
}

function VideoPage({ authUser, resolveIdToken, onSignOut }: VideoPageProps) {
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const remoteStreamRef = useRef<MediaStream | null>(null)
  const activeStreamTokenRef = useRef(0)
  const [viewerState, dispatchViewerUiEvent] = useReducer(
    reduceViewerUiState,
    initialViewerUiState,
  )
  const channelName = resolveViewerChannelName(window.location.href, null)
  const resolveIdTokenForViewer = useEffectEvent(async (): Promise<string> => resolveIdToken())
  const attemptVideoPlayback = useEffectEvent(async (reason: string): Promise<void> => {
    const videoElement = videoRef.current
    if (!videoElement || !videoElement.srcObject) {
      return
    }

    if (!videoElement.paused) {
      return
    }

    try {
      await videoElement.play()
      logVideoUiDebug(`video.play resolved (${reason})`, {
        readyState: videoElement.readyState,
        paused: videoElement.paused,
        currentTime: videoElement.currentTime,
      })
    } catch {
      logVideoUiDebug(`video.play rejected (${reason})`, {
        readyState: videoElement.readyState,
        paused: videoElement.paused,
        currentTime: videoElement.currentTime,
      })
    }
  })

  useEffect(() => {
    let cancelled = false
    let viewerHandle: { close: () => void } | null = null
    const videoElement = videoRef.current

    const logVideoElementState = (eventName: string): void => {
      if (!videoElement) {
        logVideoUiDebug(`${eventName} without video element`)
        return
      }

      logVideoUiDebug(eventName, {
        readyState: videoElement.readyState,
        networkState: videoElement.networkState,
        paused: videoElement.paused,
        currentTime: videoElement.currentTime,
        videoWidth: videoElement.videoWidth,
        videoHeight: videoElement.videoHeight,
        error: videoElement.error
          ? {
              code: videoElement.error.code,
              message: videoElement.error.message,
            }
          : null,
      })
    }

    const detachVideoListeners = (() => {
      if (!videoElement) {
        return () => undefined
      }

      const listeners = [
        'loadedmetadata',
        'loadeddata',
        'canplay',
        'play',
        'playing',
        'pause',
        'waiting',
        'stalled',
        'suspend',
        'emptied',
        'resize',
        'error',
      ] as const

      const handlerMap = new Map<string, EventListener>()
      for (const eventName of listeners) {
        const handler: EventListener = () => {
          logVideoElementState(`video event: ${eventName}`)
          if (
            eventName === 'loadedmetadata' ||
            eventName === 'loadeddata' ||
            eventName === 'canplay'
          ) {
            void attemptVideoPlayback(eventName)
          }
        }
        handlerMap.set(eventName, handler)
        videoElement.addEventListener(eventName, handler)
      }

      return () => {
        for (const [eventName, handler] of handlerMap) {
          videoElement.removeEventListener(eventName, handler)
        }
      }
    })()

    logVideoUiDebug('viewer page effect start', { channelName })

    void startBoardVideoViewer({
      channelName,
      region: appConfig.awsRegion,
      resolveIdToken: resolveIdTokenForViewer,
      onRemoteStream: (stream) => {
        logVideoUiDebug('remote stream attached', {
          streamId: stream.id,
          trackIds: stream.getTracks().map((track) => track.id),
          trackKinds: stream.getTracks().map((track) => track.kind),
        })
        const streamToken = activeStreamTokenRef.current + 1
        activeStreamTokenRef.current = streamToken
        remoteStreamRef.current = stream
        if (!videoElement) {
          logVideoUiDebug('remote stream received but no video element')
          return
        }

        videoElement.srcObject = stream
        logVideoElementState('video srcObject assigned')

        const markStreaming = (): void => {
          if (activeStreamTokenRef.current !== streamToken) {
            return
          }
          logVideoElementState('decoded frame available')
          void attemptVideoPlayback('decoded-frame')
          dispatchViewerUiEvent({ type: 'streaming' })
        }

        const playVideo = async (): Promise<void> => {
          try {
            await videoElement.play()
            logVideoElementState('video.play resolved')
          } catch {
            logVideoElementState('video.play rejected')
          }

          const videoWithFrameCallback = videoElement as VideoElementWithFrameCallback
          if (typeof videoWithFrameCallback.requestVideoFrameCallback === 'function') {
            videoWithFrameCallback.requestVideoFrameCallback(() => {
              markStreaming()
            })
            return
          }

          videoElement.addEventListener('loadeddata', markStreaming, { once: true })
        }

        void playVideo()
      },
      onUiEvent: dispatchViewerUiEvent,
    })
      .then((handle) => {
        if (cancelled) {
          handle.close()
          return
        }
        viewerHandle = handle
      })
      .catch((caughtError) => {
        dispatchViewerUiEvent({
          type: 'error',
          message:
            caughtError instanceof Error ? caughtError.message : 'Unable to open board video',
        })
      })

    return () => {
      cancelled = true
      viewerHandle?.close()
      detachVideoListeners()
      activeStreamTokenRef.current += 1
      if (remoteStreamRef.current) {
        remoteStreamRef.current.getTracks().forEach((track) => track.stop())
        remoteStreamRef.current = null
      }
      if (videoRef.current) {
        videoRef.current.srcObject = null
      }
      logVideoUiDebug('viewer page effect cleanup', { channelName })
    }
  }, [channelName])

  return (
    <main className="page page-video">
      <section className="video-shell">
        <header className="video-header">
          <div>
            <p className="video-kicker">Txing operator video</p>
            <h1>Board camera</h1>
            <p className="video-subtitle">
              Channel <code>{channelName}</code>
            </p>
          </div>
          <div className="video-actions">
            <span className="video-user">{authUser?.email ?? authUser?.sub ?? 'Unknown user'}</span>
            <a className="secondary" href="/">
              Back
            </a>
            <button type="button" className="primary" onClick={onSignOut}>
              Sign off
            </button>
          </div>
        </header>

        <div className="video-status-bar" aria-live="polite">
          <span className={`video-status-pill video-status-pill-${viewerState.status}`}>
            {getViewerStatusLabel(viewerState)}
          </span>
          {viewerState.error ? <span className="error">{viewerState.error}</span> : null}
        </div>

        <div className="video-stage">
          <video
            ref={videoRef}
            className="video-stream"
            autoPlay
            playsInline
            muted
            controls={false}
          />
          {viewerState.status !== 'streaming' ? (
            <div className="video-placeholder">{getViewerStatusLabel(viewerState)}</div>
          ) : null}
        </div>
      </section>
    </main>
  )
}

export default VideoPage
