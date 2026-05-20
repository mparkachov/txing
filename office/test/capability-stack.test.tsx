import { describe, expect, test } from 'bun:test'
import { renderToStaticMarkup } from 'react-dom/server'
import CapabilityStack from '../src/CapabilityStack'

describe('capability stack', () => {
  test('renders active and inactive capability status chips', () => {
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
      /title="video: inactive"[\s\S]*title="mcp: inactive"[\s\S]*title="board: inactive"[\s\S]*title="power: inactive"[\s\S]*title="ble: active"[\s\S]*title="sparkplug: active"/,
    )
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
    expect(markup).toContain('title="sparkplug: inactive"')
    expect(markup).toContain('title="ble: inactive"')
  })
})
