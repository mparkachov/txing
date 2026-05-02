import { describe, expect, test } from 'bun:test'
import {
  describeDeviceMetadataWithClient,
  describeThingMetadataWithClient,
  formatThingShadowReadError,
  getThingNamedShadowWithClient,
  listRigDevicesWithClient,
  listTownRigsWithClient,
} from '../src/catalog-api'

type FakeResponse = Record<string, unknown>

class FakeIotControlClient {
  private readonly responses: Map<string, FakeResponse[]>
  readonly commands: Array<{ constructor: { name: string }; input?: Record<string, unknown> }> = []

  constructor(responses: Record<string, FakeResponse[]>) {
    this.responses = new Map(Object.entries(responses))
  }

  async send(command: { constructor: { name: string }; input?: Record<string, unknown> }): Promise<unknown> {
    this.commands.push(command)
    const bucket = this.responses.get(command.constructor.name)
    if (!bucket || bucket.length === 0) {
      throw new Error(`Missing fake response for ${command.constructor.name}`)
    }
    return bucket.shift() as FakeResponse
  }
}

describe('catalog api helpers', () => {
  test('lists rigs from the configured town through fleet index and metadata lookup', async () => {
    const client = new FakeIotControlClient({
      SearchIndexCommand: [
        {
          things: [{ thingName: 'raspi-a1' }, { thingName: 'raspi-b3' }, { thingName: 'cloud-z9' }],
        },
      ],
      DescribeThingCommand: [
        {
          thingName: 'town-berlin',
          thingTypeName: 'town',
          attributes: {
            name: 'berlin',
            shortId: 'berlin',
            kind: 'townType',
            capabilities: 'sparkplug',
          },
        },
        {
          thingName: 'cloud-z9',
          thingTypeName: 'cloud',
          attributes: {
            name: 'zulu',
            shortId: 'z9',
            townId: 'town-berlin',
            kind: 'rigType',
            capabilities: 'sparkplug',
          },
        },
        {
          thingName: 'raspi-a1',
          thingTypeName: 'raspi',
          attributes: {
            name: 'alpha',
            shortId: 'a1',
            townId: 'town-berlin',
            kind: 'rigType',
            capabilities: 'sparkplug',
          },
        },
        {
          thingName: 'raspi-b3',
          thingTypeName: 'raspi',
          attributes: {
            name: 'bravo',
            shortId: 'b3',
            townId: 'town-berlin',
            kind: 'rigType',
            capabilities: 'sparkplug',
          },
        },
        {
          thingName: 'town-berlin',
          thingTypeName: 'town',
          attributes: {
            name: 'berlin',
            shortId: 'berlin',
            kind: 'townType',
            capabilities: 'sparkplug',
          },
        },
        {
          thingName: 'town-berlin',
          thingTypeName: 'town',
          attributes: {
            name: 'berlin',
            shortId: 'berlin',
            kind: 'townType',
            capabilities: 'sparkplug',
          },
        },
        {
          thingName: 'town-berlin',
          thingTypeName: 'town',
          attributes: {
            name: 'berlin',
            shortId: 'berlin',
            kind: 'townType',
            capabilities: 'sparkplug',
          },
        },
      ],
    })

    await expect(listTownRigsWithClient(client, 'town-berlin')).resolves.toEqual([
      {
        thingName: 'raspi-a1',
        rigName: 'alpha',
        shortId: 'a1',
        capabilities: ['sparkplug'],
      },
      {
        thingName: 'raspi-b3',
        rigName: 'bravo',
        shortId: 'b3',
        capabilities: ['sparkplug'],
      },
      {
        thingName: 'cloud-z9',
        rigName: 'zulu',
        shortId: 'z9',
        capabilities: ['sparkplug'],
      },
    ])
    expect(client.commands[1].input?.queryString).toBe(
      'attributes.kind:rigType AND attributes.townId:town-berlin',
    )
  })

  test('lists rig devices through pagination, metadata lookup, and stable sorting', async () => {
    const client = new FakeIotControlClient({
      SearchIndexCommand: [
        {
          things: [{ thingName: 'unit-z9' }, { thingName: 'unit-a1' }],
          nextToken: 'page-2',
        },
        {
          things: [{ thingName: 'unit-a1' }, { thingName: 'unit-b3' }],
        },
      ],
      DescribeThingCommand: [
        {
          thingName: 'unit-a1',
          thingTypeName: 'unit',
          attributes: {
            name: 'bot',
            shortId: 'a1',
            townId: 'town-berlin',
            rigId: 'raspi-a1',
            kind: 'deviceType',
            capabilities: 'sparkplug,mcu,board,mcp,video',
          },
        },
        {
          thingName: 'unit-b3',
          thingTypeName: 'unit',
          attributes: {
            name: 'crawler',
            shortId: 'b3',
            townId: 'town-berlin',
            rigId: 'raspi-a1',
            kind: 'deviceType',
            capabilities: 'sparkplug,mcu,board,mcp,video',
          },
        },
        {
          thingName: 'unit-z9',
          thingTypeName: 'unit',
          attributes: {
            name: 'zeta',
            shortId: 'z9',
            townId: 'town-berlin',
            rigId: 'raspi-a1',
            kind: 'deviceType',
            capabilities: 'sparkplug,mcu,board,mcp,video',
          },
        },
        {
          thingName: 'town-berlin',
          thingTypeName: 'town',
          attributes: {
            name: 'berlin',
            shortId: 'berlin',
            kind: 'townType',
            capabilities: 'sparkplug',
          },
        },
        {
          thingName: 'town-berlin',
          thingTypeName: 'town',
          attributes: {
            name: 'berlin',
            shortId: 'berlin',
            kind: 'townType',
            capabilities: 'sparkplug',
          },
        },
        {
          thingName: 'town-berlin',
          thingTypeName: 'town',
          attributes: {
            name: 'berlin',
            shortId: 'berlin',
            kind: 'townType',
            capabilities: 'sparkplug',
          },
        },
        {
          thingName: 'raspi-a1',
          thingTypeName: 'raspi',
          attributes: {
            name: 'alpha',
            shortId: 'a1',
            townId: 'town-berlin',
            kind: 'rigType',
            capabilities: 'sparkplug',
          },
        },
        {
          thingName: 'raspi-a1',
          thingTypeName: 'raspi',
          attributes: {
            name: 'alpha',
            shortId: 'a1',
            townId: 'town-berlin',
            kind: 'rigType',
            capabilities: 'sparkplug',
          },
        },
        {
          thingName: 'raspi-a1',
          thingTypeName: 'raspi',
          attributes: {
            name: 'alpha',
            shortId: 'a1',
            townId: 'town-berlin',
            kind: 'rigType',
            capabilities: 'sparkplug',
          },
        },
      ],
    })

    await expect(listRigDevicesWithClient(client, 'raspi-a1')).resolves.toEqual([
      {
        thingName: 'unit-a1',
        name: 'bot',
        shortId: 'a1',
        capabilities: ['sparkplug', 'mcu', 'board', 'mcp', 'video'],
      },
      {
        thingName: 'unit-b3',
        name: 'crawler',
        shortId: 'b3',
        capabilities: ['sparkplug', 'mcu', 'board', 'mcp', 'video'],
      },
      {
        thingName: 'unit-z9',
        name: 'zeta',
        shortId: 'z9',
        capabilities: ['sparkplug', 'mcu', 'board', 'mcp', 'video'],
      },
    ])
    expect(client.commands[0].input?.queryString).toBe(
      'attributes.kind:deviceType AND attributes.rigId:raspi-a1',
    )
  })

  test('describes selected device metadata and trims name', async () => {
    const client = new FakeIotControlClient({
      DescribeThingCommand: [
        {
          thingName: 'unit-kiv3mj',
          thingTypeName: 'unit',
          attributes: {
            name: ' bot ',
            shortId: 'kiv3mj',
            townId: 'town-berlin',
            rigId: 'raspi-a1',
            kind: 'deviceType',
            capabilities: 'sparkplug,mcu,board,mcp,video',
          },
        },
        {
          thingName: 'town-berlin',
          thingTypeName: 'town',
          attributes: {
            name: 'berlin',
            shortId: 'berlin',
            kind: 'townType',
            capabilities: 'sparkplug',
          },
        },
        {
          thingName: 'raspi-a1',
          thingTypeName: 'raspi',
          attributes: {
            name: 'alpha',
            shortId: 'a1',
            townId: 'town-berlin',
            kind: 'rigType',
            capabilities: 'sparkplug',
          },
        },
      ],
    })

    await expect(describeDeviceMetadataWithClient(client, 'unit-kiv3mj')).resolves.toEqual({
      thingName: 'unit-kiv3mj',
      name: 'bot',
      shortId: 'kiv3mj',
      capabilities: ['sparkplug', 'mcu', 'board', 'mcp', 'video'],
    })
  })

  test('describes unknown device types with custom shadow capabilities', async () => {
    const client = new FakeIotControlClient({
      DescribeThingCommand: [
        {
          thingName: 'sensor-a1',
          thingTypeName: 'sensor',
          attributes: {
            name: 'sensor',
            shortId: 'a1',
            kind: 'deviceType',
            capabilities: 'sparkplug,sensor-data',
          },
        },
      ],
    })

    await expect(describeThingMetadataWithClient(client, 'sensor-a1')).resolves.toEqual({
      thingName: 'sensor-a1',
      thingTypeName: 'sensor',
      kind: 'deviceType',
      name: 'sensor',
      townId: null,
      rigId: null,
      townName: null,
      rigName: null,
      shortId: 'a1',
      capabilities: ['sparkplug', 'sensor-data'],
    })
  })

  test('describes generic thing metadata including parent registry names', async () => {
    const client = new FakeIotControlClient({
      DescribeThingCommand: [
        {
          thingName: 'raspi-a1',
          thingTypeName: 'raspi',
          attributes: {
            name: 'alpha',
            townId: 'town-berlin',
            shortId: 'a1',
            kind: 'rigType',
            capabilities: 'sparkplug',
          },
        },
        {
          thingName: 'town-berlin',
          thingTypeName: 'town',
          attributes: {
            name: 'berlin',
            shortId: 'berlin',
            kind: 'townType',
            capabilities: 'sparkplug',
          },
        },
      ],
    })

    await expect(describeThingMetadataWithClient(client, 'raspi-a1')).resolves.toEqual({
      thingName: 'raspi-a1',
      thingTypeName: 'raspi',
      kind: 'rigType',
      name: 'alpha',
      townId: 'town-berlin',
      rigId: 'raspi-a1',
      townName: 'berlin',
      rigName: 'alpha',
      shortId: 'a1',
      capabilities: ['sparkplug'],
    })
  })

  test('reads a named sparkplug shadow document through the IoT data client', async () => {
    const client = new FakeIotControlClient({
      GetThingShadowCommand: [
        {
          payload: new TextEncoder().encode(
            JSON.stringify({
              state: {
                reported: {
                  metrics: {
                    redcon: 1,
                    batteryMv: 4112,
                  },
                },
              },
            }),
          ),
        },
      ],
    })

    await expect(getThingNamedShadowWithClient(client, 'unit-a1', 'sparkplug')).resolves.toEqual({
      state: {
        reported: {
          metrics: {
            redcon: 1,
            batteryMv: 4112,
          },
        },
      },
    })
  })

  test('formats forbidden direct shadow reads with a redeploy hint', () => {
    expect(
      formatThingShadowReadError(
        {
          name: 'UnknownError',
          $metadata: {
            httpStatusCode: 403,
          },
        },
        'town-a1',
        'sparkplug',
      ),
    ).toContain('iot:GetThingShadow')
  })
})
