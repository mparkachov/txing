import { describe, expect, test } from 'bun:test'
import {
  buildSparkplugNodeRedconCommandPacket,
  buildSparkplugNodeTopics,
  buildSparkplugRedconCommandPacket,
  buildSparkplugTopics,
  buildVirtualQuadCommandPacket,
  decodeSparkplugPayload,
  encodeSparkplugPayload,
  SparkplugDataType,
} from '../src/sparkplug-protocol'

describe('sparkplug protocol helpers', () => {
  test('encodes virtual quad commands for the controller without rounding the revision', () => {
    const topics = buildSparkplugTopics('town-test', 'cloud-test', 'virtual-quad-test')
    const start = buildVirtualQuadCommandPacket(topics, {
      requestId: '00000000-0000-4000-8000-000000000001',
      redcon: 1,
      terminalRevision: Number.MAX_SAFE_INTEGER,
    }, 25, 1000)
    const stop = buildVirtualQuadCommandPacket(topics, {
      requestId: '00000000-0000-4000-8000-000000000002',
      redcon: 4,
      sessionId: 'SESSION_TEST',
    }, 25, 1000)
    expect(start.topicName).toBe(topics.dcmd)
    expect(Buffer.from(start.payload).toString('base64')).toBe(
      'COgHEgwKBnJlZGNvbiADUAESPwoVdmlydHVhbFF1YWQucmVxdWVzdElkIAx6JDAwMDAwMDAwLTAwMDAtNDAwMC04MDAwLTAwMDAwMDAwMDAwMRIyChx2aXJ0dWFsUXVhZC50ZXJtaW5hbFJldmlzaW9uIAx6EDkwMDcxOTkyNTQ3NDA5OTEYGQ==',
    )
    expect(Buffer.from(stop.payload).toString('base64')).toBe(
      'COgHEgwKBnJlZGNvbiADUAQSPwoVdmlydHVhbFF1YWQucmVxdWVzdElkIAx6JDAwMDAwMDAwLTAwMDAtNDAwMC04MDAwLTAwMDAwMDAwMDAwMhInChV2aXJ0dWFsUXVhZC5zZXNzaW9uSWQgDHoMU0VTU0lPTl9URVNUGBk=',
    )
  })

  test('builds the expected sparkplug topics', () => {
    expect(buildSparkplugTopics('town', 'rig', 'txing')).toEqual({
      nbirth: 'spBv1.0/town/NBIRTH/rig',
      ndata: 'spBv1.0/town/NDATA/rig',
      ncmd: 'spBv1.0/town/NCMD/rig',
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
        floatValue: null,
        doubleValue: null,
        boolValue: null,
        stringValue: null,
        timestamp: null,
      },
    ])
  })

  test('encodes a node redcon command payload for NCMD', () => {
    const topics = buildSparkplugNodeTopics('town', 'rig')
    const packet = buildSparkplugNodeRedconCommandPacket(topics, 4, 8, 12345)
    const decoded = decodeSparkplugPayload(packet.payload)

    expect(packet.topicName).toBe('spBv1.0/town/NCMD/rig')
    expect(decoded.timestamp).toBe(12345)
    expect(decoded.seq).toBe(8)
    expect(decoded.metrics).toEqual([
      expect.objectContaining({
        name: 'redcon',
        intValue: 4,
      }),
    ])
  })

  test('decodes boolean and string metrics', () => {
    const payload = encodeSparkplugPayload({
      timestamp: 100,
      seq: 2,
      metrics: [
        {
          name: 'services/demo/available',
          datatype: SparkplugDataType.Boolean,
          boolValue: true,
        },
        {
          name: 'services/demo/transport',
          datatype: SparkplugDataType.String,
          stringValue: 'mqtt-jsonrpc',
        },
      ],
    })
    const decoded = decodeSparkplugPayload(payload)
    expect(decoded.metrics).toEqual([
      {
        name: 'services/demo/available',
        datatype: 11,
        intValue: null,
        longValue: null,
        floatValue: null,
        doubleValue: null,
        boolValue: true,
        stringValue: null,
        timestamp: null,
      },
      {
        name: 'services/demo/transport',
        datatype: 12,
        intValue: null,
        longValue: null,
        floatValue: null,
        doubleValue: null,
        boolValue: null,
        stringValue: 'mqtt-jsonrpc',
        timestamp: null,
      },
    ])
  })

  test('encodes and decodes double weather metrics', () => {
    const payload = encodeSparkplugPayload({
      timestamp: 100,
      seq: 3,
      metrics: [
        {
          name: 'measuredTemperature',
          datatype: SparkplugDataType.Double,
          doubleValue: 21.625,
        },
      ],
    })
    const decoded = decodeSparkplugPayload(payload)
    expect(decoded.metrics).toEqual([
      {
        name: 'measuredTemperature',
        datatype: 10,
        intValue: null,
        longValue: null,
        floatValue: null,
        doubleValue: 21.625,
        boolValue: null,
        stringValue: null,
        timestamp: null,
      },
    ])
  })
})
