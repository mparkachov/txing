import {
  DescribeThingCommand,
  IoTClient,
  SearchIndexCommand,
  type DescribeThingCommandOutput,
  type SearchIndexCommandOutput,
} from '@aws-sdk/client-iot'
import {
  GetThingShadowCommand,
  IoTDataPlaneClient,
  type GetThingShadowCommandOutput,
} from '@aws-sdk/client-iot-data-plane'
import { clearCredentialProviderCache, createCredentialProvider } from './aws-credentials'
import { appConfig } from './config'
import { ensureIotPolicyAttached } from './iot-policy-attach'
import { buildIotDataEndpointUrl, resolveIotDataEndpoint } from './iot-endpoint'
import { isShadowName, type ShadowName } from './shadow-protocol'

type ResolveIdToken = () => Promise<string>
type IotControlClient = Pick<IoTClient, 'send'>
type IotDataClient = Pick<IoTDataPlaneClient, 'send'>
export type RigCatalogEntry = {
  thingName: string
  rigName: string
  shortId: string | null
  capabilities: readonly ShadowName[]
}
export type DeviceCatalogEntry = {
  thingName: string
  name: string | null
  shortId: string | null
  capabilities: readonly ShadowName[]
}
export type ThingMetadata = {
  thingName: string
  thingTypeName: string | null
  kind: string | null
  name: string | null
  townId: string | null
  rigId: string | null
  townName: string | null
  rigName: string | null
  shortId: string | null
  capabilities: readonly ShadowName[]
}

const maxResults = 100
export const townTypeKind = 'townType'
export const rigTypeKind = 'rigType'
export const deviceTypeKind = 'deviceType'

const collator = new Intl.Collator(undefined, {
  numeric: true,
  sensitivity: 'base',
})

const sortUnique = (values: readonly string[]): string[] =>
  [...new Set(values)].sort((left, right) => collator.compare(left, right))

const payloadDecoder = new TextDecoder()

const normalizeOptionalText = (value: string | null | undefined): string | null => {
  if (typeof value !== 'string') {
    return null
  }

  const normalized = value.trim()
  return normalized === '' ? null : normalized
}

export const parseCapabilitiesSet = (value: string | null | undefined): readonly ShadowName[] => {
  if (typeof value !== 'string' || value.trim() === '') {
    throw new Error('Thing is missing required capabilities attribute')
  }
  const capabilities: ShadowName[] = []
  const seen = new Set<ShadowName>()
  for (const rawCapability of value.split(',')) {
    if (rawCapability.trim() !== rawCapability || rawCapability === '') {
      throw new Error(`Thing has malformed capabilities attribute: ${value}`)
    }
    if (!isShadowName(rawCapability)) {
      throw new Error(`Thing has invalid shadow capability name: ${rawCapability}`)
    }
    if (seen.has(rawCapability)) {
      throw new Error(`Thing has duplicate capability: ${rawCapability}`)
    }
    seen.add(rawCapability)
    capabilities.push(rawCapability)
  }
  if (!seen.has('sparkplug')) {
    throw new Error('Thing capabilities must include sparkplug')
  }
  return capabilities
}

const isRigKind = (kind: string | null | undefined): boolean => kind === rigTypeKind

const getRigDisplayName = (rig: RigCatalogEntry): string => rig.rigName

const getDeviceDisplayName = (device: DeviceCatalogEntry): string =>
  device.name ?? device.thingName

export const isResourceNotFoundError = (error: unknown): boolean =>
  error instanceof Error &&
  (error.name === 'ResourceNotFoundException' ||
    error.message.toLowerCase().includes('not found'))

const hasHttpStatusCode = (error: unknown, statusCode: number): boolean =>
  typeof error === 'object' &&
  error !== null &&
  '$metadata' in error &&
  typeof (error as { $metadata?: { httpStatusCode?: unknown } }).$metadata?.httpStatusCode === 'number' &&
  (error as { $metadata: { httpStatusCode: number } }).$metadata.httpStatusCode === statusCode

