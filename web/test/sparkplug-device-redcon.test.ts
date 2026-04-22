import { describe, expect, test } from 'bun:test'
import {
  extractSparkplugDeviceBatteryMv,
  extractSparkplugDeviceRedconUpdate,
} from '../src/sparkplug-device-redcon'
import {
  buildSparkplugTopics,
  encodeSparkplugPayload,
  SparkplugDataType,
} from '../src/sparkplug-protocol'

describe('sparkplug device redcon extraction', () => {
  test('extracts REDCON from DBIRTH and DDATA payloads', () => {
    const topics = buildSparkplugTopics('town', 'rig', 'txing')
    const payload = encodeSparkplugPayload({
      timestamp: 101,
      seq: 7,
      metrics: [
        {
          name: 'redcon',
          datatype: SparkplugDataType.Int32,
          intValue: 2,
        },
      ],
    })

    expect(extractSparkplugDeviceRedconUpdate(topics.dbirth, payload, topics)).toEqual({
      redcon: 2,
      source: 'dbirth',
    })
    expect(extractSparkplugDeviceRedconUpdate(topics.ddata, payload, topics)).toEqual({
      redcon: 2,
      source: 'ddata',
    })
  })

  test('extracts battery millivolts from DBIRTH and DDATA payloads', () => {
    const topics = buildSparkplugTopics('town', 'rig', 'txing')
    const payload = encodeSparkplugPayload({
      timestamp: 101,
      seq: 7,
      metrics: [
        {
          name: 'batteryMv',
          datatype: SparkplugDataType.Int32,
          intValue: 3940,
        },
      ],
    })

    expect(extractSparkplugDeviceBatteryMv(topics.dbirth, payload, topics)).toBe(3940)
    expect(extractSparkplugDeviceBatteryMv(topics.ddata, payload, topics)).toBe(3940)
  })

  test('treats DDEATH as REDCON 4 even without decoding metrics', () => {
    const topics = buildSparkplugTopics('town', 'rig', 'txing')

    expect(
      extractSparkplugDeviceRedconUpdate(topics.ddeath, new Uint8Array([0xde, 0xad]), topics),
    ).toEqual({
      redcon: 4,
      source: 'ddeath',
    })
  })

  test('ignores Sparkplug device payloads without a valid redcon metric', () => {
    const topics = buildSparkplugTopics('town', 'rig', 'txing')
    const payload = encodeSparkplugPayload({
      timestamp: 101,
      seq: 8,
      metrics: [
        {
          name: 'batteryMv',
          datatype: SparkplugDataType.Int32,
          intValue: 3812,
        },
      ],
    })

    expect(extractSparkplugDeviceRedconUpdate(topics.ddata, payload, topics)).toBeNull()
  })
})
