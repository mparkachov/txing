const getMessage = (error: unknown): string => {
  if (error instanceof Error) {
    if (error.name && error.message) {
      return `${error.name}: ${error.message}`
    }
    return error.message
  }
  return ''
}

export const isInvalidMcpLeaseTokenError = (error: unknown): boolean =>
  getMessage(error).toLowerCase().includes('invalid lease token')

export const isMcpNoActiveControlLeaseError = (error: unknown): boolean =>
  getMessage(error).toLowerCase().includes('no active control lease')

export const isRecoverableMcpLeaseError = (error: unknown): boolean =>
  isInvalidMcpLeaseTokenError(error) || isMcpNoActiveControlLeaseError(error)

export const isMcpSessionNotInitializedError = (error: unknown): boolean =>
  getMessage(error).toLowerCase().includes('mcp session is not initialized')

export const isMcpServiceUnavailableError = (error: unknown): boolean =>
  getMessage(error).toLowerCase().includes('mcp service is currently unavailable')

export const isMcpRequestTimeoutError = (error: unknown): boolean =>
  getMessage(error).toLowerCase().includes('timed out waiting for mcp response')

export const isExpectedMcpTeardownError = (error: unknown): boolean =>
  isMcpSessionNotInitializedError(error) ||
  isMcpServiceUnavailableError(error) ||
  isMcpRequestTimeoutError(error)
