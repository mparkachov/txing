import { expect, test } from 'bun:test'
import { readQuadMavlinkStatus, readQuadMediaAvailability } from '../../devices/virtual-quad/web/virtual-quad-media-status'
import { canStartVirtualQuad, readVirtualQuadCommandResult, readVirtualQuadLifecycleMessage } from '../../devices/virtual-quad/web/virtual-quad-redcon'
import {
  isVirtualQuadProjectionFresh,
  readVirtualQuadSession,
  type QuadTarget,
} from '../../devices/virtual-quad/web/virtual-quad-session'

const target: QuadTarget = {
  kind: 'device', groupId: 'town-test', edgeNodeId: 'cloud-test', deviceId: 'virtual-quad-test',
}

const sparkplug = (timestamp: number, sessionId: string, messageType = 'DDATA') => ({
  state: { reported: {
    topic: { groupId: target.groupId, edgeNodeId: target.edgeNodeId, deviceId: target.deviceId, messageType },
    payload: { timestamp, metrics: { virtualQuad: { sessionId } } },
  } },
})

const simulation = (phase: string, sessionId: string | null) => ({
  state: { reported: {
    phase, sessionId, terminalRevision: 8, availabilityWatermarkMs: 1_000, availabilityExpiresAtMs: 16_000,
  } },
})

test('virtual quad readiness expires and fences older Sparkplug reports and sessions', () => {
  const current = readVirtualQuadSession(simulation('operational', 'new-session'))
  expect(isVirtualQuadProjectionFresh(target, current, sparkplug(1_000, 'new-session'), 15_999)).toBe(true)
  expect(isVirtualQuadProjectionFresh(target, current, sparkplug(1_000, 'new-session'), 16_000)).toBe(false)
  expect(isVirtualQuadProjectionFresh(target, current, sparkplug(999, 'new-session'), 15_999)).toBe(false)
  expect(isVirtualQuadProjectionFresh(target, current, sparkplug(1_001, 'old-session'), 15_999)).toBe(false)
  expect(isVirtualQuadProjectionFresh(target, current, sparkplug(1_001, 'new-session', 'DDEATH'), 15_999)).toBe(false)
  const stopping = readVirtualQuadSession(simulation('stopping', 'new-session'))
  expect(isVirtualQuadProjectionFresh(target, stopping, sparkplug(1_001, 'new-session'), 15_999)).toBe(false)
})

test('virtual quad session phase requires a matching reservation shape', () => {
  expect(readVirtualQuadSession(simulation('stopped', null))?.terminalRevision).toBe(8)
  expect(readVirtualQuadSession(simulation('stopped', 'new-session'))).toBeNull()
  expect(readVirtualQuadSession(simulation('starting', null))).toBeNull()
})

test('virtual quad can start through Sparkplug while the simulator is inactive', () => {
  const projection = sparkplug(1_000, 'old-session')
  const report = projection.state.reported
  const stopped = {
    session: readVirtualQuadSession(simulation('stopped', null)),
    sparkplug: { state: { reported: {
      ...report,
      payload: { ...report.payload, metrics: { redcon: 4, capability: { sparkplug: true, simulation: false } } },
    } } },
  }
  expect(canStartVirtualQuad(target, stopped)).toBe(true)
  expect(canStartVirtualQuad(target, { ...stopped, session: readVirtualQuadSession(simulation('failed', null)) })).toBe(true)
  expect(canStartVirtualQuad(target, { ...stopped, session: readVirtualQuadSession(simulation('stopping', 'old-session')) })).toBe(false)
  expect(canStartVirtualQuad(target, { ...stopped, sparkplug: null })).toBe(false)
  expect(canStartVirtualQuad({ ...target, edgeNodeId: 'other-rig' }, stopped)).toBe(false)

  stopped.sparkplug.state.reported.payload.metrics.capability.sparkplug = false
  expect(canStartVirtualQuad(target, stopped)).toBe(false)
})

test('an invocation with a lost terminal event can be restarted only after its hard deadline', () => {
  const active = readVirtualQuadSession({ state: { reported: {
    phase: 'operational', sessionId: 'old-session', terminalRevision: 8,
    run: { hardDeadlineMs: 20_000 },
  } } })
  const view = { session: active, sparkplug: { state: { reported: {
    topic: { groupId: target.groupId, edgeNodeId: target.edgeNodeId, deviceId: target.deviceId, messageType: 'DDATA' },
    payload: { timestamp: 1_000, metrics: { redcon: 1, capability: { sparkplug: true } } },
  } } } }
  expect(canStartVirtualQuad(target, view, 19_999)).toBe(false)
  expect(canStartVirtualQuad(target, view, 20_000)).toBe(true)
})

