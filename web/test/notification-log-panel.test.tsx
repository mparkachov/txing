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
            tone: 'success',
            message: 'Sparkplug DCMD.redcon -> 3 at 14:49:36',
            dedupeKey: 'sparkplug-redcon:3',
            createdAtMs: new Date('2026-04-13T14:49:36Z').getTime(),
          },
          {
            id: 'runtime-log-2',
            tone: 'error',
            message: 'Board video signaling closed',
            dedupeKey: 'board-video-viewer:Board video signaling closed',
            createdAtMs: new Date('2026-04-13T14:49:40Z').getTime(),
          },
        ]}
      />,
    )

    expect(markup).toContain('Session Log')
    expect(markup).toContain('notification-log-entry notification-log-entry-success')
    expect(markup).toContain('notification-log-entry notification-log-entry-error')
    expect(markup).toContain('Sparkplug DCMD.redcon -&gt; 3 at 14:49:36')
    expect(markup).toContain('Board video signaling closed')
  })
})
