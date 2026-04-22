import { describe, expect, test } from 'bun:test'
import {
  defaultSparkplugRedconAckTimeoutMs,
  publishSparkplugRedconCommandWithAck,
} from '../src/sparkplug-command'

describe('sparkplug command ack helper', () => {
  test('waits for desired.redcon reflection after publishing', async () => {
    const calls: Array<string> = []
    const session = {
      async publishRedconCommand(redcon: number): Promise<void> {
        calls.push(`publish:${redcon}`)
      },
      async waitForSnapshot(
        predicate: (shadow: unknown) => boolean,
        timeoutMs: number,
      ): Promise<unknown> {
        calls.push(`wait:${timeoutMs}`)
        const ackShadow = {
          state: {
            desired: {
              redcon: 3,
            },
          },
        }
        expect(predicate(ackShadow)).toBe(true)
        return ackShadow
      },
    }

    await publishSparkplugRedconCommandWithAck(session, 3)

    expect(calls).toEqual([`publish:3`, `wait:${defaultSparkplugRedconAckTimeoutMs}`])
  })

  test('turns a missing ack into a rig-specific timeout error', async () => {
    const session = {
      async publishRedconCommand(): Promise<void> {},
      async waitForSnapshot(): Promise<unknown> {
        throw new Error('Timed out after 3000ms')
      },
    }

    await expect(publishSparkplugRedconCommandWithAck(session, 4, 1500)).rejects.toThrow(
      'Timed out waiting for rig to acknowledge Sparkplug DCMD.redcon=4: Timed out after 3000ms',
    )
  })
})
