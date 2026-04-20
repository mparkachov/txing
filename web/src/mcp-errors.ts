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
