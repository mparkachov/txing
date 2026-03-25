import { useEffect, useReducer, useRef } from 'react'
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
  const [viewerState, dispatchViewerUiEvent] = useReducer(
    reduceViewerUiState,
    initialViewerUiState,
  )
  const channelName = resolveViewerChannelName(window.location.href, null)

  useEffect(() => {
    let cancelled = false
    let viewerHandle: { close: () => void } | null = null

    void startBoardVideoViewer({
      channelName,
      region: appConfig.awsRegion,
      resolveIdToken,
      onRemoteStream: (stream) => {
        remoteStreamRef.current = stream
        if (videoRef.current) {
          videoRef.current.srcObject = stream
        }
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
      if (remoteStreamRef.current) {
        remoteStreamRef.current.getTracks().forEach((track) => track.stop())
        remoteStreamRef.current = null
      }
      if (videoRef.current) {
        videoRef.current.srcObject = null
      }
    }
  }, [channelName, resolveIdToken])

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
