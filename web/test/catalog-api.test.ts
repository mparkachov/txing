import { describe, expect, test } from 'bun:test'
import {
  describeDeviceMetadataWithClient,
  isRigThingGroupQuery,
  listRigDevicesWithClient,
  listRigThingGroupsWithClient,
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
  test('recognizes rig dynamic thing group queries', () => {
    expect(isRigThingGroupQuery('attributes.rig:rig AND attributes.town:*')).toBe(true)
    expect(isRigThingGroupQuery('attributes.deviceType:unit')).toBe(false)
    expect(isRigThingGroupQuery(undefined)).toBe(false)
  })

  test('lists rig groups through pagination, filtering, and sorting', async () => {
    const client = new FakeIotControlClient({
      ListThingGroupsCommand: [
        {
          thingGroups: [{ groupName: 'z-rig' }, { groupName: 'misc' }],
          nextToken: 'page-2',
        },
        {
          thingGroups: [{ groupName: 'a-rig' }],
        },
      ],
      DescribeThingGroupCommand: [
        {
          thingGroupName: 'a-rig',
          queryString: 'attributes.rig:a-rig AND attributes.town:*',
          thingGroupProperties: {
            thingGroupDescription: 'Alpha description',
          },
        },
        {
          thingGroupName: 'misc',
          queryString: 'attributes.deviceType:unit',
        },
        {
          thingGroupName: 'z-rig',
          queryString: 'attributes.rig:z-rig AND attributes.town:*',
          thingGroupProperties: {
            thingGroupDescription: 'Zulu description',
          },
        },
      ],
    })

    await expect(listRigThingGroupsWithClient(client)).resolves.toEqual([
      {
        rigName: 'a-rig',
        description: 'Alpha description',
      },
      {
        rigName: 'z-rig',
        description: 'Zulu description',
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
          attributes: {
            deviceName: 'bot',
          },
        },
        {
          thingName: 'unit-b3',
          attributes: {
            deviceName: 'crawler',
          },
        },
        {
          thingName: 'unit-z9',
          attributes: {
            deviceName: 'zeta',
          },
        },
      ],
    })

    await expect(listRigDevicesWithClient(client, 'rig')).resolves.toEqual([
      {
        thingName: 'unit-a1',
        deviceName: 'bot',
      },
      {
        thingName: 'unit-b3',
        deviceName: 'crawler',
      },
      {
        thingName: 'unit-z9',
        deviceName: 'zeta',
      },
    ])
  })

  test('describes selected device metadata and trims deviceName', async () => {
    const client = new FakeIotControlClient({
      DescribeThingCommand: [
        {
          thingName: 'unit-kiv3mj',
          attributes: {
            deviceName: ' bot ',
          },
        },
      ],
    })

    await expect(describeDeviceMetadataWithClient(client, 'unit-kiv3mj')).resolves.toEqual({
      thingName: 'unit-kiv3mj',
      deviceName: 'bot',
    })
  })
})
