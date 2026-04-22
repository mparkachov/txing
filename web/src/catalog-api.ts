import {
  DescribeThingCommand,
  DescribeThingGroupCommand,
  IoTClient,
  ListThingsInThingGroupCommand,
  type DescribeThingCommandOutput,
  type DescribeThingGroupCommandOutput,
  type ListThingsInThingGroupCommandOutput,
} from '@aws-sdk/client-iot'
import { createCredentialProvider } from './aws-credentials'
import { appConfig } from './config'

type ResolveIdToken = () => Promise<string>
type IotControlClient = Pick<IoTClient, 'send'>
export type RigCatalogEntry = {
  thingName: string
  rigName: string
  shortId: string | null
}
export type DeviceCatalogEntry = {
  thingName: string
  name: string | null
  shortId: string | null
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

const getRigDisplayName = (rig: RigCatalogEntry): string => rig.rigName

const getDeviceDisplayName = (device: DeviceCatalogEntry): string =>
  device.name ?? device.thingName

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

export const describeThingMetadataWithClient = async (
  client: IotControlClient,
  thingName: string,
): Promise<{ thingName: string; thingTypeName: string | null; name: string | null; shortId: string | null }> => {
  const response = (await client.send(
    new DescribeThingCommand({
      thingName,
    }),
  )) as DescribeThingCommandOutput

  const attributes = response.attributes
  return {
    thingName,
    thingTypeName: normalizeOptionalText(response.thingTypeName),
    name: normalizeOptionalText(
      attributes && typeof attributes.name === 'string' ? attributes.name : null,
    ),
    shortId: normalizeOptionalText(
      attributes && typeof attributes.shortId === 'string' ? attributes.shortId : null,
    ),
  }
}

export const listTownRigsWithClient = async (
  client: IotControlClient,
  townName: string,
): Promise<RigCatalogEntry[]> => {
  await client.send(
    new DescribeThingGroupCommand({
      thingGroupName: townName,
    }),
  ) as DescribeThingGroupCommandOutput

  const rigThingNames: string[] = []
  let nextToken: string | undefined

  do {
    const response = (await client.send(
      new ListThingsInThingGroupCommand({
        thingGroupName: townName,
        nextToken,
        maxResults,
      }),
    )) as ListThingsInThingGroupCommandOutput

    for (const thingName of response.things ?? []) {
      if (typeof thingName === 'string' && thingName.trim() !== '') {
        rigThingNames.push(thingName.trim())
      }
    }

    nextToken = response.nextToken
  } while (nextToken)

  const rigEntries = await Promise.all(
    sortUnique(rigThingNames).map(async (thingName) => {
      const metadata = await describeThingMetadataWithClient(client, thingName)
      return {
        thingName,
        rigName: metadata.name ?? thingName,
        shortId: metadata.shortId,
        thingTypeName: metadata.thingTypeName,
      }
    }),
  )

  return rigEntries
    .filter((rig) => rig.thingTypeName === 'rig')
    .map(({ thingTypeName: _thingTypeName, ...rig }) => rig)
    .sort((left, right) => collator.compare(getRigDisplayName(left), getRigDisplayName(right)))
}

export const listTownRigs = async (
  resolveIdToken: ResolveIdToken,
  townName: string,
): Promise<RigCatalogEntry[]> => {
  const client = await createIotControlClient(resolveIdToken)
  return listTownRigsWithClient(client, townName)
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
        const metadata = await describeThingMetadataWithClient(client, thingName)
        return {
          thingName,
          name: metadata.name,
          shortId: metadata.shortId,
        }
      } catch {
        return {
          thingName,
          name: null,
          shortId: null,
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
  const metadata = await describeThingMetadataWithClient(client, thingName)
  return {
    thingName,
    name: metadata.name,
    shortId: metadata.shortId,
  }
}

export const describeDeviceMetadata = async (
  resolveIdToken: ResolveIdToken,
  thingName: string,
): Promise<DeviceCatalogEntry> => {
  const client = await createIotControlClient(resolveIdToken)
  return describeDeviceMetadataWithClient(client, thingName)
}
