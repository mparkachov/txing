export type McpActiveControlSnapshot = {
  expiresAtMs: number
  activeTtlMs: number
}

export type McpSteadyMotionActiveControlState = {
  hasUsableActiveControl: boolean
  shouldRefreshActiveControl: boolean
}

export const getMcpActiveControlRenewBeforeMs = (activeTtlMs: number): number =>
  Math.min(1500, Math.max(300, Math.round(activeTtlMs * 0.4)))

export const getMcpActiveControlRenewDelayMs = ({
  activeTtlMs,
  expiresAtMs,
  nowMs,
}: {
  activeTtlMs: number
  expiresAtMs: number
  nowMs: number
}): number =>
  Math.max(0, expiresAtMs - getMcpActiveControlRenewBeforeMs(activeTtlMs) - nowMs)

export const getMcpSteadyMotionHeartbeatIntervalMs = (activeTtlMs: number): number =>
  Math.min(2_000, Math.max(1_000, Math.round(activeTtlMs * 0.4)))

export const getSteadyMotionActiveControlState = ({
  activeControl,
  knownActiveTtlMs,
  nowMs,
}: {
  activeControl: McpActiveControlSnapshot | null
  knownActiveTtlMs: number
  nowMs: number
}): McpSteadyMotionActiveControlState => {
  if (!activeControl || nowMs >= activeControl.expiresAtMs) {
    return {
      hasUsableActiveControl: false,
      shouldRefreshActiveControl: false,
    }
  }

  const activeTtlMs = activeControl.activeTtlMs || knownActiveTtlMs
  const renewBeforeMs = getMcpActiveControlRenewBeforeMs(activeTtlMs)
  return {
    hasUsableActiveControl: true,
    shouldRefreshActiveControl: nowMs >= activeControl.expiresAtMs - renewBeforeMs,
  }
}
