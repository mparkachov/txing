import { describe, expect, test } from 'bun:test'
import { getMcpLeaseRenewBeforeMs, getSteadyMotionLeaseState } from '../src/mcp-lease'

describe('mcp lease helpers', () => {
  test('caps the background renew threshold to a practical window', () => {
    expect(getMcpLeaseRenewBeforeMs(5_000)).toBe(1500)
    expect(getMcpLeaseRenewBeforeMs(1_000)).toBe(400)
    expect(getMcpLeaseRenewBeforeMs(200)).toBe(300)
  })

  test('treats a healthy active lease as usable without forcing a synchronous refresh', () => {
    expect(
      getSteadyMotionLeaseState({
        lease: {
          expiresAtMs: 10_000,
          leaseTtlMs: 5_000,
        },
        knownLeaseTtlMs: 5_000,
        nowMs: 7_000,
      }),
    ).toEqual({
      hasUsableLease: true,
      shouldRefreshLease: false,
    })
  })

  test('keeps a near-expiry lease usable for motion while requesting a background refresh', () => {
    expect(
      getSteadyMotionLeaseState({
        lease: {
          expiresAtMs: 10_000,
          leaseTtlMs: 5_000,
        },
        knownLeaseTtlMs: 5_000,
        nowMs: 8_700,
      }),
    ).toEqual({
      hasUsableLease: true,
      shouldRefreshLease: true,
    })
  })

  test('forces reacquisition once the local lease has expired', () => {
    expect(
      getSteadyMotionLeaseState({
        lease: {
          expiresAtMs: 10_000,
          leaseTtlMs: 5_000,
        },
        knownLeaseTtlMs: 5_000,
        nowMs: 10_000,
      }),
    ).toEqual({
      hasUsableLease: false,
      shouldRefreshLease: false,
    })
  })
})
