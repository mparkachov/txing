import { describe, expect, test } from 'bun:test'
import {
  buildBoardVideoChannelName,
  describeRedcon,
  deriveTxingPowerTransitionPending,
  deriveTxingPoweredOn,
  extractReportedBatteryMv,
  extractReportedMcuOnline,
  extractReportedRedcon,
  getTrackIndicatorPresentation,
  getTxingRedconToneClass,
} from '../src/app-model'

describe('app model helpers', () => {
  test('extracts top-level reported redcon from shadow state', () => {
    expect(
      extractReportedRedcon({
        state: {
          reported: {
            redcon: 2,
          },
        },
      }),
    ).toBe(2)
    expect(extractReportedRedcon({ state: { reported: { redcon: 7 } } })).toBeNull()
  })

  test('extracts reported redcon from sparkplug named shadow first', () => {
    expect(
      extractReportedRedcon({
        state: {
          reported: {
            redcon: 4,
          },
        },
        namedShadows: {
          sparkplug: {
            state: {
              reported: {
                redcon: 2,
              },
            },
          },
        },
      }),
    ).toBe(2)
  })

  test('extracts nested reported battery from reported.device', () => {
    expect(
      extractReportedBatteryMv({
        state: {
          reported: {
            device: {
              batteryMv: 3972,
            },
          },
        },
      }),
    ).toBe(3972)

    expect(
      extractReportedBatteryMv({
        state: {
          reported: {
            batteryMv: 3901,
          },
        },
      }),
    ).toBeNull()
  })

  test('maps redcon values to txing label tone classes and descriptions', () => {
    expect(getTxingRedconToneClass(1)).toBe('status-txing-redcon-1')
    expect(getTxingRedconToneClass(2)).toBe('status-txing-redcon-2')
    expect(getTxingRedconToneClass(3)).toBe('status-txing-redcon-3')
    expect(getTxingRedconToneClass(4)).toBe('status-txing-redcon-4')
    expect(getTxingRedconToneClass(null)).toBe('status-txing-redcon-unknown')

    expect(describeRedcon(1)).toBe('REDCON 1 · Hot Rig · Red')
    expect(describeRedcon(2)).toBe('REDCON 2 · Ember Watch · Orange')
    expect(describeRedcon(3)).toBe('REDCON 3 · Torch-Up · Yellow')
    expect(describeRedcon(4)).toBe('REDCON 4 · Cold Camp · Green')
    expect(describeRedcon(null)).toBe('REDCON unavailable')
  })

  test('maps track values to tone and intensity for header indicators', () => {
    expect(getTrackIndicatorPresentation(60, 'Left')).toEqual({
      toneClass: 'status-track-forward',
      intensity: 0.6,
      ariaLabel: 'Left track forward 60 percent',
    })
    expect(getTrackIndicatorPresentation(-30, 'Right')).toEqual({
      toneClass: 'status-track-reverse',
      intensity: 0.3,
      ariaLabel: 'Right track reverse 30 percent',
    })
    expect(getTrackIndicatorPresentation(0, 'Left')).toEqual({
      toneClass: 'status-track-idle',
      intensity: 0,
      ariaLabel: 'Left track idle',
    })
  })

  test('extracts reported mcu online from nested reported.device state', () => {
    const shadow = {
      state: {
        reported: {
          device: {
            mcu: {
              online: true,
            },
          },
        },
      },
    }

    expect(extractReportedMcuOnline(shadow)).toBe(true)
  })

  test('derives txing power from redcon first and falls back to reported flags', () => {
    expect(
      deriveTxingPoweredOn({
        reportedRedcon: 4,
        reportedMcuPower: true,
        reportedBoardPower: true,
        reportedBoardWifiOnline: true,
      }),
    ).toBe(false)

    expect(
      deriveTxingPoweredOn({
        reportedRedcon: 2,
        reportedMcuPower: false,
        reportedBoardPower: false,
        reportedBoardWifiOnline: false,
      }),
    ).toBe(true)

    expect(
      deriveTxingPoweredOn({
        reportedRedcon: null,
        reportedMcuPower: false,
        reportedBoardPower: true,
        reportedBoardWifiOnline: false,
      }),
    ).toBe(true)
  })

  test('derives txing switch pending from local target redcon and reported posture', () => {
    expect(
      deriveTxingPowerTransitionPending({
        targetRedcon: 3,
        reportedRedcon: 4,
      }),
    ).toBe(true)

    expect(
      deriveTxingPowerTransitionPending({
        targetRedcon: 4,
        reportedRedcon: 2,
      }),
    ).toBe(true)

    expect(
      deriveTxingPowerTransitionPending({
        targetRedcon: 2,
        reportedRedcon: 3,
      }),
    ).toBe(true)

    expect(
      deriveTxingPowerTransitionPending({
        targetRedcon: null,
        reportedRedcon: 4,
      }),
    ).toBe(false)

    expect(
      deriveTxingPowerTransitionPending({
        targetRedcon: 4,
        reportedRedcon: 4,
      }),
    ).toBe(false)
  })

  test('builds board video channel names from device ids', () => {
    expect(buildBoardVideoChannelName('unit-a7k2p9')).toBe('unit-a7k2p9-board-video')
  })
})
