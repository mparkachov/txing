import { describe, expect, test } from 'bun:test'
import {
  buildGetShadowPublishPacket,
  buildShadowSubscriptionPacket,
  buildShadowTopics,
  buildUpdateShadowPublishPacket,
  classifyShadowTopic,
  createShadowClientToken,
  decodeShadowResponse,
  deriveMqttHostFromIotDataEndpoint,
} from '../src/shadow-protocol'
import { mergeShadowUpdate } from '../src/shadow-merge'

const decoder = new TextDecoder()

describe('shadow protocol helpers', () => {
  test('derives the MQTT host from the IoT Data ATS endpoint', () => {
    expect(
      deriveMqttHostFromIotDataEndpoint('https://a1b2c3d4e5f6g7-ats.iot.eu-central-1.amazonaws.com'),
    ).toBe('a1b2c3d4e5f6g7-ats.iot.eu-central-1.amazonaws.com')
    expect(deriveMqttHostFromIotDataEndpoint('a1b2c3d4e5f6g7-ats.iot.eu-central-1.amazonaws.com')).toBe(
      'a1b2c3d4e5f6g7-ats.iot.eu-central-1.amazonaws.com',
    )
  })

  test('builds the exact classic shadow topics', () => {
    expect(buildShadowTopics('txing')).toEqual({
      get: '$aws/things/txing/shadow/get',
      getAccepted: '$aws/things/txing/shadow/get/accepted',
      getRejected: '$aws/things/txing/shadow/get/rejected',
      update: '$aws/things/txing/shadow/update',
      updateAccepted: '$aws/things/txing/shadow/update/accepted',
      updateRejected: '$aws/things/txing/shadow/update/rejected',
    })
  })

  test('creates unique client tokens per request', () => {
    const firstToken = createShadowClientToken('get')
    const secondToken = createShadowClientToken('get')

    expect(firstToken).toStartWith('get-')
    expect(secondToken).toStartWith('get-')
    expect(firstToken).not.toBe(secondToken)
  })

  test('builds the accepted and rejected topic subscriptions', () => {
    const topics = buildShadowTopics('txing')
    const packet = buildShadowSubscriptionPacket(topics)

    expect(packet.subscriptions.map((subscription) => subscription.topicFilter)).toEqual([
      topics.getAccepted,
      topics.getRejected,
      topics.updateAccepted,
      topics.updateRejected,
    ])
  })

  test('builds get and update publish packets with client tokens', () => {
    const topics = buildShadowTopics('txing')
    const getPacket = buildGetShadowPublishPacket(topics, 'get-token')
    const updatePacket = buildUpdateShadowPublishPacket(
      topics,
      {
        state: {
          desired: {
            mcu: {
              power: true,
            },
          },
        },
      },
      'update-token',
    )

    expect(getPacket.topicName).toBe(topics.get)
    expect(decoder.decode(getPacket.payload as Uint8Array)).toContain('"clientToken":"get-token"')
    expect(updatePacket.topicName).toBe(topics.update)
    expect(decoder.decode(updatePacket.payload as Uint8Array)).toContain('"clientToken":"update-token"')
  })

  test('reduces accepted and rejected shadow messages', () => {
    const topics = buildShadowTopics('txing')
    const acceptedPayload = new TextEncoder().encode(
      JSON.stringify({
        clientToken: 'request-1',
        state: {
          reported: {
            board: {
              power: true,
            },
          },
        },
      }),
    )
    const rejectedPayload = new TextEncoder().encode(
      JSON.stringify({
        clientToken: 'request-2',
        message: 'Not authorized',
      }),
    )

    expect(classifyShadowTopic(topics.getAccepted, topics)).toBe('getAccepted')
    expect(classifyShadowTopic(topics.updateRejected, topics)).toBe('updateRejected')
    expect(classifyShadowTopic('random/topic', topics)).toBe('ignored')

    expect(decodeShadowResponse(topics.getAccepted, acceptedPayload, topics)).toEqual({
      kind: 'getAccepted',
      operation: 'get',
      payload: {
        clientToken: 'request-1',
        state: {
          reported: {
            board: {
              power: true,
            },
          },
        },
      },
      clientToken: 'request-1',
    })

    expect(decodeShadowResponse(topics.updateRejected, rejectedPayload, topics)).toEqual({
      kind: 'updateRejected',
      operation: 'update',
      payload: {
        clientToken: 'request-2',
        message: 'Not authorized',
      },
      clientToken: 'request-2',
    })
  })

  test('merges partial update-accepted payloads into the last full shadow snapshot', () => {
    const currentShadow = {
      state: {
        reported: {
          batteryMv: 3729,
          mcu: {
            power: false,
            ble: {
              serviceUuid: 'svc',
              sleepCommandUuid: 'sleep',
              stateReportUuid: 'report',
              online: false,
              deviceId: 'AA:BB',
            },
          },
        },
      },
      metadata: {
        reported: {
          batteryMv: { timestamp: 2 },
          mcu: {
            power: { timestamp: 1 },
            ble: {
              online: { timestamp: 3 },
            },
          },
        },
      },
      version: 10,
      timestamp: 100,
    }

    const updateAcceptedPayload = {
      state: {
        reported: {
          mcu: {
            ble: {
              online: true,
            },
          },
        },
      },
      metadata: {
        reported: {
          mcu: {
            ble: {
              online: { timestamp: 4 },
            },
          },
        },
      },
      version: 11,
      timestamp: 110,
    }

    expect(mergeShadowUpdate(currentShadow, updateAcceptedPayload)).toEqual({
      state: {
        reported: {
          batteryMv: 3729,
          mcu: {
            power: false,
            ble: {
              serviceUuid: 'svc',
              sleepCommandUuid: 'sleep',
              stateReportUuid: 'report',
              online: true,
              deviceId: 'AA:BB',
            },
          },
        },
      },
      metadata: {
        reported: {
          batteryMv: { timestamp: 2 },
          mcu: {
            power: { timestamp: 1 },
            ble: {
              online: { timestamp: 4 },
            },
          },
        },
      },
      version: 11,
      timestamp: 110,
    })
  })
})
