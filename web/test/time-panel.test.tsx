import { describe, expect, test } from 'bun:test'
import { renderToStaticMarkup } from 'react-dom/server'
import TimePanel from '../../devices/time/web/TimePanel'

const shadow = {
  namedShadows: {
    time: {
      state: {
        reported: {
          currentTimeIso: '2026-05-01T10:11:12.000Z',
          mode: 'sleep',
          activeUntilMs: null,
          lastCommandId: null,
          observedAtMs: 1777630272000,
        },
      },
    },
  },
}

describe('time panel', () => {
  test('renders last rendezvous time while sleeping', () => {
    const markup = renderToStaticMarkup(
      <TimePanel
        callMcpTool={async () => ({ currentTimeIso: 'ignored', epochMs: 0 })}
        isShadowConnected={true}
        reportedRedcon={4}
        shadow={shadow}
      />,
    )

    expect(markup).toContain('2026-05-01T10:11:12.000Z')
    expect(markup).toContain('Rendezvous')
    expect(markup).toContain('sleep')
    expect(markup).toContain('unavailable')
  })
})
