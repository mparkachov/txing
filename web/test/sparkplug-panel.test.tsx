import { describe, expect, test } from 'bun:test'
import { renderToStaticMarkup } from 'react-dom/server'
import SparkplugPanel from '../src/SparkplugPanel'

describe('sparkplug panel', () => {
  test('renders a single read-only town strip without labels around redcon', () => {
    const markup = renderToStaticMarkup(
      <SparkplugPanel
        routeKind="town"
        botRedcon={null}
        targetRedcon={null}
        isRedconCommandDisabled={false}
        isRedconSleepCommandDisabled={false}
        onRedconSelect={() => {}}
      />,
    )

    expect(markup).toContain('class="sparkplug-strip"')
    expect(markup).toContain('data-sparkplug-row="town"')
    expect(markup).not.toContain('>BOT<')
    expect(markup).not.toContain('>REDCON<')
    expect(markup).toContain('sparkplug-redcon-button')
    expect(markup).not.toContain('sparkplug-device-button')
    expect(markup).not.toContain('status-battery-shell')
    expect(markup).not.toContain('status-switch-track')
  })

  test('renders a rig strip without a manual details button', () => {
    const markup = renderToStaticMarkup(
      <SparkplugPanel
        routeKind="rig"
        botRedcon={null}
        targetRedcon={null}
        isRedconCommandDisabled={false}
        isRedconSleepCommandDisabled={false}
        onRedconSelect={() => {}}
      />,
    )

    expect(markup).toContain('data-sparkplug-row="rig"')
    expect(markup).not.toContain('sparkplug-device-button')
    expect(markup).not.toContain('Show device details')
  })

  test('renders a direct bot redcon control without a manual details button outside redcon 1', () => {
    const markup = renderToStaticMarkup(
      <SparkplugPanel
        routeKind="device"
        botRedcon={4}
        targetRedcon={null}
        isRedconCommandDisabled={false}
        isRedconSleepCommandDisabled={false}
        onRedconSelect={() => {}}
      />,
    )

    expect(markup).toContain('data-sparkplug-row="bot"')
    expect(markup).toContain('aria-label="Set REDCON 1 · Hot Rig · Red"')
    expect(markup).toContain('aria-label="Set REDCON 4 · Cold Camp · Green"')
    expect(markup).toContain('sparkplug-redcon-line')
    expect(markup).not.toContain('status-switch-track')
    expect(markup).not.toContain('status-battery-shell')
    expect(markup).not.toContain('>BOT<')
    expect(markup).not.toContain('>REDCON<')
    expect(markup).toMatch(
      /aria-label="Set REDCON 4 · Cold Camp · Green"[^>]*aria-pressed="true"(?![^>]*disabled)/,
    )
    expect(markup).not.toContain('Show bot device details')
    expect(markup).not.toContain('sparkplug-device-glyph-details')
  })

  test('shows pending target styling without a manual device toggle when bot is at redcon 1', () => {
    const markup = renderToStaticMarkup(
      <SparkplugPanel
        routeKind="device"
        botRedcon={1}
        targetRedcon={2}
        isRedconCommandDisabled={false}
        isRedconSleepCommandDisabled={false}
        onRedconSelect={() => {}}
      />,
    )

    expect(markup).toContain('sparkplug-redcon-button-pending')
    expect(markup).toContain('sparkplug-redcon-target-arrow')
    expect(markup).not.toContain('sparkplug-device-button')
    expect(markup).not.toContain('Hide bot device details')
  })
})
