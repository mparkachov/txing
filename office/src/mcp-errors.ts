const getMessage = (error: unknown): string => {
  if (error instanceof Error) {
    if (error.name && error.message) {
      return `${error.name}: ${error.message}`
    }
    return error.message
  }
  return ''
}

export const isMcpNoActiveControlError = (error: unknown): boolean =>
  getMessage(error).toLowerCase().includes('no active control')

export const isMcpStaleActiveControlEpochError = (error: unknown): boolean =>
  getMessage(error).toLowerCase().includes('stale active control epoch')

export const isRecoverableMcpActiveControlError = (error: unknown): boolean =>
  isMcpNoActiveControlError(error) || isMcpStaleActiveControlEpochError(error)

export const isMcpSessionNotInitializedError = (error: unknown): boolean =>
  getMessage(error).toLowerCase().includes('mcp session is not initialized')

export const isMcpServiceUnavailableError = (error: unknown): boolean =>
  getMessage(error).toLowerCase().includes('mcp service is currently unavailable')

export const isMcpWebRtcResponseTimeoutError = (error: unknown): boolean =>
  getMessage(error).toLowerCase().includes('timed out waiting for mcp webrtc response')

export const isMcpRequestTimeoutError = (error: unknown): boolean =>
  getMessage(error).toLowerCase().includes('timed out waiting for mcp response') ||
  isMcpWebRtcResponseTimeoutError(error)

export const isRecoverableMcpDriveTransportError = (error: unknown): boolean =>
  isMcpWebRtcResponseTimeoutError(error)

export const isExpectedMcpTeardownError = (error: unknown): boolean =>
  isMcpSessionNotInitializedError(error) ||
  isMcpServiceUnavailableError(error) ||
  isMcpRequestTimeoutError(error)

type RobotStateTeardownContext = {
  error: unknown
  isDriveControlActive: boolean
  isShadowConnected: boolean
  pendingTargetRedcon: 1 | 2 | 3 | 4 | null
}

export const shouldSuppressRobotStateTeardownError = ({
  error,
  isDriveControlActive,
  isShadowConnected,
  pendingTargetRedcon,
}: RobotStateTeardownContext): boolean =>
  isExpectedMcpTeardownError(error) &&
  (!isDriveControlActive || !isShadowConnected || pendingTargetRedcon === 4)
