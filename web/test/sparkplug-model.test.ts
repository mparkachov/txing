import { describe, expect, test } from 'bun:test'
import {
  extractSparkplugCapabilityAvailability,
  extractSparkplugRedconCommandStatus,
} from '../src/sparkplug-model'

describe('sparkplug model helpers', () => {
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
})
