import { extractDesiredRedcon } from './app-model'
import type { ShadowSession } from './shadow-api'

export const defaultSparkplugRedconAckTimeoutMs = 3_000

export const publishSparkplugRedconCommandWithAck = async (
  session: Pick<ShadowSession, 'publishRedconCommand' | 'waitForSnapshot'>,
  redcon: 1 | 2 | 3 | 4,
  timeoutMs = defaultSparkplugRedconAckTimeoutMs,
): Promise<void> => {
  await session.publishRedconCommand(redcon)

  try {
    await session.waitForSnapshot(
      (shadow) => extractDesiredRedcon(shadow) === redcon,
      timeoutMs,
    )
  } catch (error) {
    const reason = error instanceof Error && error.message.trim() ? `: ${error.message}` : ''
    throw new Error(
      `Timed out waiting for rig to acknowledge Sparkplug DCMD.redcon=${redcon}${reason}`,
    )
  }
}
