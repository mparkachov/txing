import { beforeEach, describe, expect, test } from 'bun:test'
import { ChannelProtocol, type ResourceEndpointListItem } from '@aws-sdk/client-kinesis-video'
import type { IceServer } from '@aws-sdk/client-kinesis-video-signaling'
import {
  buildRtcIceServers,
  mapSignalingEndpoints,
  reduceViewerUiState,
} from '../src/video-session'
import {
  clearKvsSignalingMetadataCacheForTests,
  resolveCachedKvsSignalingMetadata,
  type KvsSignalingMetadata,
} from '../src/video-session-runtime'

beforeEach(() => {
  clearKvsSignalingMetadataCacheForTests()
})

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

  test('deduplicates concurrent KVS signaling metadata loads and reuses the cached result', async () => {
    let calls = 0
    let resolveLoad: ((metadata: KvsSignalingMetadata) => void) | null = null
    const metadata: KvsSignalingMetadata = {
      channelArn: 'arn:aws:kinesisvideo:eu-central-1:123456789012:channel/unit-a-board-video/1',
      endpoints: {
        HTTPS: 'https://kvs.example.com',
        WSS: 'wss://kvs.example.com',
      },
    }

    const loadMetadata = (): Promise<KvsSignalingMetadata> => {
      calls += 1
      return new Promise((resolve) => {
        resolveLoad = resolve
      })
    }

    const firstRequest = resolveCachedKvsSignalingMetadata({
      channelName: 'unit-a-board-video',
      region: 'eu-central-1',
      loadMetadata,
      nowMs: () => 1_000,
    })
    const secondRequest = resolveCachedKvsSignalingMetadata({
      channelName: 'unit-a-board-video',
      region: 'eu-central-1',
      loadMetadata,
      nowMs: () => 1_000,
    })

    await Promise.resolve()
    expect(calls).toBe(1)
    resolveLoad?.(metadata)
    expect(await firstRequest).toBe(metadata)
    expect(await secondRequest).toBe(metadata)
    expect(
      await resolveCachedKvsSignalingMetadata({
        channelName: 'unit-a-board-video',
        region: 'eu-central-1',
        loadMetadata,
        nowMs: () => 2_000,
      }),
    ).toBe(metadata)
    expect(calls).toBe(1)
  })

  test('cools down failed KVS signaling metadata loads before retrying AWS', async () => {
    let calls = 0
    let nowMs = 1_000
    const rateLimitError = new Error('Rate exceeded')
    const metadata: KvsSignalingMetadata = {
      channelArn: 'arn:aws:kinesisvideo:eu-central-1:123456789012:channel/unit-a-board-video/1',
      endpoints: {
        HTTPS: 'https://kvs.example.com',
        WSS: 'wss://kvs.example.com',
      },
    }

    const loadMetadata = async (): Promise<KvsSignalingMetadata> => {
      calls += 1
      if (calls === 1) {
        throw rateLimitError
      }
      return metadata
    }

    await expect(
      resolveCachedKvsSignalingMetadata({
        channelName: 'unit-a-board-video',
        region: 'eu-central-1',
        loadMetadata,
        nowMs: () => nowMs,
      }),
    ).rejects.toThrow('Rate exceeded')
    await expect(
      resolveCachedKvsSignalingMetadata({
        channelName: 'unit-a-board-video',
        region: 'eu-central-1',
        loadMetadata,
        nowMs: () => nowMs + 10_000,
      }),
    ).rejects.toThrow('Rate exceeded')
    expect(calls).toBe(1)

    nowMs += 60_001
    expect(
      await resolveCachedKvsSignalingMetadata({
        channelName: 'unit-a-board-video',
        region: 'eu-central-1',
        loadMetadata,
        nowMs: () => nowMs,
      }),
    ).toBe(metadata)
    expect(calls).toBe(2)
  })
})
