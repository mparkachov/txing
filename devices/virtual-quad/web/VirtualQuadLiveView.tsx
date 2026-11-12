import { useEffect, useState } from 'react'
import { mavlinkWebRtcDataChannelLabel } from '../../../office/src/mavlink-control'
import { parseMavlinkFrame } from '../../../office/src/mavlink-wire'
import VideoPanel from '../../../office/src/VideoPanel'

type Position = { altitude: number; heading: number | null }
type Telemetry = {
  phase: 'connecting' | 'waiting' | 'live'
  position: Position | null
  connectionError: string | null
}

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
  const [telemetry, setTelemetry] = useState<Telemetry>({
    phase: 'connecting', position: null, connectionError: null,
  })

  useEffect(() => {
    const lifetime = new AbortController()
    let attempt: AbortController | undefined
    let connectionExpiresAt = 0
    let retry: number | undefined
    let backoff = 1000
    let connected = false
    let connectionError: string | null = null
    let heartbeatAt = -Infinity
    let positionAt = -Infinity
    let position: Position | null = null

    const refresh = () => {
      const now = performance.now()
      setTelemetry({
        phase: connected ? (now - heartbeatAt < 3000 ? 'live' : 'waiting') : 'connecting',
        position: connected && now - heartbeatAt < 3000 && now - positionAt < 2000 ? position : null,
        connectionError,
      })
    }
    const reconnect = (reason: string) => {
      if (lifetime.signal.aborted || retry !== undefined) return
      attempt?.abort()
      attempt = undefined
      connected = false
      connectionError = reason
      heartbeatAt = positionAt = -Infinity
      refresh()
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
          channel.addEventListener('open', () => {
            if (signal.aborted) return
            connected = true
            connectionExpiresAt = performance.now() + 15_000
            connectionError = null
            refresh()
          })
          channel.addEventListener('close', () => fail('Data channel closed'))
          channel.addEventListener('error', () => fail('Data channel error'))
          pc.addEventListener('connectionstatechange', () => {
            if (pc.connectionState === 'failed') fail('MAVLink peer connection failed')
          })
          channel.addEventListener('message', ({ data }: MessageEvent<unknown>) => {
            if (signal.aborted || !(data instanceof ArrayBuffer)) return
            connectionExpiresAt = performance.now() + 15_000
            try {
              const frame = parseMavlinkFrame(new Uint8Array(data))
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
          })
        }, signal)
      })().catch((error: unknown) => {
        fail(error instanceof Error ? error.message : 'Unable to open data channel')
      })
    }
    connect()
    const timer = window.setInterval(() => {
      if (attempt && performance.now() >= connectionExpiresAt) {
        reconnect(connected ? 'No telemetry received' : 'Data channel opening timed out')
      } else {
        refresh()
      }
    }, 250)
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
          : telemetry.phase === 'waiting' ? 'Waiting for heartbeat'
            : telemetry.connectionError ? `Reconnecting MAVLink · ${telemetry.connectionError}` : 'Connecting MAVLink'}
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
