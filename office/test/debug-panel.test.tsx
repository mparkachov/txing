import { describe, expect, test } from 'bun:test'
import { renderToStaticMarkup } from 'react-dom/server'
import DebugPanel from '../src/DebugPanel'

describe('debug panel', () => {
  test('renders load shadow control before the last-shadow timestamp', () => {
    const markup = renderToStaticMarkup(
      <DebugPanel
        canLoadShadow={true}
        lastShadowUpdateLabel="09:48:56"
        lastShadowUpdateTitle="Last shadow update 2026-04-23 09:48:56"
        onLoadShadow={() => {}}
        reportedBoardPower={true}
        reportedMcuPower={true}
        shadowJson='{"state":{"reported":{}}}'
      />,
    )

    expect(markup).toContain('Load Shadow')
    expect(markup).toContain('status-last-shadow-update')
    expect(markup.indexOf('Load Shadow')).toBeLessThan(markup.indexOf('09:48:56'))
  })

  test('places device diagnostics with MCU and Board before shadow metadata', () => {
    const markup = renderToStaticMarkup(
      <DebugPanel
        canLoadShadow={true}
        deviceDiagnostics={<section>ArduPilot / MAVLink</section>}
        lastShadowUpdateLabel="09:48:56"
        lastShadowUpdateTitle="Last shadow update 2026-04-23 09:48:56"
        onLoadShadow={() => {}}
        reportedBoardPower={true}
        reportedMcuPower={true}
        shadowJson='{"state":{"reported":{}}}'
      />,
    )

    expect(markup).toContain('debug-panel-device-diagnostics')
    expect(markup.indexOf('Board')).toBeLessThan(markup.indexOf('ArduPilot / MAVLink'))
    expect(markup.indexOf('ArduPilot / MAVLink')).toBeLessThan(markup.indexOf('Last shadow update'))
  })
})
