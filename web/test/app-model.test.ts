import { describe, expect, test } from 'bun:test'
import {
  buildBoardVideoChannelName,
  describeRedcon,
  deriveTxingPowerTransitionPending,
  deriveTxingPoweredOn,
  extractDesiredRedcon,
  extractReportedBatteryMv,
  extractDesiredBoardPower,
  extractReportedMcuOnline,
  extractReportedBoardDrive,
  extractReportedVideo,
  extractReportedRedcon,
  getTrackIndicatorPresentation,
  getTxingRedconToneClass,
  selectPrimaryReportedRedcon,
} from '../src/app-model'

describe('app model helpers', () => {
  test('extracts board video runtime metadata from shadow state', () => {
    const runtime = extractReportedVideo({
      state: {
        reported: {
          video: {
            ready: true,
            status: 'ready',
            transport: 'aws-webrtc',
            viewerConnected: true,
            lastError: null,
          },
        },
      },
    })

    expect(runtime.ready).toBe(true)
    expect(runtime.transport).toBe('aws-webrtc')
    expect(runtime.viewerConnected).toBe(true)
  })

  test('accepts unavailable board video status from reflected shadow cache', () => {
    const runtime = extractReportedVideo({
      state: {
        reported: {
          video: {
            ready: false,
            status: 'unavailable',
            transport: 'aws-webrtc',
            viewerConnected: false,
            lastError: null,
          },
        },
      },
    })

    expect(runtime.ready).toBe(false)
    expect(runtime.status).toBe('unavailable')
    expect(runtime.transport).toBe('aws-webrtc')
  })

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

  test('extracts top-level reported battery from shadow state', () => {
    expect(
      extractReportedBatteryMv({
        state: {
          reported: {
            batteryMv: 3972,
          },
        },
      }),
    ).toBe(3972)

    expect(
      extractReportedBatteryMv({
        state: {
          reported: {
            mcu: {
              batteryMv: 3901,
            },
          },
        },
      }),
    ).toBeNull()
  })

  test('extracts signed board track percentages from shadow state', () => {
    expect(
      extractReportedBoardDrive({
        state: {
          reported: {
            board: {
              drive: {
                leftSpeed: 60,
                rightSpeed: -30,
              },
            },
          },
        },
      }),
    ).toEqual({
      leftSpeed: 60,
      rightSpeed: -30,
    })

    expect(
      extractReportedBoardDrive({
        state: {
          reported: {
            board: {
              drive: {
                leftSpeed: 160,
                rightSpeed: 0,
              },
            },
          },
        },
      }),
    ).toEqual({
      leftSpeed: null,
      rightSpeed: 0,
    })
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

  test('extracts desired board power and reported mcu online from shadow state', () => {
    const shadow = {
      state: {
        desired: {
          board: {
            power: false,
          },
        },
        reported: {
          mcu: {
            online: true,
          },
        },
      },
    }

    expect(extractDesiredBoardPower(shadow)).toBe(false)
    expect(extractReportedMcuOnline(shadow)).toBe(true)
    expect(extractDesiredRedcon({ state: { desired: { redcon: 3 } } })).toBe(3)
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

  test('prefers Sparkplug REDCON and falls back to shadow REDCON before the first device packet', () => {
    expect(
      selectPrimaryReportedRedcon({
        sparkplugReportedRedcon: 1,
        shadowReportedRedcon: 3,
      }),
    ).toBe(1)

    expect(
      selectPrimaryReportedRedcon({
        sparkplugReportedRedcon: null,
        shadowReportedRedcon: 3,
      }),
    ).toBe(3)
  })

  test('derives txing switch pending from desired redcon and reported posture', () => {
    expect(
      deriveTxingPowerTransitionPending({
        desiredRedcon: 3,
        reportedRedcon: 4,
      }),
    ).toBe(true)

    expect(
      deriveTxingPowerTransitionPending({
        desiredRedcon: 4,
        reportedRedcon: 2,
      }),
    ).toBe(true)

    expect(
      deriveTxingPowerTransitionPending({
        desiredRedcon: 2,
        reportedRedcon: 3,
      }),
    ).toBe(true)

    expect(
      deriveTxingPowerTransitionPending({
        desiredRedcon: null,
        reportedRedcon: 4,
      }),
    ).toBe(false)

    expect(
      deriveTxingPowerTransitionPending({
        desiredRedcon: 4,
        reportedRedcon: 4,
      }),
    ).toBe(false)
  })

  test('builds board video channel names from device ids', () => {
    expect(buildBoardVideoChannelName('unit-a7k2p9')).toBe('unit-a7k2p9-board-video')
  })
})
