import { describe, expect, test } from 'bun:test'
import {
  isExpectedMcpTeardownError,
  isMcpRequestTimeoutError,
  isMcpServiceUnavailableError,
  isMcpSessionNotInitializedError,
  isRecoverableMcpActiveControlError,
  shouldSuppressRobotStateTeardownError,
} from '../src/mcp-errors'

describe('MCP error helpers', () => {
  test('treats no-active and stale active epochs as recoverable', () => {
    expect(isRecoverableMcpActiveControlError(new Error('No active control'))).toBe(true)
    expect(isRecoverableMcpActiveControlError(new Error('Stale active control epoch'))).toBe(true)
    expect(isRecoverableMcpActiveControlError(new Error('Active control busy'))).toBe(false)
    expect(isRecoverableMcpActiveControlError(new Error('Internal MCP server error'))).toBe(false)
  })

  test('recognizes session not initialized errors', () => {
    expect(isMcpSessionNotInitializedError(new Error('MCP session is not initialized'))).toBe(true)
    expect(isMcpSessionNotInitializedError(new Error('No active control'))).toBe(false)
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

  test('suppresses robot state teardown errors while REDCON 4 teardown is in flight', () => {
    expect(
      shouldSuppressRobotStateTeardownError({
        error: new Error('Timed out waiting for MCP response to tools/call'),
        isDriveControlActive: true,
        isShadowConnected: true,
        pendingTargetRedcon: 4,
      }),
    ).toBe(true)
    expect(
      shouldSuppressRobotStateTeardownError({
        error: new Error('Timed out waiting for MCP response to tools/call'),
        isDriveControlActive: true,
        isShadowConnected: true,
        pendingTargetRedcon: null,
      }),
    ).toBe(false)
  })
})