test('Office can observe MAVLink at REDCON 2 before opening flight and camera at REDCON 1', () => {
  const projection = {
    state: { reported: { payload: { metrics: { capability: { mavlink: true, video: true } } } } },
  }
  expect(readQuadMediaAvailability(true, 'starting', 2, projection)).toEqual({ mavlink: true, video: false })
  expect(readQuadMediaAvailability(true, 'operational', 2, projection)).toEqual({ mavlink: true, video: false })
  expect(readQuadMediaAvailability(true, 'operational', 1, projection)).toEqual({ mavlink: true, video: true })
  expect(readQuadMediaAvailability(true, 'stopping', 2, projection)).toEqual({ mavlink: false, video: false })
  expect(readQuadMediaAvailability(false, 'operational', 1, projection)).toEqual({ mavlink: false, video: false })
})

test('the browser MAVLink status requires a fresh heartbeat', () => {
  expect(readQuadMavlinkStatus(null, null)).toBe('connecting')
  expect(readQuadMavlinkStatus({ connected: true, heartbeat: false }, null)).toBe('waiting for heartbeat')
  expect(readQuadMavlinkStatus({ connected: true, heartbeat: true }, null)).toBe('live')
  expect(readQuadMavlinkStatus(null, 'peer failed')).toBe('reconnecting')
})

test('virtual quad REDCON transitions await the correlated session and reported posture', () => {
  const receipt = (redcon: number, requestId: string, status: string) => ({
    state: { reported: { payload: { metrics: {
      redcon, redconCommandId: requestId, redconCommandTarget: 1, redconCommandStatus: status,
    } } } },
  })
  const operational = readVirtualQuadSession(simulation('operational', 'new-session'))
  const start = { redcon: 1, requestId: 'start', terminalRevision: 8 } as const
  const ready = { session: operational, sparkplug: receipt(1, 'start', 'succeeded'), fresh: true, now: 1_000 }
  expect(readVirtualQuadCommandResult(start, ready)?.status).toBe('succeeded')
  expect(readVirtualQuadCommandResult(start, { ...ready, fresh: false })).toBeNull()
  expect(readVirtualQuadCommandResult(start, { ...ready, sparkplug: receipt(1, 'other', 'succeeded') })).toBeNull()
  expect(readVirtualQuadCommandResult(start, { ...ready, sparkplug: receipt(3, 'start', 'accepted') })).toBeNull()
  expect(readVirtualQuadCommandResult(start, { ...ready, sparkplug: receipt(4, 'start', 'failed') })?.status).toBe('failed')

  const stop = { redcon: 4, requestId: 'stop', sessionId: 'new-session' } as const
  const terminal = simulation('stopped', null)
  const stopped = readVirtualQuadSession({ state: { reported: {
    ...terminal.state.reported, lastSessionId: 'new-session',
  } } })
  expect(readVirtualQuadCommandResult(stop, { ...ready, session: stopped })).toBeNull()
  expect(readVirtualQuadCommandResult(stop, { ...ready, session: stopped, sparkplug: receipt(4, 'stop', 'succeeded') })?.status)
    .toBe('succeeded')
  expect(readVirtualQuadCommandResult({ ...stop, sessionId: 'old-session' }, {
    ...ready, session: stopped, sparkplug: receipt(4, 'stop', 'succeeded'),
  })).toBeNull()
})

test('virtual quad worker expiry becomes a standard error notification', () => {
  const terminal = simulation('failed', null)
  const failed = readVirtualQuadSession({ state: { reported: {
    ...terminal.state.reported, lastOutcome: 'failed', lastReason: 'worker health expired',
  } } })
  expect(readVirtualQuadLifecycleMessage(failed)).toEqual({
    tone: 'error', message: 'Session failed · worker health expired', dedupeKey: 'virtual-quad:8:failed',
  })
  expect(readVirtualQuadLifecycleMessage(readVirtualQuadSession(simulation('stopped', null)))).toBeNull()
  const ready = readVirtualQuadSession(simulation('operational', 'new-session'))
  expect(readVirtualQuadLifecycleMessage(ready, false)?.message).toBe('Simulator readiness unavailable')
  expect(readVirtualQuadLifecycleMessage(ready, true)?.message).toBe('Simulator running')
})

test('virtual quad only announces a stop for a session observed on the open page', () => {
  const terminal = simulation('stopped', null)
  const stopped = readVirtualQuadSession({ state: { reported: {
    ...terminal.state.reported, lastSessionId: 'finished-session', lastOutcome: 'stopped',
  } } })

  expect(readVirtualQuadLifecycleMessage(stopped)).toBeNull()
  expect(readVirtualQuadLifecycleMessage(stopped, true, 'other-session')).toBeNull()
  expect(readVirtualQuadLifecycleMessage(stopped, false, 'finished-session')?.message).toBe('Stopped')
})
