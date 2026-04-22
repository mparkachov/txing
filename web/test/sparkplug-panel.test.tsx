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
        detailsToggleAriaLabel="Show rig details"
        detailsToggleTitle="Show rig details"
        isDetailsPanelOpen={false}
        isDetailsPanelToggleEnabled={true}
        isRedconCommandDisabled={false}
        isRedconSleepCommandDisabled={false}
        onRedconSelect={() => {}}
        onToggleDetailsPanel={() => {}}
      />,
    )

    expect(markup).toContain('class="sparkplug-strip"')
    expect(markup).toContain('data-sparkplug-row="town"')
    expect(markup).not.toContain('>BOT<')
    expect(markup).not.toContain('>REDCON<')
    expect(markup).toContain('sparkplug-redcon-button')
    expect(markup).toContain('aria-label="Show rig details"')
    expect(markup).not.toContain('status-battery-shell')
    expect(markup).not.toContain('status-switch-track')
  })

  test('renders a rig strip with an enabled device-list details button', () => {
    const markup = renderToStaticMarkup(
      <SparkplugPanel
        routeKind="rig"
        botRedcon={null}
        targetRedcon={null}
        detailsToggleAriaLabel="Show device details"
        detailsToggleTitle="Show device details"
        isDetailsPanelOpen={false}
        isDetailsPanelToggleEnabled={true}
        isRedconCommandDisabled={false}
        isRedconSleepCommandDisabled={false}
        onRedconSelect={() => {}}
        onToggleDetailsPanel={() => {}}
      />,
    )

    expect(markup).toContain('data-sparkplug-row="rig"')
    expect(markup).toMatch(
      /aria-label="Show device details" title="Show device details"(?![^>]*disabled)/,
    )
  })

  test('renders a direct bot redcon control with an always-visible disabled details button outside redcon 1', () => {
    const markup = renderToStaticMarkup(
      <SparkplugPanel
        routeKind="device"
        botRedcon={4}
        targetRedcon={null}
        detailsToggleAriaLabel="Show bot device details"
        detailsToggleTitle="Device details become available at REDCON 1"
        isDetailsPanelOpen={false}
        isDetailsPanelToggleEnabled={false}
        isRedconCommandDisabled={false}
        isRedconSleepCommandDisabled={false}
        onRedconSelect={() => {}}
        onToggleDetailsPanel={() => {}}
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
        targetRedcon={2}
        detailsToggleAriaLabel="Hide bot device details"
        detailsToggleTitle="Hide bot device details"
        isDetailsPanelOpen={true}
        isDetailsPanelToggleEnabled={true}
        isRedconCommandDisabled={false}
        isRedconSleepCommandDisabled={false}
        onRedconSelect={() => {}}
        onToggleDetailsPanel={() => {}}
      />,
    )

    expect(markup).toContain('sparkplug-redcon-button-pending')
    expect(markup).toContain('sparkplug-redcon-target-arrow')
    expect(markup).toContain('sparkplug-device-button sparkplug-device-button-open')
    expect(markup).toContain('aria-label="Hide bot device details"')
  })
})
