import { describe, expect, test } from 'bun:test'
import { ChannelProtocol, type ResourceEndpointListItem } from '@aws-sdk/client-kinesis-video'
import type { IceServer } from '@aws-sdk/client-kinesis-video-signaling'
import {
  buildRtcIceServers,
  mapSignalingEndpoints,
  reduceViewerUiState,
} from '../src/video-session'

describe('video session helpers', () => {
  test('maps KVS signaling endpoints by protocol', () => {
    const endpoints = mapSignalingEndpoints([
      {
        Protocol: ChannelProtocol.HTTPS,
        ResourceEndpoint: 'https://example.com',
      },
      {
        Protocol: ChannelProtocol.WSS,
        ResourceEndpoint: 'wss://example.com',
      },
    ] satisfies ResourceEndpointListItem[])

    expect(endpoints.HTTPS).toBe('https://example.com')
    expect(endpoints.WSS).toBe('wss://example.com')
  })

  test('builds rtc ice servers with the KVS stun entry first', () => {
    const iceServers = buildRtcIceServers('eu-central-1', [
      {
        Uris: ['turn:example.com:443'],
        Username: 'user',
        Password: 'pass',
      },
    ] satisfies IceServer[])

    expect(iceServers[0]?.urls).toBe('stun:stun.kinesisvideo.eu-central-1.amazonaws.com:443')
    expect(iceServers[1]).toEqual({
      urls: ['turn:example.com:443'],
      username: 'user',
      credential: 'pass',
    })
  })

  test('reduces viewer ui state through connection and error transitions', () => {
    const connecting = reduceViewerUiState(
      { status: 'idle', error: '' },
      { type: 'connecting' },
    )
    const errored = reduceViewerUiState(connecting, {
      type: 'error',
      message: 'signaling closed',
    })
    const reset = reduceViewerUiState(errored, { type: 'reset' })

    expect(connecting).toEqual({ status: 'connecting', error: '' })
    expect(errored).toEqual({ status: 'error', error: 'signaling closed' })
    expect(reset).toEqual({ status: 'idle', error: '' })
  })
})
