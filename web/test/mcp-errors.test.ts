import { describe, expect, test } from 'bun:test'
import {
  isExpectedMcpTeardownError,
  isMcpRequestTimeoutError,
  isMcpServiceUnavailableError,
  isMcpSessionNotInitializedError,
  isRecoverableMcpLeaseError,
} from '../src/mcp-errors'

describe('MCP error helpers', () => {
  test('treats invalid lease token and no active control lease as recoverable', () => {
    expect(isRecoverableMcpLeaseError(new Error('Invalid lease token'))).toBe(true)
    expect(isRecoverableMcpLeaseError(new Error('No active control lease'))).toBe(true)
    expect(isRecoverableMcpLeaseError(new Error('Internal MCP server error'))).toBe(false)
  })

  test('recognizes session not initialized errors', () => {
    expect(isMcpSessionNotInitializedError(new Error('MCP session is not initialized'))).toBe(true)
    expect(isMcpSessionNotInitializedError(new Error('No active control lease'))).toBe(false)
  })

  test('recognizes expected MCP teardown and unavailable errors', () => {
    expect(isMcpServiceUnavailableError(new Error('MCP service is currently unavailable'))).toBe(true)
    expect(
      isMcpRequestTimeoutError(new Error('Timed out waiting for MCP response to tools/call')),
    ).toBe(true)
    expect(
      isExpectedMcpTeardownError(new Error('Timed out waiting for MCP response to tools/call')),
    ).toBe(true)
    expect(isExpectedMcpTeardownError(new Error('MCP service is currently unavailable'))).toBe(
      true,
    )
    expect(isExpectedMcpTeardownError(new Error('MCP session is not initialized'))).toBe(true)
    expect(isExpectedMcpTeardownError(new Error('Internal MCP server error'))).toBe(false)
  })
})
