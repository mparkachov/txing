import { describe, expect, test } from 'bun:test'
import {
  buildViewerUrlWithChannel,
  deriveTxingPowerTransitionPending,
  deriveTxingPoweredOn,
  extractDesiredBoardPower,
  extractDesiredMcuPower,
  extractReportedBoardVideo,
  extractReportedRedcon,
  getAppRoute,
  resolveViewerChannelName,
} from '../src/app-model'

describe('app model helpers', () => {
  test('detects dashboard and video routes', () => {
    expect(getAppRoute('/')).toBe('dashboard')
    expect(getAppRoute('/video')).toBe('video')
    expect(getAppRoute('/video/')).toBe('video')
    expect(getAppRoute('/video/extra')).toBe('dashboard')
  })

  test('extracts board video session metadata from shadow state', () => {
    const runtime = extractReportedBoardVideo({
      state: {
        reported: {
          board: {
            video: {
              ready: true,
              status: 'ready',
              transport: 'aws-webrtc',
              session: {
                viewerUrl: 'https://ops.example.com/txing/video',
                channelName: 'txing-board-video',
              },
              viewerConnected: true,
              lastError: null,
            },
          },
        },
      },
    })

    expect(runtime.ready).toBe(true)
    expect(runtime.transport).toBe('aws-webrtc')
    expect(runtime.viewerUrl).toBe('https://ops.example.com/txing/video')
    expect(runtime.channelName).toBe('txing-board-video')
    expect(runtime.viewerConnected).toBe(true)
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

  test('extracts desired mcu and board power from shadow state', () => {
    const shadow = {
      state: {
        desired: {
          mcu: {
            power: true,
          },
          board: {
            power: false,
          },
        },
      },
    }

    expect(extractDesiredMcuPower(shadow)).toBe(true)
    expect(extractDesiredBoardPower(shadow)).toBe(false)
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

  test('derives txing switch pending from desired state and reported posture', () => {
    expect(
      deriveTxingPowerTransitionPending({
        txingPoweredOn: false,
        desiredMcuPower: true,
        desiredBoardPower: null,
      }),
    ).toBe(true)

    expect(
      deriveTxingPowerTransitionPending({
        txingPoweredOn: true,
        desiredMcuPower: false,
        desiredBoardPower: null,
      }),
    ).toBe(true)

    expect(
      deriveTxingPowerTransitionPending({
        txingPoweredOn: true,
        desiredMcuPower: null,
        desiredBoardPower: false,
      }),
    ).toBe(true)

    expect(
      deriveTxingPowerTransitionPending({
        txingPoweredOn: false,
        desiredMcuPower: null,
        desiredBoardPower: null,
      }),
    ).toBe(false)
  })

  test('builds viewer urls with channel query parameters', () => {
    expect(
      buildViewerUrlWithChannel('https://ops.example.com/txing/video', 'txing-board-video'),
    ).toBe('https://ops.example.com/txing/video?channel=txing-board-video')
  })

  test('resolves channel from url first and falls back to shadow metadata', () => {
    expect(
      resolveViewerChannelName(
        'https://ops.example.com/txing/video?channel=from-url',
        'from-shadow',
      ),
    ).toBe('from-url')
    expect(
      resolveViewerChannelName(
        'https://ops.example.com/txing/video',
        'from-shadow',
      ),
    ).toBe('from-shadow')
  })
})
