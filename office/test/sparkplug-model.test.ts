import { describe, expect, test } from 'bun:test'
import {
  extractIsSparkplugUnavailable,
  extractReportedRedcon,
  extractSparkplugCapabilityAvailability,
  extractSparkplugRedconCommandStatus,
  shouldClearPendingTargetRedcon,
} from '../src/sparkplug-model'
import agentShadowExample from '../../devices/tbot/aws/fixtures/agent-shadow.json'

describe('sparkplug model helpers', () => {
  test('optional agent status cannot alter device REDCON or capability availability', () => {
    const sparkplug = {
      state: { reported: {
        topic: { messageType: 'DDATA', deviceId: 'tbot-example' },
        payload: { metrics: { redcon: 2, capability: { mavlink: true, video: false } } },
      } },
    }
    for (const agent of [undefined, agentShadowExample, { state: { reported: { lifecycle: { state: 'error' } } } }]) {
      const shadow = { namedShadows: { sparkplug, agent } }
      expect(extractReportedRedcon(shadow)).toBe(2)
      expect(extractSparkplugCapabilityAvailability(shadow, 'mavlink')).toBe(true)
      expect(extractSparkplugCapabilityAvailability(shadow, 'video')).toBe(false)
      expect(extractSparkplugCapabilityAvailability(shadow, 'agent')).toBeNull()
    }
    expect(extractReportedRedcon({ namedShadows: { agent: agentShadowExample } })).toBeNull()
  })

  test('extracts redcon command failure status from sparkplug metrics', () => {
    expect(
      extractSparkplugRedconCommandStatus({
        namedShadows: {
          sparkplug: {
            state: {
              reported: {
                payload: {
                  metrics: {
                    redcon: 4,
                    redconCommandStatus: 'failed',
                    redconCommandSeq: 12,
                    redconCommandTarget: 3,
                    redconCommandMessage: 'weather BLE command deadline expired',
                  },
                },
              },
            },
          },
        },
      }),
    ).toEqual({
      status: 'failed',
      seq: 12,
      targetRedcon: 3,
      message: 'weather BLE command deadline expired',
    })
  })

  test('ignores invalid redcon command status metrics', () => {
    expect(
      extractSparkplugRedconCommandStatus({
        state: {
          reported: {
            payload: {
              metrics: {
                redconCommandStatus: 'waiting',
                redconCommandSeq: -1,
              },
            },
          },
        },
      }),
    ).toBeNull()
  })

  test('treats node and device death as unavailable', () => {
    expect(
      extractIsSparkplugUnavailable({
        state: {
          reported: {
            topic: {
              messageType: 'NDEATH',
            },
            payload: {
              metrics: {
                redcon: 4,
              },
            },
          },
        },
      }),
    ).toBe(true)
    expect(
      extractIsSparkplugUnavailable({
        state: {
          reported: {
            topic: {
              deviceId: 'unit-a1',
              messageType: 'DDEATH',
            },
            payload: {
              metrics: {},
            },
          },
        },
      }),
    ).toBe(true)
  })

  test('extracts capability availability from sparkplug metrics', () => {
    const shadow = {
      state: {
        reported: {
          payload: {
            metrics: {
              capability: {
                sparkplug: true,
                mcu: true,
                board: false,
              },
            },
          },
        },
      },
    }

    expect(extractSparkplugCapabilityAvailability(shadow, 'sparkplug')).toBe(true)
    expect(extractSparkplugCapabilityAvailability(shadow, 'mcu')).toBe(true)
    expect(extractSparkplugCapabilityAvailability(shadow, 'board')).toBe(false)
    expect(extractSparkplugCapabilityAvailability(shadow, 'video')).toBeNull()
  })

  test('derives sparkplug availability from node redcon when capability metric is absent', () => {
    expect(
      extractSparkplugCapabilityAvailability(
        {
          state: {
            reported: {
              topic: {
                messageType: 'NDATA',
              },
              payload: {
                metrics: {
                  redcon: 1,
                },
              },
            },
          },
        },
        'sparkplug',
      ),
    ).toBe(true)
    expect(
      extractSparkplugCapabilityAvailability(
        {
          state: {
            reported: {
              topic: {
                messageType: 'NDEATH',
              },
              payload: {
                metrics: {
                  redcon: 4,
                },
              },
            },
          },
        },
        'sparkplug',
      ),
    ).toBe(false)
  })

  test('treats device death capabilities as inactive', () => {
    expect(
      extractSparkplugCapabilityAvailability(
        {
          state: {
            reported: {
              topic: {
                deviceId: 'unit-a1',
                messageType: 'DDEATH',
              },
              payload: {
                metrics: {
                  capability: {
                    sparkplug: true,
                  },
                },
              },
            },
          },
        },
        'sparkplug',
      ),
    ).toBe(false)
  })

  test('keeps wake redcon commands pending through transient device death', () => {
    expect(
      shouldClearPendingTargetRedcon({
        pendingTargetRedcon: 1,
        reportedRedcon: 1,
        isSparkplugDeviceUnavailable: false,
      }),
    ).toBe(false)

    expect(
      shouldClearPendingTargetRedcon({
        pendingTargetRedcon: 1,
        reportedRedcon: null,
        isSparkplugDeviceUnavailable: true,
      }),
    ).toBe(false)

    expect(
      shouldClearPendingTargetRedcon({
        pendingTargetRedcon: 4,
        reportedRedcon: null,
        isSparkplugDeviceUnavailable: true,
      }),
    ).toBe(true)
  })
})
