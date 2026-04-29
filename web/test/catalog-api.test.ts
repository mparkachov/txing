import { describe, expect, test } from 'bun:test'
import {
  describeDeviceMetadataWithClient,
  listRigDevicesWithClient,
  listTownRigsWithClient,
} from '../src/catalog-api'

type FakeResponse = Record<string, unknown>

class FakeIotControlClient {
  private readonly responses: Map<string, FakeResponse[]>

  constructor(responses: Record<string, FakeResponse[]>) {
    this.responses = new Map(Object.entries(responses))
  }

  async send(command: { constructor: { name: string } }): Promise<unknown> {
    const bucket = this.responses.get(command.constructor.name)
    if (!bucket || bucket.length === 0) {
      throw new Error(`Missing fake response for ${command.constructor.name}`)
    }
    return bucket.shift() as FakeResponse
  }
}

describe('catalog api helpers', () => {
  test('lists rigs from the configured town group through pagination and metadata lookup', async () => {
    const client = new FakeIotControlClient({
      DescribeThingGroupCommand: [
        {
          thingGroupName: 'berlin',
        },
      ],
      ListThingsInThingGroupCommand: [
        {
          things: ['rig-z9', 'rig-a1'],
          nextToken: 'page-2',
        },
        {
          things: ['rig-a1', 'rig-b3'],
        },
      ],
      DescribeThingCommand: [
        {
          thingName: 'rig-a1',
          thingTypeName: 'rig',
          attributes: {
            name: 'alpha',
            shortId: 'a1',
            capabilitiesSet: 'sparkplug',
          },
        },
        {
          thingName: 'rig-b3',
          thingTypeName: 'rig',
          attributes: {
            name: 'bravo',
            shortId: 'b3',
            capabilitiesSet: 'sparkplug',
          },
        },
        {
          thingName: 'rig-z9',
          thingTypeName: 'rig',
          attributes: {
            name: 'zulu',
            shortId: 'z9',
            capabilitiesSet: 'sparkplug',
          },
        },
      ],
    })

    await expect(listTownRigsWithClient(client, 'berlin')).resolves.toEqual([
      {
        thingName: 'rig-a1',
        rigName: 'alpha',
        shortId: 'a1',
        capabilitiesSet: ['sparkplug'],
      },
      {
        thingName: 'rig-b3',
        rigName: 'bravo',
        shortId: 'b3',
        capabilitiesSet: ['sparkplug'],
      },
      {
        thingName: 'rig-z9',
        rigName: 'zulu',
        shortId: 'z9',
        capabilitiesSet: ['sparkplug'],
      },
    ])
  })

  test('lists rig devices through pagination, metadata lookup, and stable sorting', async () => {
    const client = new FakeIotControlClient({
      ListThingsInThingGroupCommand: [
        {
          things: ['unit-z9', 'unit-a1'],
          nextToken: 'page-2',
        },
        {
          things: ['unit-a1', 'unit-b3'],
        },
      ],
      DescribeThingCommand: [
        {
          thingName: 'unit-a1',
          thingTypeName: 'unit',
          attributes: {
            name: 'bot',
            shortId: 'a1',
            capabilitiesSet: 'sparkplug,device,mcu,board,video',
          },
        },
        {
          thingName: 'unit-b3',
          thingTypeName: 'unit',
          attributes: {
            name: 'crawler',
            shortId: 'b3',
            capabilitiesSet: 'sparkplug,device,mcu,board,video',
          },
        },
        {
          thingName: 'unit-z9',
          thingTypeName: 'unit',
          attributes: {
            name: 'zeta',
            shortId: 'z9',
            capabilitiesSet: 'sparkplug,device,mcu,board,video',
          },
        },
      ],
    })

    await expect(listRigDevicesWithClient(client, 'rig')).resolves.toEqual([
      {
        thingName: 'unit-a1',
        name: 'bot',
        shortId: 'a1',
        capabilitiesSet: ['sparkplug', 'device', 'mcu', 'board', 'video'],
      },
      {
        thingName: 'unit-b3',
        name: 'crawler',
        shortId: 'b3',
        capabilitiesSet: ['sparkplug', 'device', 'mcu', 'board', 'video'],
      },
      {
        thingName: 'unit-z9',
        name: 'zeta',
        shortId: 'z9',
        capabilitiesSet: ['sparkplug', 'device', 'mcu', 'board', 'video'],
      },
    ])
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
            capabilitiesSet: 'sparkplug,device,mcu,board,video',
          },
        },
      ],
    })

    await expect(describeDeviceMetadataWithClient(client, 'unit-kiv3mj')).resolves.toEqual({
      thingName: 'unit-kiv3mj',
      name: 'bot',
      shortId: 'kiv3mj',
      capabilitiesSet: ['sparkplug', 'device', 'mcu', 'board', 'video'],
    })
  })
})