export const isThingShadowReadForbiddenError = (error: unknown): boolean =>
  hasHttpStatusCode(error, 403) ||
  (error instanceof Error &&
    (error.name === 'ForbiddenException' ||
      error.name === 'UnknownError' ||
      error.message.toLowerCase().includes('forbidden') ||
      error.message.toLowerCase().includes('not authorized')))

const runWithFreshCredentialRetry = async <T>(
  resolveIdToken: ResolveIdToken,
  operation: (idToken: string) => Promise<T>,
  shouldRetry: (error: unknown) => boolean = isThingShadowReadForbiddenError,
): Promise<T> => {
  const runOnce = async (): Promise<T> => operation(await resolveIdToken())

  try {
    return await runOnce()
  } catch (caughtError) {
    if (!shouldRetry(caughtError)) {
      throw caughtError
    }
  }

  clearCredentialProviderCache()
  return runOnce()
}

export const formatThingShadowReadError = (
  error: unknown,
  thingName: string,
  shadowName: ShadowName = 'sparkplug',
): string => {
  if (isThingShadowReadForbiddenError(error)) {
    return `Direct AWS IoT read of ${thingName}/${shadowName} is forbidden for the authenticated web identity. Redeploy shared/aws so the web authenticated role includes iot:GetThingShadow, then sign in again.`
  }
  if (isResourceNotFoundError(error)) {
    return `Thing '${thingName}' is missing the named shadow '${shadowName}'.`
  }
  if (error instanceof Error && error.message.trim()) {
    return error.message
  }
  return `Unable to read named shadow '${shadowName}' for thing '${thingName}'.`
}

const createIotControlClient = (idToken: string): IotControlClient =>
  new IoTClient({
    region: appConfig.awsRegion,
    credentials: createCredentialProvider(idToken),
  })

const createIotDataClient = async (idToken: string): Promise<IotDataClient> => {
  const endpoint = await resolveIotDataEndpoint({
    region: appConfig.awsRegion,
    idToken,
  })
  return new IoTDataPlaneClient({
    region: appConfig.awsRegion,
    endpoint: buildIotDataEndpointUrl(endpoint),
    credentials: createCredentialProvider(idToken),
  })
}

const decodeShadowPayload = (payload: Uint8Array | undefined): unknown => {
  if (!(payload instanceof Uint8Array)) {
    return {}
  }
  const text = payloadDecoder.decode(payload).trim()
  if (!text) {
    return {}
  }
  return JSON.parse(text)
}

export const describeThingMetadataWithClient = async (
  client: IotControlClient,
  thingName: string,
): Promise<ThingMetadata> => {
  const response = (await client.send(
    new DescribeThingCommand({
      thingName,
    }),
  )) as DescribeThingCommandOutput

  const attributes = response.attributes
  const thingTypeName = normalizeOptionalText(response.thingTypeName)
  const kind = normalizeOptionalText(
    attributes && typeof attributes.kind === 'string' ? attributes.kind : null,
  )
  const townId = normalizeOptionalText(
    attributes && typeof attributes.townId === 'string' ? attributes.townId : null,
  )
  const rigId = normalizeOptionalText(
    attributes && typeof attributes.rigId === 'string' ? attributes.rigId : null,
  )
  let townName = townId
  let rigName = rigId
  if (townId) {
    try {
      const townResponse = (await client.send(
        new DescribeThingCommand({ thingName: townId }),
      )) as DescribeThingCommandOutput
      townName = normalizeOptionalText(townResponse.attributes?.name) ?? townId
    } catch {
      townName = townId
    }
  }
  if (rigId) {
    try {
      const rigResponse = (await client.send(
        new DescribeThingCommand({ thingName: rigId }),
      )) as DescribeThingCommandOutput
      rigName = normalizeOptionalText(rigResponse.attributes?.name) ?? rigId
    } catch {
      rigName = rigId
    }
  } else if (isRigKind(kind)) {
    rigName = normalizeOptionalText(attributes?.name) ?? thingName
  }
  return {
    thingName,
    thingTypeName,
    kind,
    name: normalizeOptionalText(
      attributes && typeof attributes.name === 'string' ? attributes.name : null,
    ),
    townId,
    rigId: isRigKind(kind) ? thingName : rigId,
    townName,
    rigName,
    shortId: normalizeOptionalText(
      attributes && typeof attributes.shortId === 'string' ? attributes.shortId : null,
    ),
    capabilities: parseCapabilitiesSet(
      attributes && typeof attributes.capabilities === 'string'
        ? attributes.capabilities
        : null,
    ),
  }
}

