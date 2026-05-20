const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value)

export const mergeShadowUpdate = (current: unknown, update: unknown): unknown => {
  if (!isRecord(update)) {
    return update
  }

  const next: Record<string, unknown> = isRecord(current) ? { ...current } : {}
  for (const [key, value] of Object.entries(update)) {
    if (value === null) {
      delete next[key]
      continue
    }

    const currentValue = next[key]
    if (isRecord(currentValue) && isRecord(value)) {
      next[key] = mergeShadowUpdate(currentValue, value)
      continue
    }

    if (isRecord(value)) {
      next[key] = mergeShadowUpdate(undefined, value)
      continue
    }

    next[key] = value
  }

  return next
}
