import { describe, expect, test } from 'bun:test'
import {
  getMcpActiveControlRenewDelayMs,
  getMcpActiveControlRenewBeforeMs,
  getMcpSteadyMotionHeartbeatIntervalMs,
  getSteadyMotionActiveControlState,
} from '../src/mcp-active-control'

describe('mcp active control helpers', () => {
  test('caps the background renew threshold to a practical window', () => {
    expect(getMcpActiveControlRenewBeforeMs(5_000)).toBe(1500)
    expect(getMcpActiveControlRenewBeforeMs(1_000)).toBe(400)
    expect(getMcpActiveControlRenewBeforeMs(200)).toBe(300)
  })

  test('schedules active-control renewal before local expiry', () => {
    expect(
      getMcpActiveControlRenewDelayMs({
        activeTtlMs: 5_000,
        expiresAtMs: 10_000,
        nowMs: 7_000,
      }),
    ).toBe(1500)
    expect(
      getMcpActiveControlRenewDelayMs({
        activeTtlMs: 5_000,
        expiresAtMs: 10_000,
        nowMs: 8_700,
      }),
    ).toBe(0)
  })

  test('uses a low-rate steady-motion heartbeat instead of per-frame MCP command spam', () => {
    expect(getMcpSteadyMotionHeartbeatIntervalMs(5_000)).toBe(2_000)
    expect(getMcpSteadyMotionHeartbeatIntervalMs(3_000)).toBe(1_200)
    expect(getMcpSteadyMotionHeartbeatIntervalMs(1_000)).toBe(1_000)
  })

  test('treats healthy active control as usable without forcing a synchronous refresh', () => {
    expect(
      getSteadyMotionActiveControlState({
        activeControl: {
          expiresAtMs: 10_000,
          activeTtlMs: 5_000,
        },
        knownActiveTtlMs: 5_000,
        nowMs: 7_000,
      }),
    ).toEqual({
      hasUsableActiveControl: true,
      shouldRefreshActiveControl: false,
    })
  })

  test('keeps near-expiry active control usable while requesting a background refresh', () => {
    expect(
      getSteadyMotionActiveControlState({
        activeControl: {
          expiresAtMs: 10_000,
          activeTtlMs: 5_000,
        },
        knownActiveTtlMs: 5_000,
        nowMs: 8_700,
      }),
    ).toEqual({
      hasUsableActiveControl: true,
      shouldRefreshActiveControl: true,
    })
  })

  test('forces reacquisition once local active control has expired', () => {
    expect(
      getSteadyMotionActiveControlState({
        activeControl: {
          expiresAtMs: 10_000,
          activeTtlMs: 5_000,
        },
        knownActiveTtlMs: 5_000,
        nowMs: 10_000,
      }),
    ).toEqual({
      hasUsableActiveControl: false,
      shouldRefreshActiveControl: false,
    })
  })
})
