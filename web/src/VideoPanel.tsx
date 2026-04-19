import { useEffect, useEffectEvent, useReducer, useRef } from 'react'
import { resolveViewerChannelName } from './app-model'
import { appConfig } from './config'
import {
  reduceViewerUiState,
  startBoardVideoViewer,
  type ViewerUiState,
} from './video-session'

type VideoPanelProps = {
  resolveIdToken: () => Promise<string>
  channelName?: string | null
  debugEnabled?: boolean
  onRuntimeError?: (message: string) => void
}
type VideoElementWithFrameCallback = HTMLVideoElement & {
  requestVideoFrameCallback?: (callback: VideoFrameRequestCallback) => number
  cancelVideoFrameCallback?: (handle: number) => void
}
type VideoFrameLike = CanvasImageSource & {
  close: () => void
  codedWidth: number
  codedHeight: number
}
type MediaStreamTrackProcessorInstance = {
  readable: ReadableStream<VideoFrameLike>
}
type MediaStreamTrackProcessorConstructor = new (init: {
  track: MediaStreamTrack
}) => MediaStreamTrackProcessorInstance

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

function VideoPanel({
  resolveIdToken,
  channelName: preferredChannelName = null,
  debugEnabled = false,
  onRuntimeError,
}: VideoPanelProps) {
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const remoteStreamRef = useRef<MediaStream | null>(null)
  const activeStreamTokenRef = useRef(0)
  const [viewerState, dispatchViewerUiEvent] = useReducer(
    reduceViewerUiState,
    initialViewerUiState,
  )
  const channelName = resolveViewerChannelName(window.location.href, preferredChannelName)
  const logVideoUiDebug = useEffectEvent((message: string, details?: unknown): void => {
    if (!debugEnabled) {
      return
    }
    if (details === undefined) {
      console.info('[device-video-ui]', message)
      return
    }
    console.info('[device-video-ui]', message, details)
  })
  const resolveIdTokenForViewer = useEffectEvent(async (): Promise<string> => resolveIdToken())
  const drawCanvasSource = useEffectEvent((
    source: CanvasImageSource,
    sourceWidth: number,
    sourceHeight: number,
  ): void => {
    const canvasElement = canvasRef.current
    if (!canvasElement || sourceWidth <= 0 || sourceHeight <= 0) {
      return
    }

    const cssWidth = Math.max(1, canvasElement.clientWidth)
    const cssHeight = Math.max(1, canvasElement.clientHeight)
    const pixelRatio = window.devicePixelRatio || 1
    const targetWidth = Math.max(1, Math.round(cssWidth * pixelRatio))
    const targetHeight = Math.max(1, Math.round(cssHeight * pixelRatio))

    if (canvasElement.width !== targetWidth || canvasElement.height !== targetHeight) {
      canvasElement.width = targetWidth
      canvasElement.height = targetHeight
    }

    const context = canvasElement.getContext('2d')
    if (!context) {
      return
    }

    context.setTransform(1, 0, 0, 1, 0, 0)
    context.clearRect(0, 0, canvasElement.width, canvasElement.height)
    context.fillStyle = '#05080f'
    context.fillRect(0, 0, canvasElement.width, canvasElement.height)

    const scale = Math.min(
      canvasElement.width / sourceWidth,
      canvasElement.height / sourceHeight,
    )
    const drawWidth = Math.round(sourceWidth * scale)
    const drawHeight = Math.round(sourceHeight * scale)
    const drawX = Math.round((canvasElement.width - drawWidth) / 2)
    const drawY = Math.round((canvasElement.height - drawHeight) / 2)
    context.drawImage(source, drawX, drawY, drawWidth, drawHeight)
  })
  const syncCanvasFromVideo = useEffectEvent((reason: string, metadata?: VideoFrameCallbackMetadata): void => {
    const videoElement = videoRef.current
    if (!videoElement || videoElement.videoWidth <= 0 || videoElement.videoHeight <= 0) {
      return
    }

    drawCanvasSource(videoElement, videoElement.videoWidth, videoElement.videoHeight)

    if (!metadata) {
      return
    }

    const presentedFrames = metadata.presentedFrames
    if (presentedFrames <= 3 || presentedFrames % 150 === 0) {
      logVideoUiDebug('video frame callback', {
        reason,
        presentedFrames,
        mediaTime: metadata.mediaTime,
        expectedDisplayTime: metadata.expectedDisplayTime,
        presentationTime: metadata.presentationTime,
      })
    }
  })
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
    if (viewerState.status !== 'error' || !viewerState.error) {
      return
    }
    onRuntimeError?.(viewerState.error)
  }, [onRuntimeError, viewerState.error, viewerState.status])

  useEffect(() => {
    let cancelled = false
    let viewerHandle: { close: () => void } | null = null
    let activeFrameCallbackHandle: number | null = null
    let activeTrackProcessorReader: ReadableStreamDefaultReader<VideoFrameLike> | null = null
    const videoElement = videoRef.current
    const canvasElement = canvasRef.current

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

    logVideoUiDebug('viewer panel effect start', { channelName })

    void startBoardVideoViewer({
      channelName,
      region: appConfig.awsRegion,
      resolveIdToken: resolveIdTokenForViewer,
      debugEnabled,
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

        const markStreaming = (): void => {
          if (activeStreamTokenRef.current !== streamToken) {
            return
          }
          dispatchViewerUiEvent({ type: 'streaming' })
        }

        const trackProcessorConstructor = (
          window as Window & {
            MediaStreamTrackProcessor?: MediaStreamTrackProcessorConstructor
          }
        ).MediaStreamTrackProcessor
        const videoTrack = stream.getVideoTracks()[0]
        if (trackProcessorConstructor && videoTrack) {
          logVideoUiDebug('using track processor renderer', { trackId: videoTrack.id })
          const processor = new trackProcessorConstructor({ track: videoTrack })
          const reader = processor.readable.getReader()
          activeTrackProcessorReader = reader

          void (async () => {
            let presentedFrames = 0
            try {
              while (activeStreamTokenRef.current === streamToken) {
                const { value, done } = await reader.read()
                if (done || !value) {
                  break
                }

                presentedFrames += 1
                drawCanvasSource(value, value.codedWidth, value.codedHeight)
                if (presentedFrames <= 3 || presentedFrames % 150 === 0) {
                  logVideoUiDebug('track processor frame', {
                    presentedFrames,
                    codedWidth: value.codedWidth,
                    codedHeight: value.codedHeight,
                  })
                }
                if (presentedFrames === 1) {
                  logVideoUiDebug('track processor first frame')
                  markStreaming()
                }
                value.close()
              }
            } catch (caughtError) {
              if (activeStreamTokenRef.current === streamToken) {
                logVideoUiDebug('track processor failed', caughtError)
              }
            } finally {
              reader.releaseLock()
            }
          })()
          return
        }

        videoElement.srcObject = stream
        logVideoElementState('video srcObject assigned')
        const markStreamingFromVideo = (): void => {
          logVideoElementState('decoded frame available')
          syncCanvasFromVideo('decoded-frame')
          void attemptVideoPlayback('decoded-frame')
          markStreaming()
        }

        const videoWithFrameCallback = videoElement as VideoElementWithFrameCallback
        const scheduleFrameCallback = (): void => {
          if (
            activeStreamTokenRef.current !== streamToken ||
            typeof videoWithFrameCallback.requestVideoFrameCallback !== 'function'
          ) {
            return
          }

          activeFrameCallbackHandle = videoWithFrameCallback.requestVideoFrameCallback((_, metadata) => {
            if (activeStreamTokenRef.current !== streamToken) {
              return
            }

            syncCanvasFromVideo('requestVideoFrameCallback', metadata)
            markStreamingFromVideo()
            scheduleFrameCallback()
          })
        }

        const playVideo = async (): Promise<void> => {
          try {
            await videoElement.play()
            logVideoElementState('video.play resolved')
          } catch {
            logVideoElementState('video.play rejected')
          }

          if (typeof videoWithFrameCallback.requestVideoFrameCallback === 'function') {
            scheduleFrameCallback()
            return
          }

          videoElement.addEventListener('loadeddata', markStreamingFromVideo, { once: true })
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
      if (activeTrackProcessorReader !== null) {
        void activeTrackProcessorReader.cancel().catch(() => undefined)
        activeTrackProcessorReader = null
      }
      if (activeFrameCallbackHandle !== null) {
        const currentVideo = videoElement as VideoElementWithFrameCallback | null
        currentVideo?.cancelVideoFrameCallback?.(activeFrameCallbackHandle)
        activeFrameCallbackHandle = null
      }
      detachVideoListeners()
      activeStreamTokenRef.current += 1
      if (remoteStreamRef.current) {
        remoteStreamRef.current.getTracks().forEach((track) => track.stop())
        remoteStreamRef.current = null
      }
      if (canvasElement) {
        const context = canvasElement.getContext('2d')
        context?.clearRect(0, 0, canvasElement.width, canvasElement.height)
      }
      if (videoElement) {
        videoElement.srcObject = null
      }
      logVideoUiDebug('viewer panel effect cleanup', { channelName })
    }
  }, [channelName, debugEnabled])

  return (
    <div className="status-video-panel">
      <div className="status-video-stage">
        <video
          ref={videoRef}
          className="status-video-preview"
          autoPlay
          playsInline
          muted
          controls={false}
        />
        <canvas ref={canvasRef} className="status-video-canvas" aria-hidden="true" />
        {viewerState.status !== 'streaming' ? (
          <div className="status-video-placeholder">{getViewerStatusLabel(viewerState)}</div>
        ) : null}
      </div>
    </div>
  )
}

export default VideoPanel
