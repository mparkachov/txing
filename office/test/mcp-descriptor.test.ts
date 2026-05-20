import { describe, expect, test } from 'bun:test'
import {
  mcpWebRtcDataChannelLabel,
  parseMcpDescriptor,
  shouldAwaitInitialMcpDescriptor,
  selectPreferredMcpWebRtcTransport,
} from '../src/mcp-descriptor'

describe('MCP descriptor transport parsing', () => {
  test('treats active MQTT descriptors without transports as MQTT-only', () => {
    expect(
      parseMcpDescriptor({
        transport: 'mqtt-jsonrpc',
        control: {
          mode: 'active',
          activeTtlMs: 5000,
        },
      }),
    ).toEqual({
      activeTtlMs: 5000,
      transports: [
        {
          type: 'mqtt-jsonrpc',
          priority: 100,
        },
      ],
    })
  })

  test('rejects descriptors without active control metadata', () => {
    expect(
      parseMcpDescriptor({
        transport: 'mqtt-jsonrpc',
        control: {
          mode: 'lease',
          activeTtlMs: 5000,
        },
      }),
    ).toBeNull()
  })

  test('orders WebRTC data channel ahead of MQTT fallback', () => {
    const descriptor = parseMcpDescriptor({
      control: {
        mode: 'active',
        activeTtlMs: 5000,
      },
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

  test('keeps explicit WebRTC-only descriptors WebRTC-only', () => {
    const descriptor = parseMcpDescriptor({
      control: {
        mode: 'active',
        activeTtlMs: 5000,
      },
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
    ])
  })

  test('waits for the initial descriptor before choosing a fallback transport', () => {
    expect(shouldAwaitInitialMcpDescriptor(null, null)).toBe(true)
    expect(shouldAwaitInitialMcpDescriptor(null, true)).toBe(true)
    expect(shouldAwaitInitialMcpDescriptor(null, false)).toBe(false)
    expect(
      shouldAwaitInitialMcpDescriptor(
        parseMcpDescriptor({
          control: {
            mode: 'active',
            activeTtlMs: 5000,
          },
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
