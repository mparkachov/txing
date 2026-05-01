import { describe, expect, test } from 'bun:test'
import {
  buildBoardVideoChannelName,
  describeRedcon,
  deriveTxingPowerTransitionPending,
  deriveTxingPoweredOn,
  extractIsSparkplugDeviceUnavailable,
  extractReportedBatteryMv,
  extractReportedMcuOnline,
  extractReportedRedcon,
  extractSparkplugMessageType,
  hasReachedTargetRedcon,
  getTrackIndicatorPresentation,
  getTxingRedconToneClass,
  shouldClearPendingTargetRedcon,
} from '../../devices/unit/web/app-model'

describe('app model helpers', () => {
  test('extracts top-level reported redcon from shadow state', () => {
    expect(
      extractReportedRedcon({
        state: {
          reported: {
            payload: {
              metrics: {
                redcon: 2,
              },
            },
          },
        },
      }),
    ).toBe(2)
    expect(
      extractReportedRedcon({
        state: {
          reported: {
            payload: {
              metrics: {
                redcon: 7,
              },
            },
          },
        },
      }),
    ).toBeNull()
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
                payload: {
                  metrics: {
                    redcon: 2,
                  },
                },
              },
            },
          },
        },
      }),
    ).toBe(2)
  })

  test('extracts node reported redcon from a top-level sparkplug metric', () => {
    expect(
      extractReportedRedcon({
        namedShadows: {
          sparkplug: {
            state: {
              reported: {
                topic: {
                  namespace: 'spBv1.0',
                  groupId: 'town',
                  messageType: 'NDATA',
                  edgeNodeId: 'rig',
                },
                payload: {
                  metrics: {
                    redcon: 1,
                  },
                },
              },
            },
          },
        },
      }),
    ).toBe(1)
  })

  test('reads node death redcon only from sparkplug payload metrics', () => {
    expect(
      extractReportedRedcon({
        namedShadows: {
          sparkplug: {
            state: {
              reported: {
                topic: {
                  namespace: 'spBv1.0',
                  groupId: 'town',
                  messageType: 'NDEATH',
                  edgeNodeId: 'rig',
                },
                payload: {
                  metrics: {
                    redcon: 4,
                  },
                },
              },
            },
          },
        },
      }),
    ).toBe(4)
  })

  test('treats device death redcon as unavailable even if a legacy metric is present', () => {
    expect(
      extractReportedRedcon({
        namedShadows: {
          sparkplug: {
            state: {
              reported: {
                topic: {
                  namespace: 'spBv1.0',
                  groupId: 'town',
                  edgeNodeId: 'rig',
                  deviceId: 'unit-a1',
                  messageType: 'DDEATH',
                },
                payload: {
                  metrics: {
                    redcon: 4,
                  },
                },
              },
            },
          },
        },
      }),
    ).toBeNull()
  })

  test('does not derive redcon from sparkplug message type when metric is absent', () => {
    expect(
      extractReportedRedcon({
        namedShadows: {
          sparkplug: {
            state: {
              reported: {
                topic: {
                  namespace: 'spBv1.0',
                  groupId: 'town',
                  edgeNodeId: 'rig',
                  deviceId: 'unit-a1',
                  messageType: 'DDEATH',
                },
                payload: {
                  metrics: {},
                },
              },
            },
          },
        },
      }),
    ).toBeNull()
  })

  test('extracts sparkplug message type and device availability separately', () => {
    const deviceDeathShadow = {
      namedShadows: {
        sparkplug: {
          state: {
            reported: {
              topic: {
                namespace: 'spBv1.0',
                groupId: 'town',
                edgeNodeId: 'rig',
                deviceId: 'unit-a1',
                messageType: 'DDEATH',
              },
              payload: {
                metrics: {},
              },
            },
          },
        },
      },
    }

    expect(extractSparkplugMessageType(deviceDeathShadow)).toBe('DDEATH')
    expect(extractIsSparkplugDeviceUnavailable(deviceDeathShadow)).toBe(true)
    expect(
      extractIsSparkplugDeviceUnavailable({
        namedShadows: {
          sparkplug: {
            state: {
              reported: {
                topic: {
                  namespace: 'spBv1.0',
                  groupId: 'town',
                  edgeNodeId: 'rig',
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
        },
      }),
    ).toBe(false)
  })

  test('extracts nested reported battery from reported.device', () => {
    expect(
      extractReportedBatteryMv({
        state: {
          reported: {
            payload: {
              metrics: {
                batteryMv: 3972,
              },
            },
          },
        },
      }),
    ).toBe(3972)

    expect(
      extractReportedBatteryMv({
        state: {
          reported: {
            device: {
              batteryMv: 3901,
            },
          },
        },
      }),
    ).toBeNull()
  })

  test('treats device death battery as unavailable even if a legacy metric is present', () => {
    expect(
      extractReportedBatteryMv({
        namedShadows: {
          sparkplug: {
            state: {
              reported: {
                topic: {
                  namespace: 'spBv1.0',
                  groupId: 'town',
                  edgeNodeId: 'rig',
                  deviceId: 'unit-a1',
                  messageType: 'DDEATH',
                },
                payload: {
                  metrics: {
                    batteryMv: 3901,
                  },
                },
              },
            },
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

    expect(
      deriveTxingPoweredOn({
        isSparkplugDeviceUnavailable: true,
        reportedRedcon: null,
        reportedMcuPower: true,
        reportedBoardPower: true,
        reportedBoardWifiOnline: true,
      }),
    ).toBe(false)
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

  test('clears pending redcon state on convergence or device death', () => {
    expect(
      shouldClearPendingTargetRedcon({
        pendingTargetRedcon: 3,
        reportedRedcon: 3,
        isSparkplugDeviceUnavailable: false,
      }),
    ).toBe(true)

    expect(
      shouldClearPendingTargetRedcon({
        pendingTargetRedcon: 4,
        reportedRedcon: null,
        isSparkplugDeviceUnavailable: true,
      }),
    ).toBe(true)

    expect(
      shouldClearPendingTargetRedcon({
        pendingTargetRedcon: 2,
        reportedRedcon: 4,
        isSparkplugDeviceUnavailable: false,
      }),
    ).toBe(false)
  })

  test('detects when the reported sparkplug redcon has reached the target', () => {
    expect(
      hasReachedTargetRedcon({
        targetRedcon: 1,
        reportedRedcon: 3,
      }),
    ).toBe(false)

    expect(
      hasReachedTargetRedcon({
        targetRedcon: 1,
        reportedRedcon: 1,
      }),
    ).toBe(true)

    expect(
      hasReachedTargetRedcon({
        targetRedcon: 4,
        reportedRedcon: 3,
      }),
    ).toBe(false)

    expect(
      hasReachedTargetRedcon({
        targetRedcon: 4,
        reportedRedcon: 4,
      }),
    ).toBe(true)

    expect(
      hasReachedTargetRedcon({
        targetRedcon: 2,
        reportedRedcon: null,
      }),
    ).toBe(false)
  })

  test('builds board video channel names from device ids', () => {
    expect(buildBoardVideoChannelName('unit-a7k2p9')).toBe('unit-a7k2p9-board-video')
  })
})
