import { useEffect, useEffectEvent, useRef, useState, type RefObject } from 'react'
import { mavlinkDriveRefreshMs, mavlinkWebRtcDataChannelLabel } from '../../../office/src/mavlink-control'
import VideoPanel from '../../../office/src/VideoPanel'
import { VirtualQuadFlight, type Direction, type QuadFlightView } from './virtual-quad-flight'

const directionButtons: { direction: Direction; key: string; label: string }[] = [
  { direction: 'forward', key: 'w', label: 'Forward' },
  { direction: 'back', key: 's', label: 'Back' },
  { direction: 'left', key: 'a', label: 'Left' },
  { direction: 'right', key: 'd', label: 'Right' },
  { direction: 'up', key: 'r', label: 'Climb' },
  { direction: 'down', key: 'f', label: 'Descend' },
  { direction: 'yawLeft', key: 'q', label: 'Yaw left' },
  { direction: 'yawRight', key: 'e', label: 'Yaw right' },
]
const directionByKey = new Map(directionButtons.map(({ key, direction }) => [key, direction]))
const landedLabel: Record<number, string> = { 1: 'Landed', 2: 'Airborne', 3: 'Taking off', 4: 'Landing' }

function VirtualQuadTelemetry({
  deviceId, actor, resolveIdToken, videoAvailable, videoFrameAt,
}: {
  deviceId: string
  actor: string
  resolveIdToken: () => Promise<string>
  videoAvailable: boolean
  videoFrameAt: RefObject<number>
}) {
  const flight = useRef<VirtualQuadFlight | null>(null)
  const [view, setView] = useState<QuadFlightView | null>(null)
  const [connectionError, setConnectionError] = useState<string | null>(null)
  const readVideoTime = useEffectEvent(() => videoAvailable ? videoFrameAt.current : -Infinity)

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
        const [{ connectKvsViewer }, { createCredentialProvider }, idToken] = await Promise.all([
          import('../../../office/src/kvs-viewer-peer'),
          import('../../../office/src/aws-credentials'),
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

    const keyDown = (event: KeyboardEvent) => {
      const key = event.key.toLowerCase()
      const direction = directionByKey.get(key)
      if (!direction || event.ctrlKey || event.altKey || event.metaKey ||
        (event.target instanceof HTMLElement && event.target.closest('input, textarea, select, [contenteditable], [role="dialog"]')) ||
        !flight.current?.view().canMove) return
      event.preventDefault()
      flight.current.setInput(key, direction)
    }
    const keyUp = (event: KeyboardEvent) => flight.current?.releaseInput(event.key.toLowerCase())
    const clearInput = () => flight.current?.clearInput()
    const pageHide = () => reconnect('Page disconnected')
    window.addEventListener('keydown', keyDown)
    window.addEventListener('keyup', keyUp)
    window.addEventListener('blur', clearInput)
    window.addEventListener('pagehide', pageHide)
    document.addEventListener('visibilitychange', clearInput)
    return () => {
      lifetime.abort()
      flight.current?.close()
      flight.current = null
      window.clearTimeout(retry)
      window.clearInterval(timer)
      window.removeEventListener('keydown', keyDown)
      window.removeEventListener('keyup', keyUp)
      window.removeEventListener('blur', clearInput)
      window.removeEventListener('pagehide', pageHide)
      document.removeEventListener('visibilitychange', clearInput)
    }
  }, [actor, deviceId, resolveIdToken])

  return (
    <div className="virtual-quad-flight-controls" aria-label="Virtual quadcopter flight controls">
      <div className="status-video-overlay-metrics" aria-label="MAVLink telemetry">
        <span role="status">
          {view?.heartbeat ? 'MAVLink live' : view?.connected ? 'Waiting for heartbeat'
            : connectionError ? `Reconnecting MAVLink · ${connectionError}` : 'Connecting MAVLink'}
        </span>
        <span>{view?.camera ? 'Camera live' : 'Waiting for camera'}</span>
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
      <div className="virtual-quad-flight-actions">
        <span>{view?.held ? 'Control' : 'View only'}</span>
        {view?.owner && <span>Controller {view.owner}</span>}
        {view?.supported === false && <span>Flight controls unavailable</span>}
        {view?.supported && (
          view.held
            ? <button type="button" onClick={() => { void flight.current?.release() }}>Release control</button>
            : <button type="button" disabled={!view.canAcquire} onClick={() => { void flight.current?.acquire() }}>Acquire control</button>
        )}
        {view?.held && (
          <>
            <button type="button" disabled={!view.canTakeOff} onClick={() => { void flight.current?.takeOff() }}>Take off</button>
            <button type="button" disabled={!view.canLand} onClick={() => { void flight.current?.land() }}>Land</button>
          </>
        )}
        {view?.pending && <span role="status">{view.pending}</span>}
      </div>
      {view?.held && <div className="virtual-quad-flight-actions" aria-label="Movement">
        {directionButtons.map(({ direction, key, label }) => (
          <button key={direction} type="button" disabled={!view.canMove} aria-keyshortcuts={key.toUpperCase()}
            onPointerDown={(event) => {
              if (event.button !== 0) return
              event.currentTarget.setPointerCapture(event.pointerId)
              flight.current?.setInput(`pointer-${event.pointerId}`, direction)
            }}
            onPointerUp={(event) => flight.current?.releaseInput(`pointer-${event.pointerId}`)}
            onPointerCancel={(event) => flight.current?.releaseInput(`pointer-${event.pointerId}`)}
            onLostPointerCapture={(event) => flight.current?.releaseInput(`pointer-${event.pointerId}`)}
            onKeyDown={(event) => {
              if (event.key === ' ' || event.key === 'Enter') {
                event.preventDefault()
                flight.current?.setInput('movement-button', direction)
              }
            }}
            onKeyUp={(event) => {
              if (event.key === ' ' || event.key === 'Enter') flight.current?.releaseInput('movement-button')
            }}
            onBlur={() => flight.current?.releaseInput('movement-button')}
          >{label} <kbd>{key.toUpperCase()}</kbd></button>
        ))}
      </div>}
      {view?.error && <span role="alert">{view.error}</span>}
    </div>
  )
}

export function VirtualQuadLiveView({
  deviceId, actor, videoAvailable, mavlinkAvailable, resolveIdToken, debugEnabled,
}: {
  deviceId: string
  actor: string
  videoAvailable: boolean
  mavlinkAvailable: boolean
  resolveIdToken: () => Promise<string>
  debugEnabled: boolean
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
          videoAvailable={videoAvailable} videoFrameAt={videoFrameAt} />
      )}
    </section>
  )
}
