import { describe, expect, test } from 'bun:test'
import {
  publishDirectSparkplugRedconCommandWithClient,
  publishSparkplugRedconCommandWithAck,
  resolveThingSparkplugRedconCommandTarget,
} from '../src/sparkplug-command'
import { decodeSparkplugPayload } from '../src/sparkplug-protocol'

class FakeIotDataClient {
  readonly commands: Array<{ constructor: { name: string }; input: Record<string, unknown> }> = []

  async send(command: { constructor: { name: string }; input: Record<string, unknown> }): Promise<void> {
    this.commands.push(command)
  }
}

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

  test('resolves a direct Sparkplug command target for device things', () => {
    expect(
      resolveThingSparkplugRedconCommandTarget({
        thingName: 'unit-a1',
        thingTypeName: 'unit',
        townId: 'town-a1',
        rigId: 'rig-a1',
      }),
    ).toEqual({
      groupId: 'town-a1',
      edgeNodeId: 'rig-a1',
      deviceId: 'unit-a1',
    })

    expect(
      resolveThingSparkplugRedconCommandTarget({
        thingName: 'sensor-a1',
        thingTypeName: 'sensor',
        townId: 'town-a1',
        rigId: 'rig-a1',
      }),
    ).toEqual({
      groupId: 'town-a1',
      edgeNodeId: 'rig-a1',
      deviceId: 'sensor-a1',
    })

    expect(
      resolveThingSparkplugRedconCommandTarget({
        thingName: 'rig-a1',
        thingTypeName: 'rig',
        townId: 'town-a1',
        rigId: 'rig-a1',
      }),
    ).toBeNull()
  })

  test('publishes direct device Sparkplug redcon commands through the IoT data plane', async () => {
    const client = new FakeIotDataClient()

    await publishDirectSparkplugRedconCommandWithClient(
      client,
      {
        groupId: 'town',
        edgeNodeId: 'rig',
        deviceId: 'unit-a1',
      },
      3,
      17,
    )

    expect(client.commands).toHaveLength(1)
    expect(client.commands[0].constructor.name).toBe('PublishCommand')
    expect(client.commands[0].input.topic).toBe('spBv1.0/town/DCMD/rig/unit-a1')
    expect(client.commands[0].input.qos).toBe(1)

    const payload = client.commands[0].input.payload
    expect(payload).toBeInstanceOf(Uint8Array)
    const decoded = decodeSparkplugPayload(payload as Uint8Array)
    expect(decoded.seq).toBe(17)
    expect(decoded.metrics).toEqual([
      expect.objectContaining({
        name: 'redcon',
        intValue: 3,
      }),
    ])
  })
})