export const describeThingMetadata = async (
  resolveIdToken: ResolveIdToken,
  thingName: string,
): Promise<ThingMetadata> => {
  return runWithFreshCredentialRetry(resolveIdToken, async (idToken) => {
    const client = createIotControlClient(idToken)
    return describeThingMetadataWithClient(client, thingName)
  })
}

export const getThingNamedShadowWithClient = async (
  client: IotDataClient,
  thingName: string,
  shadowName: ShadowName = 'sparkplug',
): Promise<unknown> => {
  const response = (await client.send(
    new GetThingShadowCommand({
      thingName,
      shadowName,
    }),
  )) as GetThingShadowCommandOutput

  return decodeShadowPayload(response.payload)
}

export const getThingNamedShadow = async (
  resolveIdToken: ResolveIdToken,
  thingName: string,
  shadowName: ShadowName = 'sparkplug',
): Promise<unknown> => {
  return runWithFreshCredentialRetry(resolveIdToken, async (idToken) => {
    await ensureIotPolicyAttached(idToken)
    const client = await createIotDataClient(idToken)
    return getThingNamedShadowWithClient(client, thingName, shadowName)
  })
}

const searchThingNamesWithClient = async (
  client: IotControlClient,
  queryString: string,
): Promise<string[]> => {
  const thingNames: string[] = []
  let nextToken: string | undefined

  do {
    const response = (await client.send(
      new SearchIndexCommand({
        indexName: 'AWS_Things',
        queryString,
        maxResults,
        nextToken,
      }),
    )) as SearchIndexCommandOutput

    for (const thing of response.things ?? []) {
      const nextThingName = normalizeOptionalText(thing.thingName)
      if (nextThingName) {
        thingNames.push(nextThingName)
      }
    }

    nextToken = response.nextToken
  } while (nextToken)

  return sortUnique(thingNames)
}

const resolveSingleThingMetadataWithClient = async (
  client: IotControlClient,
  queryString: string,
  missingMessage: string,
  multipleMessage: string,
): Promise<ThingMetadata> => {
  const thingNames = await searchThingNamesWithClient(client, queryString)
  if (thingNames.length === 0) {
    throw new Error(missingMessage)
  }
  if (thingNames.length > 1) {
    throw new Error(multipleMessage)
  }
  return describeThingMetadataWithClient(client, thingNames[0])
}

export const listTownRigsWithClient = async (
  client: IotControlClient,
  townName: string,
): Promise<RigCatalogEntry[]> => {
  const townMetadata =
    townName.startsWith('town-')
      ? await describeThingMetadataWithClient(client, townName)
      : await resolveTownThingWithClient(client, townName)
  const rigThingNames = await searchThingNamesWithClient(
    client,
    `attributes.kind:${rigTypeKind} AND attributes.townId:${townMetadata.thingName}`,
  )

  const rigEntries = await Promise.all(
    sortUnique(rigThingNames).map(async (thingName) => {
      const metadata = await describeThingMetadataWithClient(client, thingName)
      return {
        thingName,
        rigName: metadata.name ?? thingName,
        shortId: metadata.shortId,
        capabilities: metadata.capabilities,
        kind: metadata.kind,
      }
    }),
  )

  return rigEntries
    .filter((rig) => isRigKind(rig.kind))
    .map((rig) => ({
      thingName: rig.thingName,
      rigName: rig.rigName,
      shortId: rig.shortId,
      capabilities: rig.capabilities,
    }))
    .sort((left, right) => collator.compare(getRigDisplayName(left), getRigDisplayName(right)))
}

