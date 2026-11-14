import { describe, expect, test } from 'bun:test'
import { renderToStaticMarkup } from 'react-dom/server'
import agentShadowExample from '../../devices/tbot/aws/fixtures/agent-shadow.json'
import DebugPanel from '../src/DebugPanel'

const common = {
  canLoadShadow: true,
  lastShadowUpdateLabel: '09:48:56',
  lastShadowUpdateTitle: 'Last shadow update 2026-04-23 09:48:56',
  onLoadShadow: () => {},
  shadowDocument: { namedShadows: { sparkplug: { state: { reported: {} } } } },
  shadowNames: ['sparkplug'],
}

describe('debug panel', () => {
  test('renders load shadow control before the last-shadow timestamp', () => {
    const markup = renderToStaticMarkup(<DebugPanel {...common} />)

    expect(markup).toContain('Load Shadow')
    expect(markup).toContain('status-last-shadow-update')
    expect(markup.indexOf('Load Shadow')).toBeLessThan(markup.indexOf('09:48:56'))
  })

  test('places device diagnostics before shadow metadata and omits hardware status tiles', () => {
    const markup = renderToStaticMarkup(
      <DebugPanel {...common} deviceDiagnostics={<section>ArduPilot / MAVLink</section>} />,
    )

    expect(markup).toContain('debug-panel-device-diagnostics')
    expect(markup).not.toContain('status-device')
    expect(markup).not.toContain('>MCU<')
    expect(markup).not.toContain('>Board<')
    expect(markup.indexOf('ArduPilot / MAVLink')).toBeLessThan(markup.indexOf('Last shadow update'))
  })

  test('renders each declared shadow with only its own document', () => {
    const markup = renderToStaticMarkup(
      <DebugPanel
        {...common}
        initialSparkplugShadow={{ version: 1 }}
        shadowNames={['sparkplug', 'board', 'video', 'mavlink']}
        shadowDocument={{
          state: { reported: 'combined-state' },
          namedShadows: {
            sparkplug: { version: 2 },
            board: { state: { reported: 'board-sample' } },
            mavlink: { state: { reported: 'mavlink-sample' } },
            simulation: { state: { reported: 'unlisted-sample' } },
          },
        }}
      />,
    )

    expect(markup).toContain('Sparkplug shadow JSON')
    expect(markup).toContain('&quot;version&quot;: 2')
    expect(markup).not.toContain('&quot;version&quot;: 1')
    const board = markup.match(/<textarea[^>]*aria-label="Board shadow JSON"[^>]*>([\s\S]*?)<\/textarea>/)?.[1]
    expect(board).toContain('board-sample')
    expect(board).not.toContain('mavlink-sample')
    expect(markup).toContain('MAVLink shadow JSON')
    expect(markup).toContain('<h2>Video shadow</h2><p>No shadow data received.</p>')
    expect(markup).not.toContain('combined-state')
    expect(markup).not.toContain('unlisted-sample')
    expect(markup.match(/<textarea[^>]*\bread[oO]nly=""/g)).toHaveLength(3)
  })

  test('shows the initial Sparkplug read while waiting for MQTT snapshots', () => {
    const markup = renderToStaticMarkup(
      <DebugPanel {...common} shadowDocument={undefined} initialSparkplugShadow={{ version: 1 }} />,
    )
    expect(markup).toContain('Sparkplug shadow JSON')
    expect(markup).toContain('&quot;version&quot;: 1')
  })

  test('shows Agent in its own panel with isolated unavailable states', () => {
    const otherDevice = renderToStaticMarkup(<DebugPanel {...common} />)
    const agentDevice = { ...common, shadowNames: ['sparkplug', 'agent'] }
    const ready = renderToStaticMarkup(
      <DebugPanel {...agentDevice} agentShadow={{ status: 'ready', json: JSON.stringify(agentShadowExample), error: '' }} />,
    )
    const missing = renderToStaticMarkup(
      <DebugPanel {...agentDevice} agentShadow={{ status: 'missing', json: '', error: '' }} />,
    )
    const unavailable = renderToStaticMarkup(
      <DebugPanel {...agentDevice} agentShadow={{ status: 'error', json: '', error: 'Read failed' }} />,
    )

    expect(otherDevice).not.toContain('Agent shadow')
    expect(ready).toContain('Agent shadow JSON')
    expect(ready).toContain('run-example')
    expect(ready).toContain('https://example.invalid/agent')
    expect(ready).toContain('video receive: peer connection timed out')
    expect(ready).not.toContain('udpPort')
    expect(missing).toContain('Agent status has not been initialized.')
    expect(unavailable).toContain('Agent status unavailable: Read failed')
    expect(unavailable).toContain('Sparkplug shadow JSON')
  })
})
