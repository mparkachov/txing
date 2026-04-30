import { describe, expect, test } from 'bun:test'
import { renderToStaticMarkup } from 'react-dom/server'
import SparkplugPanel from '../src/SparkplugPanel'

describe('sparkplug panel', () => {
  test('renders a read-only strip without route-specific labels', () => {
    const markup = renderToStaticMarkup(
      <SparkplugPanel
        sparkplugRedcon={1}
        targetRedcon={null}
        isInteractive={false}
        isRedconCommandDisabled={false}
        isRedconSleepCommandDisabled={false}
        onRedconSelect={() => {}}
      />,
    )

    expect(markup).toContain('class="sparkplug-strip"')
    expect(markup).toContain('data-sparkplug-mode="readonly"')
    expect(markup).not.toContain('>BOT<')
    expect(markup).not.toContain('>REDCON<')
    expect(markup).toContain('sparkplug-redcon-button')
    expect(markup).not.toContain('sparkplug-device-button')
    expect(markup).not.toContain('status-battery-shell')
    expect(markup).not.toContain('status-switch-track')
  })

  test('renders a read-only strip without manual detail affordances', () => {
    const markup = renderToStaticMarkup(
      <SparkplugPanel
        sparkplugRedcon={2}
        targetRedcon={null}
        isInteractive={false}
        isRedconCommandDisabled={false}
        isRedconSleepCommandDisabled={false}
        onRedconSelect={() => {}}
      />,
    )

    expect(markup).toContain('data-sparkplug-mode="readonly"')
    expect(markup).not.toContain('sparkplug-device-button')
    expect(markup).not.toContain('Show device details')
  })

  test('renders an interactive redcon control without route-specific affordances', () => {
    const markup = renderToStaticMarkup(
      <SparkplugPanel
        sparkplugRedcon={4}
        targetRedcon={null}
        isInteractive={true}
        isRedconCommandDisabled={false}
        isRedconSleepCommandDisabled={false}
        onRedconSelect={() => {}}
      />,
    )

    expect(markup).toContain('data-sparkplug-mode="interactive"')
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

  test('shows pending target styling for the generic current-thing panel', () => {
    const markup = renderToStaticMarkup(
      <SparkplugPanel
        sparkplugRedcon={1}
        targetRedcon={2}
        isInteractive={true}
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
