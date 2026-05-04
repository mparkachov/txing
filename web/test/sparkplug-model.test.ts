import { describe, expect, test } from 'bun:test'
import { extractSparkplugRedconCommandStatus } from '../src/sparkplug-model'

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
})
