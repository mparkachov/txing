import {
  DescribeThingCommand,
  DescribeThingGroupCommand,
  IoTClient,
  ListThingGroupsCommand,
  ListThingsInThingGroupCommand,
  type DescribeThingCommandOutput,
  type DescribeThingGroupCommandOutput,
  type ListThingGroupsCommandOutput,
  type ListThingsInThingGroupCommandOutput,
} from '@aws-sdk/client-iot'
import { createCredentialProvider } from './aws-credentials'
import { appConfig } from './config'

type ResolveIdToken = () => Promise<string>
type IotControlClient = Pick<IoTClient, 'send'>
export type RigCatalogEntry = {
  rigName: string
  description: string | null
}
export type DeviceCatalogEntry = {
  thingName: string
  deviceName: string | null
}

const maxResults = 100

const collator = new Intl.Collator(undefined, {
  numeric: true,
  sensitivity: 'base',
})

const sortUnique = (values: readonly string[]): string[] =>
  [...new Set(values)].sort((left, right) => collator.compare(left, right))

const normalizeOptionalText = (value: string | null | undefined): string | null => {
  if (typeof value !== 'string') {
    return null
  }

  const normalized = value.trim()
  return normalized === '' ? null : normalized
}

const getDeviceDisplayName = (device: DeviceCatalogEntry): string =>
  device.deviceName ?? device.thingName

export const isRigThingGroupQuery = (queryString: string | null | undefined): boolean =>
  typeof queryString === 'string' &&
  queryString.includes('attributes.rig:') &&
  queryString.includes('attributes.town:*')

export const isResourceNotFoundError = (error: unknown): boolean =>
  error instanceof Error &&
  (error.name === 'ResourceNotFoundException' ||
    error.message.toLowerCase().includes('not found'))

const createIotControlClient = async (resolveIdToken: ResolveIdToken): Promise<IotControlClient> => {
  const idToken = await resolveIdToken()
  return new IoTClient({
    region: appConfig.awsRegion,
    credentials: createCredentialProvider(idToken),
  })
}

export const listRigThingGroupsWithClient = async (
  client: IotControlClient,
): Promise<RigCatalogEntry[]> => {
  const candidateGroupNames: string[] = []
  let nextToken: string | undefined

  do {
    const response = (await client.send(
      new ListThingGroupsCommand({
        nextToken,
        maxResults,
      }),
    )) as ListThingGroupsCommandOutput

    for (const group of response.thingGroups ?? []) {
      if (typeof group.groupName === 'string' && group.groupName.trim() !== '') {
        candidateGroupNames.push(group.groupName.trim())
      }
    }

    nextToken = response.nextToken
  } while (nextToken)

  const rigEntries: RigCatalogEntry[] = []
  for (const groupName of sortUnique(candidateGroupNames)) {
    const description = (await client.send(
      new DescribeThingGroupCommand({
        thingGroupName: groupName,
      }),
    )) as DescribeThingGroupCommandOutput

    if (isRigThingGroupQuery(description.queryString)) {
      rigEntries.push({
        rigName: groupName,
        description: normalizeOptionalText(
          description.thingGroupProperties?.thingGroupDescription,
        ),
      })
    }
  }

  return rigEntries.sort((left, right) => collator.compare(left.rigName, right.rigName))
}

export const listRigThingGroups = async (
  resolveIdToken: ResolveIdToken,
): Promise<RigCatalogEntry[]> => {
  const client = await createIotControlClient(resolveIdToken)
  return listRigThingGroupsWithClient(client)
}

export const listRigDevicesWithClient = async (
  client: IotControlClient,
  rigName: string,
): Promise<DeviceCatalogEntry[]> => {
  const deviceIds: string[] = []
  let nextToken: string | undefined

  do {
    const response = (await client.send(
      new ListThingsInThingGroupCommand({
        thingGroupName: rigName,
        nextToken,
        maxResults,
      }),
    )) as ListThingsInThingGroupCommandOutput

    for (const thingName of response.things ?? []) {
      if (typeof thingName === 'string' && thingName.trim() !== '') {
        deviceIds.push(thingName.trim())
      }
    }

    nextToken = response.nextToken
  } while (nextToken)

  const uniqueDeviceIds = sortUnique(deviceIds)
  const deviceEntries = await Promise.all(
    uniqueDeviceIds.map(async (thingName) => {
      try {
        return await describeDeviceMetadataWithClient(client, thingName)
      } catch {
        return {
          thingName,
          deviceName: null,
        }
      }
    }),
  )

  return deviceEntries.sort((left, right) =>
    collator.compare(getDeviceDisplayName(left), getDeviceDisplayName(right)),
  )
}

export const listRigDevices = async (
  resolveIdToken: ResolveIdToken,
  rigName: string,
): Promise<DeviceCatalogEntry[]> => {
  const client = await createIotControlClient(resolveIdToken)
  return listRigDevicesWithClient(client, rigName)
}

export const describeDeviceMetadataWithClient = async (
  client: IotControlClient,
  thingName: string,
): Promise<DeviceCatalogEntry> => {
  const response = (await client.send(
    new DescribeThingCommand({
      thingName,
    }),
  )) as DescribeThingCommandOutput

  const attributes = response.attributes
  const deviceName =
    attributes && typeof attributes.deviceName === 'string' && attributes.deviceName.trim() !== ''
      ? attributes.deviceName.trim()
      : null

  return {
    thingName,
    deviceName,
  }
}

export const describeDeviceMetadata = async (
  resolveIdToken: ResolveIdToken,
  thingName: string,
): Promise<DeviceCatalogEntry> => {
  const client = await createIotControlClient(resolveIdToken)
  return describeDeviceMetadataWithClient(client, thingName)
}
