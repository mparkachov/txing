import { describe, expect, test } from 'bun:test'
import { renderToStaticMarkup } from 'react-dom/server'
import virtualQuadAdapter from '../../devices/virtual-quad/web/virtual-quad-adapter'
import { readAgentStatus } from '../src/agent-shadow-status'
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
    control: { state: 'observing' },
  },
}
const read = (patch: Partial<typeof reported> = {}, sessionId: string | null = 'quad-1') =>
  readAgentStatus({ state: { reported: { ...reported, ...patch } } }, now, sessionId).label

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

  test('fences catalog readiness and observer status against the same session as the live view', () => {
    const target = { kind: 'device', groupId: 'town-test', edgeNodeId: 'cloud-test', deviceId: 'virtual-quad-test' } as const
    const simulation = { state: { reported: {
      phase: 'operational', sessionId: 'quad-1', terminalRevision: 1,
      availabilityWatermarkMs: now - 1_000, availabilityExpiresAtMs: now + 5_000,
    } } }
    const sparkplug = (sessionId: string, redcon = 1, timestamp = now) => ({
      state: { reported: {
        topic: { ...target, messageType: 'DDATA' },
        payload: { timestamp, metrics: { redcon, virtualQuad: { sessionId }, capability: { mavlink: true, video: redcon === 1 } } },
      } },
    })
    const status = (projection: unknown, at = now) =>
      virtualQuadAdapter.readCatalogStatus(target, { simulation, sparkplug: projection, agent: { state: { reported } } }, at)

    expect(status(sparkplug('quad-1'))).toEqual({
      redcon: 1,
      agentStatus: { active: true, label: 'running', expiresAtMs: now + 15_000 },
      simulationExpiresAtMs: now + 5_000,
    })
    const degraded = status(sparkplug('quad-1', 2))
    expect(degraded.redcon).toBe(2)
    expect(degraded.agentStatus?.active).toBe(false)
    for (const stale of [
      status(sparkplug('previous-session')),
      status(sparkplug('quad-1', 1, now - 1_001)),
      status(sparkplug('quad-1'), now + 5_000),
    ]) {
      expect(stale.redcon).toBe(3)
      expect(stale.agentStatus?.active).toBe(false)
      expect(stale.simulationExpiresAtMs).toBeNull()
    }
  })

  test('uses the observer state for the agent dot while retaining other capability projections', () => {
    const markup = renderToStaticMarkup(<CapabilityStack
      thingName="quad-1"
      label="Virtual quad"
      capabilities={['agent', 'video']}
      sparkplugShadow={{ state: { reported: { payload: { metrics: { capability: { agent: true, video: true } } } } } }}
      sparkplugShadowStatus="ready"
      agentStatus={{ active: false, label: 'stopping' }}
    />)
    expect(markup).toContain('catalog-status-capability-inactive" title="agent: stopping"')
    expect(markup).toContain('catalog-status-capability-active" title="video: active"')
  })

  test('MAVLink availability follows Sparkplug even while the agent is connecting', () => {
    const markup = renderToStaticMarkup(<CapabilityStack
      thingName="quad-1"
      label="Virtual quad"
      capabilities={['mavlink', 'agent']}
      sparkplugShadow={{ state: { reported: { payload: { metrics: { capability: { mavlink: true } } } } } }}
      sparkplugShadowStatus="ready"
      agentStatus={{ active: false, label: 'connecting' }}
    />)
    expect(markup).toContain('catalog-status-capability-active" title="mavlink: active"')
  })
})

test('agent readiness requires two fresh connected streams on a device without a simulator session', () => {
  expect(readAgentStatus({ state: { reported } }, now).active).toBe(true)
  for (const runtime of [
    { ...reported.runtime, mavlink: { state: 'connecting' } },
    { ...reported.runtime, video: { state: 'error' } },
    { ...reported.runtime, sampledAt: now / 1000 - 75 },
    { ...reported.runtime, runId: 'previous-run' },
  ]) {
    expect(readAgentStatus({ state: { reported: { ...reported, runtime } } }, now).active).toBe(false)
  }
  expect(readAgentStatus(undefined, now).active).toBe(false)
})

test('TBot catalog and device badges require the runtime shadow in addition to launch eligibility', () => {
  const nowMs = Date.now()
  const sample = { ...reported,
    activation: { id: 'tbot-activation', deadline: Math.floor(nowMs / 1000) + 60 },
    runtime: { ...reported.runtime, sampledAt: Math.floor(nowMs / 1000) },
  }
  const ready = readAgentStatus({ state: { reported: sample } }, nowMs)
  const projection = (agent: boolean) => ({ state: { reported: { payload: { metrics: { capability: { agent } } } } } })
  const badge = (catalog: boolean, agentStatus?: typeof ready, eligible = true) => renderToStaticMarkup(
    <CapabilityStack thingName="tbot" label="TBot" capabilities={['sparkplug', 'agent']}
      sparkplugShadow={catalog ? projection(eligible) : { namedShadows: { sparkplug: projection(eligible) } }}
      sparkplugShadowStatus="ready" agentStatus={agentStatus} />,
  )
  for (const catalog of [true, false]) {
    expect(badge(catalog)).toContain('catalog-status-capability-inactive" title="agent: unavailable"')
    expect(badge(catalog, ready)).toContain('catalog-status-capability-active" title="agent: running"')
    expect(badge(catalog, { active: true, label: 'running', expiresAtMs: nowMs }))
      .toContain('catalog-status-capability-inactive" title="agent: unavailable"')
    expect(badge(catalog, ready, false)).toContain('catalog-status-capability-inactive" title="agent: unavailable"')
  }
})
