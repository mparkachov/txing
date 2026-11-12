import { refreshTokensIfNeeded } from '../auth'
import { createCredentialProvider } from '../aws-credentials'
import { connectKvsViewer } from '../kvs-viewer-peer'

type CandidateTypes = { local: string | null; remote: string | null }
type Sample = {
  at: string
  join: number
  seconds: number
  forceTurn: boolean
  video: CandidateTypes
  mavlink: CandidateTypes
  decodedFrames: number
  decodedFps: number
  mavlinkFrames: number
  heartbeats: number
  invalidMessages: number
  width: number
  height: number
  poseToDisplayMs: number[]
}
type StatsEntry = {
  type: string
  kind?: string
  mediaType?: string
  framesDecoded?: number
  selectedCandidatePairId?: string
  localCandidateId?: string
  remoteCandidateId?: string
  candidateType?: string
}

const readStats = async (pc: RTCPeerConnection) => {
  const stats = await pc.getStats()
  let frames = 0
  const candidates: CandidateTypes = { local: null, remote: null }
  stats.forEach((entry: StatsEntry) => {
    if (entry.type === 'inbound-rtp' && (entry.kind ?? entry.mediaType) === 'video') {
      frames += entry.framesDecoded ?? 0
    }
    if (entry.type !== 'transport' || !entry.selectedCandidatePairId) return
    const pair: StatsEntry | undefined = stats.get(entry.selectedCandidatePairId)
    candidates.local = stats.get(pair?.localCandidateId ?? '')?.candidateType ?? null
    candidates.remote = stats.get(pair?.remoteCandidateId ?? '')?.candidateType ?? null
  })
  return { frames, candidates }
}

