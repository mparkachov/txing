import { PublishCommand, IoTDataPlaneClient } from '@aws-sdk/client-iot-data-plane'
import { clearCredentialProviderCache, createCredentialProvider } from './aws-credentials'
import {
  isThingShadowReadForbiddenError,
  type ThingMetadata,
} from './catalog-api'
import { appConfig } from './config'
import { ensureIotPolicyAttached } from './iot-policy-attach'
import { buildIotDataEndpointUrl, resolveIotDataEndpoint } from './iot-endpoint'
import {
  buildSparkplugRedconCommandPacket,
  buildSparkplugTopics,
} from './sparkplug-protocol'
import type { ShadowSession } from './shadow-api'

type ResolveIdToken = () => Promise<string>
type IotDataClient = Pick<IoTDataPlaneClient, 'send'>

export type SparkplugRedconCommandTarget = {
  groupId: string
  edgeNodeId: string
  deviceId: string
}

const createIotDataClient = async (
  resolveIdToken: ResolveIdToken,
): Promise<IotDataClient> => {
  const idToken = await resolveIdToken()
  await ensureIotPolicyAttached(idToken)
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

export const resolveThingSparkplugRedconCommandTarget = (
  metadata: Pick<ThingMetadata, 'thingName' | 'thingTypeName' | 'townName' | 'rigName'> | null,
): SparkplugRedconCommandTarget | null => {
  if (
    !metadata ||
    metadata.thingTypeName === 'town' ||
    metadata.thingTypeName === 'rig' ||
    !metadata.townName ||
    !metadata.rigName
  ) {
    return null
  }

  return {
    groupId: metadata.townName,
    edgeNodeId: metadata.rigName,
    deviceId: metadata.thingName,
  }
}

export const publishDirectSparkplugRedconCommandWithClient = async (
  client: IotDataClient,
  target: SparkplugRedconCommandTarget,
  redcon: 1 | 2 | 3 | 4,
  seq = 0,
): Promise<void> => {
  const packet = buildSparkplugRedconCommandPacket(
    buildSparkplugTopics(target.groupId, target.edgeNodeId, target.deviceId),
    redcon,
    seq,
  )
  await client.send(
    new PublishCommand({
      topic: packet.topicName,
      qos: packet.qos,
      payload: packet.payload,
    }),
  )
}

export const publishDirectSparkplugRedconCommand = async (
  resolveIdToken: ResolveIdToken,
  target: SparkplugRedconCommandTarget,
  redcon: 1 | 2 | 3 | 4,
  seq = 0,
): Promise<void> => {
  const publishOnce = async (): Promise<void> => {
    const client = await createIotDataClient(resolveIdToken)
    await publishDirectSparkplugRedconCommandWithClient(client, target, redcon, seq)
  }

  try {
    await publishOnce()
  } catch (caughtError) {
    if (!isThingShadowReadForbiddenError(caughtError)) {
      throw caughtError
    }
    clearCredentialProviderCache()
    await publishOnce()
  }
}

export const publishSparkplugRedconCommandWithAck = async (
  session: Pick<ShadowSession, 'publishRedconCommand'>,
  redcon: 1 | 2 | 3 | 4,
): Promise<void> => {
  await session.publishRedconCommand(redcon)
}
