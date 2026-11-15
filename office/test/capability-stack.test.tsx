import { describe, expect, test } from 'bun:test'
import { renderToStaticMarkup } from 'react-dom/server'
import { readFileSync } from 'node:fs'
import CapabilityStack from '../src/CapabilityStack'
import { parseCapabilitiesSet } from '../src/catalog-api'
import { listDeviceWebAdapters } from '../src/device-registry'

describe('capability stack', () => {
  test('renders visible active and inactive capability status chips', () => {
    const markup = renderToStaticMarkup(
      <CapabilityStack
        thingName="bot"
        label="bot"
        capabilities={['sparkplug', 'ble', 'power', 'board', 'mcp', 'video']}
        sparkplugShadow={{
          state: {
            reported: {
              payload: {
                metrics: {
                  capability: {
                    sparkplug: true,
                    ble: true,
                    power: false,
                  },
                },
              },
            },
          },
        }}
        sparkplugShadowStatus="ready"
      />,
    )

    expect(markup).toContain('aria-label="Capability status for bot"')
    expect(markup).toMatch(
      /title="video: inactive"[\s\S]*title="mcp: inactive"[\s\S]*title="board: inactive"[\s\S]*title="power: inactive"[\s\S]*title="ble: active"/,
    )
    expect(markup).not.toContain('title="sparkplug: active"')
    expect(markup).toContain('catalog-status-capability-active')
    expect(markup).toContain('catalog-status-capability-inactive')
  })

  test('supports navigation-specific layout class without changing status rules', () => {
    const markup = renderToStaticMarkup(
      <CapabilityStack
        thingName="raspi"
        label="raspi"
        capabilities={['sparkplug', 'ble']}
        sparkplugShadow={null}
        sparkplugShadowStatus="loading"
        className="navigation-capabilities"
      />,
    )

    expect(markup).toContain('catalog-status-capabilities navigation-capabilities')
    expect(markup).not.toContain('title="sparkplug: inactive"')
    expect(markup).toContain('title="ble: inactive"')
  })

  test('renders Thread as active from the Sparkplug projection for power-si', () => {
    const markup = renderToStaticMarkup(
      <CapabilityStack
        thingName="power-si-001"
        label="Power SI"
        capabilities={['sparkplug', 'thread', 'power']}
        sparkplugShadow={{
          state: {
            reported: {
              payload: {
                metrics: {
                  capability: {
                    sparkplug: true,
                    thread: true,
                    power: false,
                  },
                },
              },
            },
          },
        }}
        sparkplugShadowStatus="ready"
      />,
    )

    expect(markup).toContain('title="thread: active"')
    expect(markup).toContain('title="power: inactive"')
    expect(markup).not.toContain('title="sparkplug: active"')
  })

  test('omits the capability row for a thing that only declares Sparkplug', () => {
    const markup = renderToStaticMarkup(
      <CapabilityStack
        thingName="raspi"
        label="raspi"
        capabilities={['sparkplug']}
        sparkplugShadow={null}
        sparkplugShadowStatus="loading"
      />,
    )

    expect(markup).toBe('')
  })

  test('requires both the reported simulation bit and matching unexpired health', () => {
    const now = Date.now()
    const renderBadge = (simulation: boolean, simulationExpiresAtMs: number | null) => renderToStaticMarkup(
      <CapabilityStack thingName="virtual-quad" label="Virtual quad" capabilities={['simulation']}
        sparkplugShadow={{ state: { reported: { payload: { metrics: { capability: { simulation } } } } } }}
        sparkplugShadowStatus="ready" simulationExpiresAtMs={simulationExpiresAtMs} />,
    )
    expect(renderBadge(true, now + 60_000)).toContain('title="simulation: active"')
    expect(renderBadge(false, now + 60_000)).toContain('title="simulation: inactive"')
    expect(renderBadge(true, now)).toContain('title="simulation: inactive"')
    expect(renderBadge(true, null)).toContain('title="simulation: inactive"')
  })

  for (const { type } of listDeviceWebAdapters()) {
    test(`${type} omits only Sparkplug in the catalog and device header`, () => {
      const manifest = Bun.TOML.parse(readFileSync(
        new URL(`../../devices/${type}/manifest.toml`, import.meta.url), 'utf8',
      )) as { capabilities: string[] }
      const capabilities = parseCapabilitiesSet(manifest.capabilities.join(','))
      const availability = capabilities.map((name, index) => [name, index % 2 === 0] as const)
      const sparkplug = { state: { reported: { payload: { metrics: {
        redcon: 2, capability: Object.fromEntries(availability),
      } } } } }
      const common = { thingName: type, label: type, capabilities, sparkplugShadowStatus: 'ready',
        simulationExpiresAtMs: Date.now() + 60_000 } as const
      const catalog = renderToStaticMarkup(<CapabilityStack {...common} sparkplugShadow={sparkplug} />)
      const device = renderToStaticMarkup(<CapabilityStack {...common}
        sparkplugShadow={{ namedShadows: { sparkplug } }} className="navigation-capabilities" />)
      const titles = (markup: string) => Array.from(markup.matchAll(/title="([^"]+)"/g), ([, title]) => title)
      const expected = availability.filter(([name]) => name !== 'sparkplug').reverse()
        .map(([name, active]) => `${name}: ${name === 'agent' ? 'unavailable' : active ? 'active' : 'inactive'}`)
      expect(titles(catalog)).toEqual(expected)
      expect(titles(device)).toEqual(expected)
    })
  }
})
