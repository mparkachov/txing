const defaultSessionSuffix = (): string => {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`
}

export const buildShadowMqttClientId = (
  identityId: string,
  sessionSuffix: string = defaultSessionSuffix(),
): string => `${identityId}-${sessionSuffix}`
