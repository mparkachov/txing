import { useEffect, useEffectEvent, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { mavlinkDriveRefreshMs, mavlinkWebRtcDataChannelLabel } from '../../../office/src/mavlink-control'
import { createCredentialProvider } from '../../../office/src/aws-credentials'
import type { AppNotificationInput } from '../../../office/src/app-notifications'
import VideoPanel from '../../../office/src/VideoPanel'
import { VideoOverlayRow, type MavlinkVideoStatus } from '../../../office/src/VideoControlOverlay'
import MavlinkControllerPanel from '../../../office/src/MavlinkControllerPanel'
import MavlinkDebugPanel from '../../../office/src/MavlinkDebugPanel'
import { VirtualQuadFlight, type QuadFlightView } from './virtual-quad-flight'
import { readQuadMavlinkStatus } from './virtual-quad-media-status'

const landedLabel: Record<number, string> = { 1: 'Landed', 2: 'Airborne', 3: 'Taking off', 4: 'Landing' }

export function VirtualQuadMavlinkDiagnostics({ status, connectionError, view, videoAvailable }: {
  status: MavlinkVideoStatus
  connectionError: string | null
  view: QuadFlightView | null
  videoAvailable: boolean
}) {
  const owner = view?.held ? 'You have control' : view?.owner ? `Control held by ${view.owner}` : 'No active controller'
  const connection = status === 'inactive' ? 'MAVLink control peer idle' : `MAVLink ${status}`
  return (
    <MavlinkDebugPanel vehicleName="Virtual quadcopter" connection={connection} owner={owner}
      flight={{ armed: view?.armed ?? null, mode: view?.mode ?? null }}>
      {videoAvailable && <p>{view?.camera ? 'Camera live' : 'Waiting for camera'}</p>}
      {view?.landed && <p>{landedLabel[view.landed]}</p>}
      {view?.position && (
        <p>
          Altitude {view.position.altitude.toFixed(1)} m
          {view.position.heading !== null && <> · Heading {view.position.heading.toFixed(1)}°</>}
          {' · '}Speed {view.position.speed.toFixed(1)} m/s
        </p>
      )}
      {videoAvailable && view?.supported === false && <p>Flight controls unavailable</p>}
      {view?.pending && <p role="status">{view.pending}</p>}
      {connectionError && <p>{connectionError}</p>}
      {view?.error && <p>{view.error}</p>}
    </MavlinkDebugPanel>
  )
}

export function VirtualQuadLiveView({
  deviceId, actor, resolveIdToken, videoAvailable, mavlinkAvailable, debugEnabled, onToggleDebug, debugTarget, notify,
}: {
  deviceId: string
  actor: string
  resolveIdToken: () => Promise<string>
  videoAvailable: boolean
  mavlinkAvailable: boolean
  debugEnabled: boolean
  onToggleDebug: () => void
  debugTarget: HTMLDivElement | null
  notify: (notification: AppNotificationInput) => void
}) {
  const videoFrameAt = useRef(-Infinity)
  const flight = useRef<VirtualQuadFlight | null>(null)
  const [view, setView] = useState<QuadFlightView | null>(null)
  const [connectionError, setConnectionError] = useState<string | null>(null)
  const readVideoTime = useEffectEvent(() => videoAvailable ? videoFrameAt.current : -Infinity)
  const mavlinkStatus = mavlinkAvailable ? readQuadMavlinkStatus(view, connectionError) : 'inactive'
  const flightError = mavlinkAvailable ? view?.error : null

  useEffect(() => {
    if (flightError) {
      notify({ tone: 'error', message: flightError, dedupeKey: `mavlink:${deviceId}:${flightError}`, objectId: deviceId })
    }
  }, [deviceId, flightError, notify])

  useEffect(() => {
    if (!videoAvailable) videoFrameAt.current = -Infinity
  }, [videoAvailable])

  useEffect(() => {
    if (!mavlinkAvailable) {
      setView(null)
      setConnectionError(null)
      return
    }
    const lifetime = new AbortController()
    let attempt: AbortController | undefined
    let connectionExpiresAt = 0
    let retry: number | undefined
    let backoff = 1_000
    let channelOpen = false

    const reconnect = (reason: string) => {
      if (lifetime.signal.aborted || retry !== undefined) return
      attempt?.abort()
      attempt = undefined
      channelOpen = false
      const retired = flight.current
      flight.current = null
      retired?.close()
      setView(null)
      setConnectionError(reason)
      retry = window.setTimeout(() => {
        retry = undefined
        connect()
      }, backoff)
      backoff = Math.min(backoff * 2, 10_000)
    }

    const connect = () => {
      attempt = new AbortController()
      const signal = AbortSignal.any([lifetime.signal, attempt.signal])
      connectionExpiresAt = performance.now() + 20_000
      const fail = (reason: string) => {
        if (!signal.aborted) reconnect(reason)
      }
      void (async () => {
        const [{ connectKvsViewer }, idToken] = await Promise.all([
          import('../../../office/src/kvs-viewer-peer'),
          resolveIdToken(),
        ])
        signal.throwIfAborted()
        await connectKvsViewer(`${deviceId}-mavlink`, createCredentialProvider(idToken), true, (pc) => {
          const channel = pc.createDataChannel(mavlinkWebRtcDataChannelLabel, { ordered: true })
          channel.binaryType = 'arraybuffer'
          const controller = new VirtualQuadFlight({
            actor,
            videoAt: () => readVideoTime(),
            sendQueueEmpty: () => channel.bufferedAmount === 0,
            onClose: () => fail(controller.view().error ?? 'Data channel closed'),
          })
          flight.current = controller
          channel.addEventListener('open', () => {
            if (signal.aborted) return
            channelOpen = true
            connectionExpiresAt = performance.now() + 15_000
            setConnectionError(null)
            controller.attach({
              close: () => channel.close(),
              sendBinary: (frame) => channel.send(new Uint8Array(frame)),
              sendText: (message) => channel.send(message),
            })
          })
          channel.addEventListener('close', () => fail('Data channel closed'))
          channel.addEventListener('error', () => fail('Data channel error'))
          pc.addEventListener('connectionstatechange', () => {
            if (pc.connectionState === 'failed') fail('MAVLink peer connection failed')
          })
          channel.addEventListener('message', ({ data }: MessageEvent<unknown>) => {
            if (signal.aborted) return
            if (typeof data === 'string') controller.handleMessage(data)
            else if (data instanceof ArrayBuffer) {
              connectionExpiresAt = performance.now() + 15_000
              controller.handleMessage(new Uint8Array(data))
            }
          })
        }, signal)
      })().catch((error: unknown) => {
        fail(error instanceof Error ? error.message : 'Unable to open data channel')
      })
    }

    connect()
    const timer = window.setInterval(() => {
      if (attempt && performance.now() >= connectionExpiresAt) {
        reconnect(channelOpen ? 'No telemetry received' : 'Data channel opening timed out')
        return
      }
      const controller = flight.current
      if (!controller) return
      controller.tick()
      const next = controller.view()
      if (next.heartbeat) backoff = 1_000
      if (flight.current === controller) setView(next)
    }, mavlinkDriveRefreshMs)

    const pageHide = () => reconnect('Page disconnected')
    window.addEventListener('pagehide', pageHide)
    return () => {
      lifetime.abort()
      flight.current?.close()
      flight.current = null
      window.clearTimeout(retry)
      window.clearInterval(timer)
      window.removeEventListener('pagehide', pageHide)
    }
  }, [actor, deviceId, mavlinkAvailable, resolveIdToken])

  if (!videoAvailable && !mavlinkAvailable) return null
  return (
    <section className="card catalog-card catalog-card-detail" aria-label="Virtual quadcopter live view">
      <MavlinkControllerPanel
        linkStatus={mavlinkStatus}
        linkDetail={connectionError ?? flightError ?? view?.pending ??
          (videoAvailable && view?.supported === false ? 'Flight controls unavailable' : null)}
        showControllerToggle={videoAvailable && mavlinkAvailable}
        renderVideo={(controlOverlay) => videoAvailable ? (
          <VideoPanel channelName={`${deviceId}-board-video`} resolveIdToken={resolveIdToken}
            debugEnabled={debugEnabled} onFramePresented={() => { videoFrameAt.current = performance.now() }}
            overlay={<VideoOverlayRow controls={controlOverlay} debug={{ enabled: debugEnabled, toggle: onToggleDebug }} />}
            videoOnly />
        ) : (
          <div className="status-video-offline-surface" aria-label="Virtual quadcopter camera unavailable">
            <span className="status-video-placeholder">Camera unavailable</span>
            <VideoOverlayRow controls={controlOverlay} />
          </div>
        )}
        vehicleName="Virtual quadcopter"
        profile="quad"
        held={mavlinkAvailable && (view?.held ?? false)}
        canMove={mavlinkAvailable && videoAvailable && (view?.canMove ?? false)}
        owner={view?.owner}
        acquire={{ label: 'Acquire control', enabled: mavlinkAvailable && videoAvailable && (view?.canAcquire ?? false), run: async (signal) => {
          const controller = flight.current
          if (!controller || signal.aborted) return
          const abort = () => controller.close()
          signal.addEventListener('abort', abort, { once: true })
          try {
            await controller.acquire()
          } finally {
            signal.removeEventListener('abort', abort)
          }
        } }}
        release={{ enabled: view?.held ?? false, run: () => flight.current?.release() }}
        takeoff={{ label: 'Take off', enabled: mavlinkAvailable && videoAvailable && (view?.canTakeOff ?? false), run: () => flight.current?.takeOff() }}
        land={{ label: 'Land', enabled: mavlinkAvailable && videoAvailable && (view?.canLand ?? false), run: () => flight.current?.land() }}
        sendMotion={(sticks) => flight.current?.sendMotion(sticks)}
      />
      {debugEnabled && debugTarget && createPortal(
        <VirtualQuadMavlinkDiagnostics status={mavlinkStatus} connectionError={connectionError}
          view={mavlinkAvailable ? view : null} videoAvailable={videoAvailable} />,
        debugTarget,
      )}
    </section>
  )
}
