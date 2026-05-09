import { describe, expect, test } from 'bun:test'
import powerDeviceAdapter from '../../devices/power/web/power-adapter'
import { extractPowerReportedState } from '../../devices/power/web/power-model'

describe('power adapter', () => {
  test('extracts battery metrics from sparkplug shadow', () => {
    const shadow = {
      namedShadows: {
        sparkplug: {
          state: {
            reported: {
              payload: {
                metrics: {
                  redcon: 4,
                  batteryMv: 3512,
                },
              },
            },
          },
        },
      },
    }

    expect(extractPowerReportedState(shadow)).toEqual({
      batteryMv: 3512,
    })
    expect(powerDeviceAdapter.extractTelemetry(shadow).reportedBatteryMv).toBe(3512)
  })
})
