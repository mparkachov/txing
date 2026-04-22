import { describe, expect, test } from 'bun:test'
import { renderToStaticMarkup } from 'react-dom/server'
import NotificationLogPanel from '../src/NotificationLogPanel'

describe('notification log panel', () => {
  test('renders current-session log entries with tone styling', () => {
    const markup = renderToStaticMarkup(
      <NotificationLogPanel
        notificationLog={[
          {
            id: 'runtime-log-1',
            tone: 'neutral',
            message: 'Sparkplug DCMD.redcon -> 3',
            dedupeKey: 'sparkplug-redcon:3',
            createdAtMs: new Date(2026, 3, 13, 14, 49, 36).getTime(),
          },
          {
            id: 'runtime-log-2',
            tone: 'error',
            message: 'Board video signaling closed',
            dedupeKey: 'board-video-viewer:Board video signaling closed',
            createdAtMs: new Date(2026, 3, 13, 14, 49, 40).getTime(),
          },
        ]}
      />,
    )

    expect(markup).toContain('Session Log')
    expect(markup).toContain('notification-log-entry notification-log-entry-neutral')
    expect(markup).toContain('notification-log-entry notification-log-entry-error')
    expect(markup).toContain('2026-04-13 14:49:36')
    expect(markup).toContain('Sparkplug DCMD.redcon -&gt; 3')
    expect(markup).toContain('Board video signaling closed')
  })
})
