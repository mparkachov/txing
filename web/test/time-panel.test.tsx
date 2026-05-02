import { describe, expect, test } from 'bun:test'
import { renderToStaticMarkup } from 'react-dom/server'
import TimePanel from '../../devices/time/web/TimePanel'
import { formatEpochMs, formatTimeValue } from '../../devices/time/web/time-model'

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

    expect(markup).toContain(formatTimeValue('2026-05-01T10:11:12.000Z'))
    expect(markup).toContain('Rendezvous')
    expect(markup).toContain('Browser time')
    expect(markup).toContain('sleep')
    expect(markup).not.toContain('Live time')
    expect(markup).not.toContain('unavailable')
    expect(markup).not.toContain('2026-05-01T10:11:12.000Z')
  })

  test('formats time values in browser timezone without milliseconds', () => {
    const formattedIso = formatTimeValue('2026-05-01T10:11:12.374Z')
    const formattedEpoch = formatEpochMs(1777630272374)

    expect(formattedIso).not.toContain('.374')
    expect(formattedIso).not.toContain('T10:11:12.374Z')
    expect(formattedEpoch).not.toContain('.374')
    expect(formattedEpoch).not.toContain('T10:11:12.374Z')
    expect(formattedIso).toMatch(/\d{2}/)
  })
})
