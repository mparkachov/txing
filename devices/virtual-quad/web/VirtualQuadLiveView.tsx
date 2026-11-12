import { useEffect, useState } from 'react'
import { appConfig } from '../../../office/src/config'
import { mavlinkWebRtcDataChannelLabel } from '../../../office/src/mavlink-control'
import { startMavlinkDataChannel } from '../../../office/src/mavlink-session'
import { parseMavlinkFrame } from '../../../office/src/mavlink-wire'
import VideoPanel from '../../../office/src/VideoPanel'

type Position = { altitude: number; heading: number | null }
type Telemetry = { phase: 'connecting' | 'waiting' | 'live'; position: Position | null }

const readPosition = (payload: Uint8Array): Position | null => {
  if (payload.byteLength < 4 || payload.byteLength > 28) return null
  // MAVLink 2 can omit trailing zero bytes, including a north heading of zero.
  const padded = new Uint8Array(28)
  padded.set(payload)
  const fields = new DataView(padded.buffer)
  const heading = fields.getUint16(26, true)
  return {
    altitude: fields.getInt32(16, true) / 1000,
    heading: heading < 36_000 ? heading / 100 : null,
  }
}

function VirtualQuadTelemetry({
  deviceId, resolveIdToken,
}: {
  deviceId: string
  resolveIdToken: () => Promise<string>
}) {
  const [telemetry, setTelemetry] = useState<Telemetry>({ phase: 'connecting', position: null })

  useEffect(() => {
    const lifetime = new AbortController()
    let retry: number | undefined
    let backoff = 1000
    let connected = false
    let heartbeatAt = -Infinity
    let positionAt = -Infinity
    let position: Position | null = null

    const refresh = () => {
      const now = performance.now()
      setTelemetry({
        phase: connected ? (now - heartbeatAt < 3000 ? 'live' : 'waiting') : 'connecting',
        position: connected && now - heartbeatAt < 3000 && now - positionAt < 2000 ? position : null,
      })
    }
    const reconnect = () => {
      if (lifetime.signal.aborted || retry !== undefined) return
      connected = false
      heartbeatAt = positionAt = -Infinity
      refresh()
      retry = window.setTimeout(() => {
        retry = undefined
        connect()
      }, backoff)
      backoff = Math.min(backoff * 2, 10_000)
    }
    const connect = () => {
      void startMavlinkDataChannel({
        channelName: `${deviceId}-mavlink`,
        label: mavlinkWebRtcDataChannelLabel,
        region: appConfig.awsRegion,
        resolveIdToken,
        signal: lifetime.signal,
        onStateChange: (state) => {
          if (lifetime.signal.aborted) return
          if (state === 'open') {
            connected = true
            refresh()
          } else if (state === 'closed' || state === 'error') {
            reconnect()
          }
        },
        onMessage: (message) => {
          if (lifetime.signal.aborted || typeof message === 'string') return
          try {
            const frame = parseMavlinkFrame(message)
            if (frame.systemId !== 1 || frame.componentId !== 1) return
            if (frame.messageId === 0 && frame.payload.byteLength >= 9) {
              heartbeatAt = performance.now()
              backoff = 1000
            } else if (frame.messageId === 33) {
              position = readPosition(frame.payload)
              positionAt = performance.now()
            }
          } catch {
            // Malformed telemetry is never presented as fresh.
          }
        },
      }).catch(reconnect)
    }
    connect()
    const timer = window.setInterval(refresh, 250)
    return () => {
      lifetime.abort()
      window.clearTimeout(retry)
      window.clearInterval(timer)
    }
  }, [deviceId, resolveIdToken])

  return (
    <div className="status-video-overlay-metrics" aria-label="MAVLink telemetry">
      <span role="status">
        {telemetry.phase === 'live' ? 'MAVLink live'
          : telemetry.phase === 'waiting' ? 'Waiting for heartbeat' : 'Connecting MAVLink'}
      </span>
      {telemetry.position && (
        <>
          <span>Altitude {telemetry.position.altitude.toFixed(1)} m</span>
          {telemetry.position.heading !== null && <span>Heading {telemetry.position.heading.toFixed(1)}°</span>}
        </>
      )}
    </div>
  )
}

export function VirtualQuadLiveView({
  deviceId, videoAvailable, mavlinkAvailable, resolveIdToken, debugEnabled,
}: {
  deviceId: string
  videoAvailable: boolean
  mavlinkAvailable: boolean
  resolveIdToken: () => Promise<string>
  debugEnabled: boolean
}) {
  if (!videoAvailable && !mavlinkAvailable) return null
  return (
    <section className="card catalog-card catalog-card-detail" aria-label="Virtual quadcopter live view">
      {videoAvailable && (
        <VideoPanel
          channelName={`${deviceId}-board-video`}
          resolveIdToken={resolveIdToken}
          debugEnabled={debugEnabled}
          videoOnly
        />
      )}
      {mavlinkAvailable && <VirtualQuadTelemetry deviceId={deviceId} resolveIdToken={resolveIdToken} />}
    </section>
  )
}
