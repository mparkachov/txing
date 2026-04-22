import { describe, expect, test } from 'bun:test'
import { renderToStaticMarkup } from 'react-dom/server'
import SparkplugPanel from '../src/SparkplugPanel'

describe('sparkplug panel', () => {
  test('renders a single read-only town strip without labels around redcon', () => {
    const markup = renderToStaticMarkup(
      <SparkplugPanel
        routeKind="town"
        botRedcon={null}
        desiredRedcon={null}
        isBotPanelOpen={false}
        isRedconCommandDisabled={false}
        isRedconSleepCommandDisabled={false}
        onRedconSelect={() => {}}
        onToggleBotPanel={() => {}}
      />,
    )

    expect(markup).toContain('class="sparkplug-strip"')
    expect(markup).toContain('data-sparkplug-row="town"')
    expect(markup).not.toContain('>BOT<')
    expect(markup).not.toContain('>REDCON<')
    expect(markup).toContain('sparkplug-redcon-button')
    expect(markup).not.toContain('status-battery-shell')
    expect(markup).not.toContain('status-switch-track')
  })

  test('renders a direct bot redcon control with an always-visible disabled details button outside redcon 1', () => {
    const markup = renderToStaticMarkup(
      <SparkplugPanel
        routeKind="device"
        botRedcon={4}
        desiredRedcon={null}
        isBotPanelOpen={false}
        isRedconCommandDisabled={false}
        isRedconSleepCommandDisabled={false}
        onRedconSelect={() => {}}
        onToggleBotPanel={() => {}}
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
    expect(markup).toContain('aria-label="Show bot device details"')
    expect(markup).toContain('disabled=""')
    expect(markup).toContain('sparkplug-device-glyph-details')
  })

  test('shows pending target styling and device toggle when bot is at redcon 1', () => {
    const markup = renderToStaticMarkup(
      <SparkplugPanel
        routeKind="device"
        botRedcon={1}
        desiredRedcon={2}
        isBotPanelOpen={true}
        isRedconCommandDisabled={false}
        isRedconSleepCommandDisabled={false}
        onRedconSelect={() => {}}
        onToggleBotPanel={() => {}}
      />,
    )

    expect(markup).toContain('sparkplug-redcon-button-pending')
    expect(markup).toContain('sparkplug-redcon-target-arrow')
    expect(markup).toContain('sparkplug-device-button sparkplug-device-button-open')
    expect(markup).toContain('aria-label="Hide bot device details"')
  })
})
