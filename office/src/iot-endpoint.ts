import { DescribeEndpointCommand, IoTClient } from '@aws-sdk/client-iot'
import { createCredentialProvider } from './aws-credentials'

const AWS_IOT_DATA_ENDPOINT_TYPE = 'iot:Data-ATS'

type EndpointAddressClient = {
  send: (command: DescribeEndpointCommand) => Promise<{ endpointAddress?: string }>
}

type ResolveIotDataEndpointOptions = {
  region: string
  idToken: string
  createClient?: (idToken: string) => EndpointAddressClient
}

const resolvedEndpointsByRegion = new Map<string, string>()
const pendingEndpointsByRegion = new Map<string, Promise<string>>()

export const buildIotDataEndpointUrl = (endpointAddress: string): string => {
  const normalizedEndpointAddress = endpointAddress.trim()
  if (!normalizedEndpointAddress) {
    throw new Error('AWS IoT data endpoint must not be empty')
  }
  return normalizedEndpointAddress.includes('://')
    ? normalizedEndpointAddress
    : `https://${normalizedEndpointAddress}`
}

const buildDefaultClient = (region: string, idToken: string): EndpointAddressClient =>
  new IoTClient({
    region,
    credentials: createCredentialProvider(idToken),
  })

export const resolveIotDataEndpoint = async ({
  region,
  idToken,
  createClient = (nextIdToken) => buildDefaultClient(region, nextIdToken),
}: ResolveIotDataEndpointOptions): Promise<string> => {
  const cachedEndpoint = resolvedEndpointsByRegion.get(region)
  if (cachedEndpoint) {
    return cachedEndpoint
  }

  const pendingEndpoint = pendingEndpointsByRegion.get(region)
  if (pendingEndpoint) {
    return pendingEndpoint
  }

  const endpointPromise = (async () => {
    const client = createClient(idToken)
    const response = await client.send(
      new DescribeEndpointCommand({
        endpointType: AWS_IOT_DATA_ENDPOINT_TYPE,
      }),
    )
    const endpointAddress = response.endpointAddress?.trim()
    if (!endpointAddress) {
      throw new Error('AWS IoT DescribeEndpoint did not return a valid endpointAddress')
    }

    resolvedEndpointsByRegion.set(region, endpointAddress)
    return endpointAddress
  })().finally(() => {
    pendingEndpointsByRegion.delete(region)
  })

  pendingEndpointsByRegion.set(region, endpointPromise)
  return endpointPromise
}

export const resetIotDataEndpointCacheForTest = (): void => {
  resolvedEndpointsByRegion.clear()
  pendingEndpointsByRegion.clear()
}
