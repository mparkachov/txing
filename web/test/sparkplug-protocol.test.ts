import { describe, expect, test } from 'bun:test'
import {
  buildSparkplugRedconCommandPacket,
  buildSparkplugTopics,
  decodeSparkplugPayload,
} from '../src/sparkplug-protocol'

describe('sparkplug protocol helpers', () => {
  test('builds the expected sparkplug topics', () => {
    expect(buildSparkplugTopics('town', 'rig', 'txing')).toEqual({
      nbirth: 'spBv1.0/town/NBIRTH/rig',
      ndata: 'spBv1.0/town/NDATA/rig',
      dcmd: 'spBv1.0/town/DCMD/rig/txing',
      dbirth: 'spBv1.0/town/DBIRTH/rig/txing',
      ddata: 'spBv1.0/town/DDATA/rig/txing',
      ddeath: 'spBv1.0/town/DDEATH/rig/txing',
    })
  })

  test('encodes a redcon command payload using sparkplug protobuf fields', () => {
    const topics = buildSparkplugTopics('town', 'rig', 'txing')
    const packet = buildSparkplugRedconCommandPacket(topics, 3, 7, 12345)
    const decoded = decodeSparkplugPayload(packet.payload)

    expect(packet.topicName).toBe('spBv1.0/town/DCMD/rig/txing')
    expect(decoded.timestamp).toBe(12345)
    expect(decoded.seq).toBe(7)
    expect(decoded.metrics).toEqual([
      {
        name: 'redcon',
        datatype: 3,
        intValue: 3,
        longValue: null,
        timestamp: null,
      },
    ])
  })
})
