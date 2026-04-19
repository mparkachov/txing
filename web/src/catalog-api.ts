import {
  DescribeThingGroupCommand,
  IoTClient,
  ListThingGroupsCommand,
  ListThingsInThingGroupCommand,
  type DescribeThingGroupCommandOutput,
  type ListThingGroupsCommandOutput,
  type ListThingsInThingGroupCommandOutput,
} from '@aws-sdk/client-iot'
import { createCredentialProvider } from './aws-credentials'
import { appConfig } from './config'

type ResolveIdToken = () => Promise<string>
type IotControlClient = Pick<IoTClient, 'send'>

const maxResults = 100

const collator = new Intl.Collator(undefined, {
  numeric: true,
  sensitivity: 'base',
})

const sortUnique = (values: readonly string[]): string[] =>
  [...new Set(values)].sort((left, right) => collator.compare(left, right))

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
): Promise<string[]> => {
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

  const rigNames: string[] = []
  for (const groupName of sortUnique(candidateGroupNames)) {
    const description = (await client.send(
      new DescribeThingGroupCommand({
        thingGroupName: groupName,
      }),
    )) as DescribeThingGroupCommandOutput

    if (isRigThingGroupQuery(description.queryString)) {
      rigNames.push(groupName)
    }
  }

  return sortUnique(rigNames)
}

export const listRigThingGroups = async (resolveIdToken: ResolveIdToken): Promise<string[]> => {
  const client = await createIotControlClient(resolveIdToken)
  return listRigThingGroupsWithClient(client)
}

export const listRigDevicesWithClient = async (
  client: IotControlClient,
  rigName: string,
): Promise<string[]> => {
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

  return sortUnique(deviceIds)
}

export const listRigDevices = async (
  resolveIdToken: ResolveIdToken,
  rigName: string,
): Promise<string[]> => {
  const client = await createIotControlClient(resolveIdToken)
  return listRigDevicesWithClient(client, rigName)
}
