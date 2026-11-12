import { KinesisVideoClient } from '@aws-sdk/client-kinesis-video'
import { GetIceServerConfigCommand, KinesisVideoSignalingClient } from '@aws-sdk/client-kinesis-video-signaling'
import type { createCredentialProvider } from './aws-credentials'
import { appConfig } from './config'
import { loadKvsWebRtcBrowserSdk } from './kvs-webrtc-browser'
import {
  buildKinesisVideoClientConfig,
  buildKinesisVideoSignalingClientConfig,
  buildRtcIceServers,
  resolveKvsSignalingMetadata,
} from './video-session-runtime'

type ViewerPeer = { pc: RTCPeerConnection; close: () => void }

export const connectKvsViewer = async (
  channelName: string,
  credentials: ReturnType<typeof createCredentialProvider>,
  forceTurn: boolean,
  configure: (pc: RTCPeerConnection) => void,
  signal: AbortSignal,
): Promise<ViewerPeer> => {
  signal.throwIfAborted()
  const region = appConfig.awsRegion
  const kinesisVideoClient = new KinesisVideoClient(buildKinesisVideoClientConfig({ region, credentials }))
  const { channelArn, endpoints } = await resolveKvsSignalingMetadata({ channelName, region, kinesisVideoClient })
  signal.throwIfAborted()
  const clientId = crypto.randomUUID()
  const api = new KinesisVideoSignalingClient(buildKinesisVideoSignalingClientConfig({
    region,
    endpoint: endpoints.HTTPS,
    credentials,
  }))
  const config = await api.send(new GetIceServerConfigCommand({
    ChannelARN: channelArn,
    ClientId: clientId,
  }), { abortSignal: signal })
  const { Role, SignalingClient } = await loadKvsWebRtcBrowserSdk()
  const { accessKeyId, secretAccessKey, sessionToken } = await credentials()
  signal.throwIfAborted()
  const pc = new RTCPeerConnection({
    iceServers: buildRtcIceServers(region, config.IceServerList),
    iceTransportPolicy: forceTurn ? 'relay' : 'all',
  })
  const signaling = new SignalingClient({
    channelARN: channelArn, channelEndpoint: endpoints.WSS, role: Role.VIEWER,
    region, clientId, credentials: { accessKeyId, secretAccessKey, sessionToken },
  })
  let closed = false
  const close = () => {
    if (closed) return
    closed = true
    signal.removeEventListener('abort', close)
    signaling.removeAllListeners()
    signaling.close()
    pc.close()
  }
  const remoteCandidates: RTCIceCandidateInit[] = []
  const localCandidates: RTCIceCandidate[] = []
  let offered = false

  try {
    configure(pc)
    signal.addEventListener('abort', close, { once: true })
    pc.addEventListener('icecandidate', ({ candidate }) => {
      if (!candidate) return
      if (offered) signaling.sendIceCandidate(candidate)
      else localCandidates.push(candidate)
    })
    await new Promise<void>((resolve, reject) => {
      const timer = window.setTimeout(() => finish(new Error('KVS offer timed out')), 20_000)
      const abort = () => finish(new Error('Viewer cancelled'))
      const finish = (error?: Error) => {
        window.clearTimeout(timer)
        signal.removeEventListener('abort', abort)
        if (error) reject(error)
        else resolve()
      }
      signal.addEventListener('abort', abort, { once: true })
      signaling.on('open', () => {
        void pc.createOffer().then((offer) => pc.setLocalDescription(offer)).then(() => {
          if (!pc.localDescription || signal.aborted) throw new Error('Viewer offer unavailable')
          signaling.sendSdpOffer(pc.localDescription)
          offered = true
          for (const candidate of localCandidates.splice(0)) signaling.sendIceCandidate(candidate)
        }).catch(() => finish(new Error('Viewer offer failed')))
      })
      signaling.on('sdpAnswer', (answer) => {
        void pc.setRemoteDescription(answer).then(async () => {
          for (const candidate of remoteCandidates.splice(0)) {
            await pc.addIceCandidate(candidate).catch(() => undefined)
          }
          finish()
        }).catch(() => finish(new Error('Viewer answer failed')))
      })
      signaling.on('iceCandidate', (candidate) => {
        if (!pc.remoteDescription) remoteCandidates.push(candidate)
        else void pc.addIceCandidate(candidate).catch(() => undefined)
      })
      signaling.on('error', () => finish(new Error('KVS signaling error')))
      // After the answer, signaling can idle out while the established media continues.
      signaling.on('close', () => finish(new Error('KVS signaling closed before answer')))
      try { signaling.open() } catch { finish(new Error('Unable to open KVS signaling')) }
    })
    return { pc, close }
  } catch (error) {
    close()
    throw error
  }
}
