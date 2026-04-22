import { describe, expect, test } from 'bun:test'
import { publishSparkplugRedconCommandWithAck } from '../src/sparkplug-command'

describe('sparkplug command ack helper', () => {
  test('publishes the sparkplug command without waiting for shadow desired echo', async () => {
    const calls: Array<string> = []
    const session = {
      async publishRedconCommand(redcon: number): Promise<void> {
        calls.push(`publish:${redcon}`)
      },
    }

    await publishSparkplugRedconCommandWithAck(session, 3)

    expect(calls).toEqual(['publish:3'])
  })

  test('surfaces publish failures directly', async () => {
    const session = {
      async publishRedconCommand(): Promise<void> {
        throw new Error('publish failed')
      },
    }

    await expect(publishSparkplugRedconCommandWithAck(session, 4)).rejects.toThrow(
      'publish failed',
    )
  })
})