const configurePage = () => {
  const form = document.querySelector<HTMLFormElement>('form')!
  const input = (id: string) => document.querySelector<HTMLInputElement>(id)!
  const button = (id: string) => document.querySelector<HTMLButtonElement>(id)!
  const preview = document.querySelector<HTMLVideoElement>('#preview')!
  const status = document.querySelector<HTMLElement>('#status')!
  const display = document.querySelector<HTMLElement>('#samples')!
  const query = new URLSearchParams(window.location.search)
  const device = query.get('device')
  if (device && /^virtual-quad-[a-z0-9]+$/.test(device)) {
    input('#video-channel').value = `${device}-board-video`
    input('#mavlink-channel').value = `${device}-mavlink`
  }
  input('#rtp-epoch').value = query.get('rtpEpochMs') ?? ''
  input('#relay').checked = query.get('relay') === '1'
  let current: AbortController | undefined
  let joins = 0
  const samples: Sample[] = []
  const events: { at: string; join: number; event: string; forceTurn?: boolean }[] = []
  const event = (join: number, name: string, forceTurn?: boolean) =>
    events.push({ at: new Date().toISOString(), join, event: name, forceTurn })

  const leave = () => {
    current?.abort()
    current = undefined
    preview.srcObject = null
    button('#join').disabled = false
    button('#leave').disabled = true
  }
  window.addEventListener('pagehide', leave)
  button('#leave').addEventListener('click', () => {
    event(joins, 'leave')
    leave()
    status.textContent = 'Left'
  })
  button('#save').addEventListener('click', () => {
    const blob = new Blob([JSON.stringify({ events, samples }, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = 'virtual-quad-qualification.json'
    link.click()
    window.setTimeout(() => URL.revokeObjectURL(url), 1000)
  })
  form.addEventListener('submit', (submit) => {
    submit.preventDefault()
    leave()
    const abort = new AbortController()
    current = abort
    const { signal } = abort
    const join = ++joins
    const forceTurn = input('#relay').checked
    const videoChannel = input('#video-channel').value
    const mavlinkChannel = input('#mavlink-channel').value
    const rtpEpochMs = input('#rtp-epoch').valueAsNumber
    event(join, 'join', forceTurn)
    status.textContent = 'Connecting…'
    button('#join').disabled = true
    button('#leave').disabled = false
    void (async () => {
      const tokens = await refreshTokensIfNeeded()
      if (!tokens) throw new Error('Sign in through Office first')
      const credentials = createCredentialProvider(tokens.idToken)
      let mavlinkFrames = 0
      let heartbeats = 0
      let invalidMessages = 0
      let poseToDisplayMs: number[] = []
      const [video, data] = await Promise.all([
        connectKvsViewer(videoChannel, credentials, forceTurn, (pc) => {
          pc.addTransceiver('video', { direction: 'recvonly' })
          pc.addEventListener('track', ({ track }) => {
            preview.srcObject = new MediaStream([track])
          })
        }, signal),
        connectKvsViewer(mavlinkChannel, credentials, forceTurn, (pc) => {
          const channel = pc.createDataChannel('txing.mavlink.v1', { ordered: true })
          channel.binaryType = 'arraybuffer'
          channel.addEventListener('open', () => event(join, 'data-open'))
          channel.addEventListener('message', ({ data }: MessageEvent<unknown>) => {
            if (data instanceof ArrayBuffer) {
              const bytes = new Uint8Array(data)
              if (bytes.length >= 12 && bytes[0] === 0xfd && (bytes[2] & ~1) === 0 &&
                bytes.length === 12 + bytes[1] + ((bytes[2] & 1) ? 13 : 0)) {
                ++mavlinkFrames
                if (bytes[5] === 1 && bytes[6] === 1 && bytes[7] === 0 && bytes[8] === 0 && bytes[9] === 0) {
                  ++heartbeats
                }
                return
              }
            }
            ++invalidMessages
          })
        }, signal),
      ])
      signal.throwIfAborted()
      if (Number.isFinite(rtpEpochMs) && typeof preview.requestVideoFrameCallback === 'function') {
        const recordFrame: VideoFrameRequestCallback = (_now, frame) => {
          if (signal.aborted) return
          if (frame.rtpTimestamp !== undefined) {
            // The pinned KVS sender uses 90 kHz H.264 RTP with zero random
            // offset. The native log maps tick zero to the first pose's UTC time.
            const poseTime = rtpEpochMs + frame.rtpTimestamp / 90
            const displayTime = performance.timeOrigin + frame.expectedDisplayTime
            poseToDisplayMs.push(Math.round((displayTime - poseTime) * 10) / 10)
          }
          callback = preview.requestVideoFrameCallback(recordFrame)
        }
        let callback = preview.requestVideoFrameCallback(recordFrame)
        signal.addEventListener('abort', () => preview.cancelVideoFrameCallback(callback), { once: true })
      }
      event(join, 'answers-received')
      status.textContent = 'Connected to signaling; sampling decoded media and telemetry'
      let previousAt = performance.now()
      let previousDecoded = (await readStats(video.pc)).frames
      let timer = 0
      signal.addEventListener('abort', () => window.clearTimeout(timer), { once: true })
      const sample = async () => {
        if (signal.aborted) return
        const [v, d] = await Promise.all([readStats(video.pc), readStats(data.pc)])
        if (signal.aborted) return
        const now = performance.now()
        const seconds = (now - previousAt) / 1000
        const decodedFrames = Math.max(0, v.frames - previousDecoded)
        previousDecoded = v.frames
        previousAt = now
        const row = {
          at: new Date().toISOString(), join, forceTurn, seconds,
          video: v.candidates, mavlink: d.candidates, decodedFrames,
          decodedFps: decodedFrames / seconds, mavlinkFrames, heartbeats, invalidMessages,
          width: preview.videoWidth, height: preview.videoHeight, poseToDisplayMs,
        }
        samples.push(row)
        mavlinkFrames = heartbeats = invalidMessages = 0
        poseToDisplayMs = []
        const recent = samples.slice(-6).map(({ poseToDisplayMs, ...sample }) => {
          const sorted = [...poseToDisplayMs].sort((a, b) => a - b)
          return { ...sample, measuredFrames: sorted.length, poseToDisplayP95Ms: sorted[Math.ceil(sorted.length * 0.95) - 1] ?? null }
        })
        display.textContent = JSON.stringify(recent, null, 2)
        schedule()
      }
      const schedule = () => {
        timer = window.setTimeout(() => {
          void sample().catch(() => {
            if (signal.aborted) return
            event(join, 'stats-failed')
            leave()
            status.textContent = 'Unable to read WebRTC statistics'
          })
        }, 5000)
      }
      if (!signal.aborted) schedule()
    })().catch((error: unknown) => {
      if (signal.aborted) return
      event(join, 'join-failed')
      leave()
      status.textContent = error instanceof Error ? error.message : 'Viewer failed'
    })
  })
}

if (import.meta.env.DEV) configurePage()
