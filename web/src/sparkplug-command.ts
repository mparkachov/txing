import type { ShadowSession } from './shadow-api'

export const publishSparkplugRedconCommandWithAck = async (
  session: Pick<ShadowSession, 'publishRedconCommand'>,
  redcon: 1 | 2 | 3 | 4,
): Promise<void> => {
  await session.publishRedconCommand(redcon)
}
