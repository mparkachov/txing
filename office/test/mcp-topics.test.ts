import { describe, expect, test } from 'bun:test'
import {
  buildMcpDescriptorTopic,
  buildMcpSessionC2sSubscription,
  buildMcpSessionC2sTopic,
  buildMcpSessionS2cTopic,
  buildMcpStatusTopic,
  buildMcpTopicRoot,
  parseMcpDescriptorOrStatusTopic,
} from '../src/mcp-topics'

describe('mcp topic helpers', () => {
  test('builds device-first mcp topics', () => {
    expect(buildMcpTopicRoot('unit-local')).toBe('txings/unit-local/mcp')
    expect(buildMcpDescriptorTopic('unit-local')).toBe('txings/unit-local/mcp/descriptor')
    expect(buildMcpStatusTopic('unit-local')).toBe('txings/unit-local/mcp/status')
    expect(buildMcpSessionC2sTopic('unit-local', 'session-a')).toBe(
      'txings/unit-local/mcp/session/session-a/c2s',
    )
    expect(buildMcpSessionS2cTopic('unit-local', 'session-a')).toBe(
      'txings/unit-local/mcp/session/session-a/s2c',
    )
    expect(buildMcpSessionC2sSubscription('unit-local')).toBe('txings/unit-local/mcp/session/+/c2s')
  })

  test('parses descriptor and status topics', () => {
    expect(parseMcpDescriptorOrStatusTopic('txings/unit-local/mcp/descriptor')).toEqual({
      deviceId: 'unit-local',
      kind: 'descriptor',
    })
    expect(parseMcpDescriptorOrStatusTopic('txings/unit-local/mcp/status')).toEqual({
      deviceId: 'unit-local',
      kind: 'status',
    })
    expect(parseMcpDescriptorOrStatusTopic('txings/unit-local/mcp/session/a/c2s')).toBeNull()
  })
})
