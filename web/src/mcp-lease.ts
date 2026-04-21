export type McpLeaseSnapshot = {
  expiresAtMs: number
  leaseTtlMs: number
}

export type McpSteadyMotionLeaseState = {
  hasUsableLease: boolean
  shouldRefreshLease: boolean
}

export const getMcpLeaseRenewBeforeMs = (leaseTtlMs: number): number =>
  Math.min(1500, Math.max(300, Math.round(leaseTtlMs * 0.4)))

export const getMcpSteadyMotionHeartbeatIntervalMs = (leaseTtlMs: number): number =>
  Math.min(2_000, Math.max(1_000, Math.round(leaseTtlMs * 0.4)))

export const getSteadyMotionLeaseState = ({
  lease,
  knownLeaseTtlMs,
  nowMs,
}: {
  lease: McpLeaseSnapshot | null
  knownLeaseTtlMs: number
  nowMs: number
}): McpSteadyMotionLeaseState => {
  if (!lease || nowMs >= lease.expiresAtMs) {
    return {
      hasUsableLease: false,
      shouldRefreshLease: false,
    }
  }

  const activeLeaseTtlMs = lease.leaseTtlMs || knownLeaseTtlMs
  const renewBeforeMs = getMcpLeaseRenewBeforeMs(activeLeaseTtlMs)
  return {
    hasUsableLease: true,
    shouldRefreshLease: nowMs >= lease.expiresAtMs - renewBeforeMs,
  }
}