export const listTownRigs = async (
  resolveIdToken: ResolveIdToken,
  townName: string,
): Promise<RigCatalogEntry[]> => {
  return runWithFreshCredentialRetry(resolveIdToken, async (idToken) => {
    const client = createIotControlClient(idToken)
    return listTownRigsWithClient(client, townName)
  })
}

export const listRigDevicesWithClient = async (
  client: IotControlClient,
  rigName: string,
): Promise<DeviceCatalogEntry[]> => {
  const deviceIds = await searchThingNamesWithClient(
    client,
    `attributes.kind:${deviceTypeKind} AND attributes.rigId:${rigName}`,
  )

  const uniqueDeviceIds = sortUnique(deviceIds)
  const deviceEntries = await Promise.all(
    uniqueDeviceIds.map(async (thingName) => {
      const metadata = await describeThingMetadataWithClient(client, thingName)
      return {
        thingName,
        name: metadata.name,
        shortId: metadata.shortId,
        capabilities: metadata.capabilities,
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
  return runWithFreshCredentialRetry(resolveIdToken, async (idToken) => {
    const client = createIotControlClient(idToken)
    return listRigDevicesWithClient(client, rigName)
  })
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
    capabilities: metadata.capabilities,
  }
}

export const describeDeviceMetadata = async (
  resolveIdToken: ResolveIdToken,
  thingName: string,
): Promise<DeviceCatalogEntry> => {
  return runWithFreshCredentialRetry(resolveIdToken, async (idToken) => {
    const client = createIotControlClient(idToken)
    return describeDeviceMetadataWithClient(client, thingName)
  })
}

export const resolveTownThingWithClient = async (
  client: IotControlClient,
  townName: string,
): Promise<ThingMetadata> =>
  resolveSingleThingMetadataWithClient(
    client,
    `attributes.kind:${townTypeKind} AND attributes.name:${townName}`,
    `Town '${townName}' was not found.`,
    `Town '${townName}' matched multiple AWS IoT things.`,
  )

export const resolveTownThing = async (
  resolveIdToken: ResolveIdToken,
  townName: string,
): Promise<ThingMetadata> => {
  return runWithFreshCredentialRetry(resolveIdToken, async (idToken) => {
    const client = createIotControlClient(idToken)
    return resolveTownThingWithClient(client, townName)
  })
}

export const resolveRigThingWithClient = async (
  client: IotControlClient,
  townName: string,
  rigName: string,
): Promise<ThingMetadata> => {
  const townMetadata =
    townName.startsWith('town-')
      ? await describeThingMetadataWithClient(client, townName)
      : await resolveTownThingWithClient(client, townName)
  const thingNames = sortUnique(
    await searchThingNamesWithClient(
      client,
      `attributes.kind:${rigTypeKind} AND attributes.name:${rigName} AND attributes.townId:${townMetadata.thingName}`,
    ),
  )
  if (thingNames.length === 0) {
    throw new Error(`Rig '${rigName}' in town '${townName}' was not found.`)
  }
  if (thingNames.length > 1) {
    throw new Error(`Rig '${rigName}' in town '${townName}' matched multiple AWS IoT things.`)
  }
  return describeThingMetadataWithClient(client, thingNames[0])
}

export const resolveRigThing = async (
  resolveIdToken: ResolveIdToken,
  townName: string,
  rigName: string,
): Promise<ThingMetadata> => {
  return runWithFreshCredentialRetry(resolveIdToken, async (idToken) => {
    const client = createIotControlClient(idToken)
    return resolveRigThingWithClient(client, townName, rigName)
  })
}
