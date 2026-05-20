import { describe, expect, test } from 'bun:test'
import { parseRobotState } from '../src/shadow-api-runtime'

describe('shadow api runtime helpers', () => {
  test('parses full active-control owner metadata from robot state', () => {
    const robotState = parseRobotState({
      control: {
        activeRequired: true,
        activeTtlMs: 5000,
        activeHeldByCaller: false,
        activeOwnerSessionId: 'session-a',
        activeExpiresAtMs: 20000,
        activeEpoch: 9,
        activeControl: {
          sessionId: 'session-a',
          actor: 'operator-a',
          transport: 'webrtc-datachannel',
          sinceMs: 10000,
          expiresAtMs: 20000,
          epoch: 9,
        },
      },
      motion: {
        leftSpeed: 0,
        rightSpeed: 0,
        sequence: 2,
      },
      video: {
        available: true,
        ready: true,
        status: 'ready',
        viewerConnected: true,
        lastError: null,
      },
    })

    expect(robotState?.control.activeControl).toEqual({
      sessionId: 'session-a',
      actor: 'operator-a',
      transport: 'webrtc-datachannel',
      sinceMs: 10000,
      expiresAtMs: 20000,
      epoch: 9,
    })
    expect(robotState?.control.activeOwnerSessionId).toBe('session-a')
    expect(robotState?.control.activeEpoch).toBe(9)
  })
})
