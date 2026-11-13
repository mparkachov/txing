import { describe, expect, test } from 'bun:test'
import { renderToStaticMarkup } from 'react-dom/server'
import { readVirtualQuadAgentStatus } from '../src/agent-shadow-status'
import CapabilityStack from '../src/CapabilityStack'

const now = 1_700_000_000_000
const reported = {
  lifecycle: { state: 'running' },
  activation: { id: 'quad-1', deadline: now / 1000 + 120 },
  run: { id: 'run-1' },
  runtime: {
    runId: 'run-1',
    sampledAt: now / 1000 - 60,
    mavlink: { state: 'connected' },
    video: { state: 'connected' },
  },
}
const read = (patch: Partial<typeof reported> = {}, sessionId: string | null = 'quad-1') =>
  readVirtualQuadAgentStatus({ state: { reported: { ...reported, ...patch } } }, sessionId, now)

describe('virtual quad agent shadow status', () => {
  test('reports a fresh observer for the current simulator session and run', () => {
    expect(read()).toBe('running')
    expect(read({}, 'quad-2')).toBe('unavailable')
    expect(read({}, null)).toBe('unavailable')
    expect(read({ run: { id: 'run-2' } })).toBe('unavailable')
    expect(read({ runtime: { ...reported.runtime, sampledAt: now / 1000 - 75 } })).toBe('unavailable')
    expect(read({ activation: { ...reported.activation, deadline: now / 1000 } })).toBe('expired')
  })

  test('distinguishes stopping, replacement startup and connection recovery', () => {
    expect(read({ lifecycle: { state: 'stopped' } })).toBe('stopped')
    expect(read({ lifecycle: { state: 'stopping' } })).toBe('stopping')
    expect(read({ lifecycle: { state: 'starting' } })).toBe('starting')
    expect(read({ runtime: { ...reported.runtime, video: { state: 'connecting' } } })).toBe('connecting')
  })

  test('uses the observer state for the agent dot while retaining other capability projections', () => {
    const markup = renderToStaticMarkup(<CapabilityStack
      thingName="quad-1"
      label="Virtual quad"
      capabilities={['agent', 'video']}
      sparkplugShadow={{ state: { reported: { payload: { metrics: { capability: { agent: true, video: true } } } } } }}
      sparkplugShadowStatus="ready"
      agentStatus="stopping"
    />)
    expect(markup).toContain('catalog-status-capability-inactive" title="agent: stopping"')
    expect(markup).toContain('catalog-status-capability-active" title="video: active"')
  })

  test('a ready MAVLink service remains gray while the browser connects', () => {
    const markup = renderToStaticMarkup(<CapabilityStack
      thingName="quad-1"
      label="Virtual quad"
      capabilities={['mavlink']}
      sparkplugShadow={{ state: { reported: { payload: { metrics: { capability: { mavlink: true } } } } } }}
      sparkplugShadowStatus="ready"
      mavlinkStatus="connecting"
    />)
    expect(markup).toContain('catalog-status-capability-inactive" title="mavlink: connecting"')
  })
})
