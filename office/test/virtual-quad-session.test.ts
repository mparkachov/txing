import { expect, test } from 'bun:test'
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
