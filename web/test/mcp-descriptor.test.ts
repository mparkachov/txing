import { describe, expect, test } from 'bun:test'
import {
  mcpWebRtcDataChannelLabel,
  parseMcpDescriptor,
  shouldAwaitInitialMcpDescriptor,
  selectPreferredMcpWebRtcTransport,
} from '../src/mcp-descriptor'

describe('MCP descriptor transport parsing', () => {
  test('treats legacy descriptors without transports as MQTT-only', () => {
    expect(
      parseMcpDescriptor({
        transport: 'mqtt-jsonrpc',
        leaseTtlMs: 5000,
      }),
    ).toEqual({
      leaseTtlMs: 5000,
      transports: [
        {
          type: 'mqtt-jsonrpc',
          priority: 100,
        },
      ],
    })
  })

  test('orders WebRTC data channel ahead of MQTT fallback', () => {
    const descriptor = parseMcpDescriptor({
      leaseTtlMs: 5000,
      transports: [
        {
          type: 'mqtt-jsonrpc',
          priority: 100,
        },
        {
          type: 'webrtc-datachannel',
          priority: 10,
          signaling: 'aws-kvs',
          channelName: 'unit-local-board-video',
          region: 'eu-central-1',
          label: 'txing.mcp.v1',
        },
      ],
    })

    expect(descriptor?.transports.map((transport) => transport.type)).toEqual([
      'webrtc-datachannel',
      'mqtt-jsonrpc',
    ])
    expect(selectPreferredMcpWebRtcTransport(descriptor)).toEqual({
      type: 'webrtc-datachannel',
      priority: 10,
      signaling: 'aws-kvs',
      channelName: 'unit-local-board-video',
      region: 'eu-central-1',
      label: 'txing.mcp.v1',
    })
  })

  test('keeps MQTT fallback even when descriptor omits it', () => {
    const descriptor = parseMcpDescriptor({
      leaseTtlMs: 5000,
      transports: [
        {
          type: 'webrtc-datachannel',
          priority: 10,
          signaling: 'aws-kvs',
          channelName: 'unit-local-board-video',
          region: 'eu-central-1',
        },
      ],
    })

    expect(descriptor?.transports).toEqual([
      {
        type: 'webrtc-datachannel',
        priority: 10,
        signaling: 'aws-kvs',
        channelName: 'unit-local-board-video',
        region: 'eu-central-1',
        label: mcpWebRtcDataChannelLabel,
      },
      {
        type: 'mqtt-jsonrpc',
        priority: 100,
      },
    ])
  })

  test('waits for the initial descriptor before choosing a fallback transport', () => {
    expect(shouldAwaitInitialMcpDescriptor(null, null)).toBe(true)
    expect(shouldAwaitInitialMcpDescriptor(null, true)).toBe(true)
    expect(shouldAwaitInitialMcpDescriptor(null, false)).toBe(false)
    expect(
      shouldAwaitInitialMcpDescriptor(
        parseMcpDescriptor({
          leaseTtlMs: 5000,
          transports: [
            {
              type: 'webrtc-datachannel',
              priority: 10,
              signaling: 'aws-kvs',
              channelName: 'unit-local-board-video',
              region: 'eu-central-1',
            },
          ],
        }),
        true,
      ),
    ).toBe(false)
  })
})
