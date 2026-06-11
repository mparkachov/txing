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
  buildSparkplugNodeRedconCommandPacket,
  buildSparkplugNodeTopics,
  buildSparkplugRedconCommandPacket,
  buildSparkplugTopics,
} from './sparkplug-protocol'
import type { ShadowSession } from './shadow-api'

type ResolveIdToken = () => Promise<string>
type IotDataClient = Pick<IoTDataPlaneClient, 'send'>

export type SparkplugRedconCommandTarget = {
  kind: 'device'
  groupId: string
  edgeNodeId: string
  deviceId: string
} | {
  kind: 'node'
  groupId: string
  edgeNodeId: string
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
  metadata: Pick<ThingMetadata, 'thingName' | 'kind' | 'townId' | 'rigId'> | null,
): SparkplugRedconCommandTarget | null => {
  if (!metadata || !metadata.townId) {
    return null
  }
  if (metadata.kind === 'rigType') {
    return {
      kind: 'node',
      groupId: metadata.townId,
      edgeNodeId: metadata.thingName,
    }
  }
  if (metadata.kind !== 'deviceType' || !metadata.rigId) {
    return null
  }

  return {
    kind: 'device',
    groupId: metadata.townId,
    edgeNodeId: metadata.rigId,
    deviceId: metadata.thingName,
  }
}

export const sparkplugCommandTargetThingName = (
  target: SparkplugRedconCommandTarget,
): string => target.kind === 'device' ? target.deviceId : target.edgeNodeId

export const sparkplugCommandTargetMessageType = (
  target: SparkplugRedconCommandTarget,
): 'DCMD' | 'NCMD' => target.kind === 'device' ? 'DCMD' : 'NCMD'

export const publishDirectSparkplugRedconCommandWithClient = async (
  client: IotDataClient,
  target: SparkplugRedconCommandTarget,
  redcon: 1 | 2 | 3 | 4,
  seq = 0,
): Promise<void> => {
  const packet = target.kind === 'device'
    ? buildSparkplugRedconCommandPacket(
        buildSparkplugTopics(target.groupId, target.edgeNodeId, target.deviceId),
        redcon,
        seq,
      )
    : buildSparkplugNodeRedconCommandPacket(
        buildSparkplugNodeTopics(target.groupId, target.edgeNodeId),
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
