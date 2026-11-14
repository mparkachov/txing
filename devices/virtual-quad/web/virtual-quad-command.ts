import type { DeviceCommandTarget } from '../../../office/src/device-adapter'
import { publishSparkplugPacket } from '../../../office/src/sparkplug-command'
import {
  buildSparkplugTopics,
  encodeSparkplugPayload,
  SparkplugDataType,
  type SparkplugPublishPacket,
  type SparkplugTopics,
} from '../../../office/src/sparkplug-protocol'

export type VirtualQuadCommand = {
  requestId: string
} & (
  | { redcon: 1; terminalRevision: number }
  | { redcon: 4; sessionId: string }
)

export const buildVirtualQuadCommandPacket = (
  topics: Pick<SparkplugTopics, 'dcmd'>,
  command: VirtualQuadCommand,
  seq: number,
  timestamp = Date.now(),
): SparkplugPublishPacket => {
  if (!/^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/i.test(command.requestId) ||
    !Number.isInteger(seq) || seq < 0 || seq > 0x7fffffff) {
    throw new Error('Invalid virtual quad command identity or sequence')
  }
  if (command.redcon === 1 && (!Number.isSafeInteger(command.terminalRevision) || command.terminalRevision < 0)) {
    throw new Error('Invalid terminal revision for Start')
  }
  if (command.redcon === 4 && !/^[A-Za-z0-9_-]{1,128}$/.test(command.sessionId)) {
    throw new Error('Invalid session ID for Stop')
  }

  return {
    topicName: topics.dcmd,
    qos: 1,
    payload: encodeSparkplugPayload({
      timestamp,
      seq,
      metrics: [
        { name: 'redcon', datatype: SparkplugDataType.Int32, intValue: command.redcon },
        { name: 'virtualQuad.requestId', datatype: SparkplugDataType.String, stringValue: command.requestId },
        command.redcon === 1
          ? { name: 'virtualQuad.terminalRevision', datatype: SparkplugDataType.String, stringValue: String(command.terminalRevision) }
          : { name: 'virtualQuad.sessionId', datatype: SparkplugDataType.String, stringValue: command.sessionId },
      ],
    }),
  }
}

export const publishVirtualQuadCommand = (
  resolveIdToken: () => Promise<string>,
  target: DeviceCommandTarget,
  command: VirtualQuadCommand,
  seq: number,
): Promise<void> => {
  const packet = buildVirtualQuadCommandPacket(
    buildSparkplugTopics(target.groupId, target.edgeNodeId, target.deviceId), command, seq,
  )
  return publishSparkplugPacket(resolveIdToken, packet)
}
