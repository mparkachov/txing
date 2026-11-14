import { useEffect, useEffectEvent, useRef, useState, type RefObject } from 'react'
import { mavlinkDriveRefreshMs, mavlinkWebRtcDataChannelLabel } from '../../../office/src/mavlink-control'
import { createCredentialProvider } from '../../../office/src/aws-credentials'
import VideoPanel from '../../../office/src/VideoPanel'
import MavlinkControllerPanel from '../../../office/src/MavlinkControllerPanel'
import { VirtualQuadFlight, type QuadFlightView } from './virtual-quad-flight'
import { readQuadMavlinkStatus, type QuadMavlinkStatus } from './virtual-quad-media-status'

const landedLabel: Record<number, string> = { 1: 'Landed', 2: 'Airborne', 3: 'Taking off', 4: 'Landing' }

function VirtualQuadTelemetry({
  deviceId, actor, resolveIdToken, videoAvailable, videoFrameAt, onMavlinkStatus,
}: {
  deviceId: string
  actor: string
  resolveIdToken: () => Promise<string>
  videoAvailable: boolean
  videoFrameAt: RefObject<number>
  onMavlinkStatus: (status: QuadMavlinkStatus) => void
}) {
  const flight = useRef<VirtualQuadFlight | null>(null)
  const [view, setView] = useState<QuadFlightView | null>(null)
  const [connectionError, setConnectionError] = useState<string | null>(null)
  const readVideoTime = useEffectEvent(() => videoAvailable ? videoFrameAt.current : -Infinity)
  const mavlinkStatus = readQuadMavlinkStatus(view, connectionError)

  useEffect(() => {
    onMavlinkStatus(mavlinkStatus)
  }, [mavlinkStatus, onMavlinkStatus])
  useEffect(() => () => onMavlinkStatus('inactive'), [onMavlinkStatus])

  useEffect(() => {
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
  }, [actor, deviceId, resolveIdToken])

  return (
    <div className="virtual-quad-flight-controls" aria-label="Virtual quadcopter flight controls">
      <div className="status-video-overlay-metrics" aria-label="MAVLink telemetry">
        <span role="status">
          {mavlinkStatus === 'live' ? 'MAVLink live' : mavlinkStatus === 'waiting for heartbeat' ? 'Waiting for heartbeat'
            : mavlinkStatus === 'reconnecting' ? `Reconnecting MAVLink · ${connectionError}` : 'Connecting MAVLink'}
        </span>
        {videoAvailable && <span>{view?.camera ? 'Camera live' : 'Waiting for camera'}</span>}
        {view?.mode && <span>Mode {view.mode}</span>}
        {view?.armed !== null && view?.armed !== undefined && <span>{view.armed ? 'Armed' : 'Disarmed'}</span>}
        {view?.landed && <span>{landedLabel[view.landed]}</span>}
        {view?.position && (
          <>
            <span>Altitude {view.position.altitude.toFixed(1)} m</span>
            {view.position.heading !== null && <span>Heading {view.position.heading.toFixed(1)}°</span>}
            <span>Speed {view.position.speed.toFixed(1)} m/s</span>
          </>
        )}
      </div>
      {videoAvailable && view?.supported === false && <span>Flight controls unavailable</span>}
      {videoAvailable && (
        <MavlinkControllerPanel
          vehicleName="Virtual quadcopter"
          profile="quad"
          held={view?.held ?? false}
          canMove={view?.canMove ?? false}
          owner={view?.owner}
          acquire={{ label: 'Acquire control', enabled: view?.canAcquire ?? false, run: async (signal) => {
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
          takeoff={{ label: 'Take off', enabled: view?.canTakeOff ?? false, run: () => flight.current?.takeOff() }}
          land={{ label: 'Land', enabled: view?.canLand ?? false, run: () => flight.current?.land() }}
          sendMotion={(sticks) => flight.current?.sendMotion(sticks)}
        />
      )}
      {view?.pending && <span role="status">{view.pending}</span>}
      {view?.error && <span role="alert">{view.error}</span>}
    </div>
  )
}

export function VirtualQuadLiveView({
  deviceId, actor, videoAvailable, mavlinkAvailable, resolveIdToken, debugEnabled, onMavlinkStatus,
}: {
  deviceId: string
  actor: string
  videoAvailable: boolean
  mavlinkAvailable: boolean
  resolveIdToken: () => Promise<string>
  debugEnabled: boolean
  onMavlinkStatus: (status: QuadMavlinkStatus) => void
}) {
  const videoFrameAt = useRef(-Infinity)
  useEffect(() => {
    if (!videoAvailable) videoFrameAt.current = -Infinity
  }, [videoAvailable])
  if (!videoAvailable && !mavlinkAvailable) return null
  return (
    <section className="card catalog-card catalog-card-detail" aria-label="Virtual quadcopter live view">
      {videoAvailable && (
        <VideoPanel channelName={`${deviceId}-board-video`} resolveIdToken={resolveIdToken}
          debugEnabled={debugEnabled} onFramePresented={() => { videoFrameAt.current = performance.now() }} videoOnly />
      )}
      {mavlinkAvailable && (
        <VirtualQuadTelemetry deviceId={deviceId} actor={actor} resolveIdToken={resolveIdToken}
          videoAvailable={videoAvailable} videoFrameAt={videoFrameAt} onMavlinkStatus={onMavlinkStatus} />
      )}
    </section>
  )
}
