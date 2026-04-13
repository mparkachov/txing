import { describe, expect, test } from 'bun:test'
import { renderToStaticMarkup } from 'react-dom/server'
import NotificationTray from '../src/NotificationTray'

describe('notification tray', () => {
  test('renders tone classes and dismiss controls for runtime notifications', () => {
    const markup = renderToStaticMarkup(
      <NotificationTray
        notifications={[
          {
            id: 'notification-1',
            tone: 'success',
            message: 'Sparkplug DCMD.redcon -> 3',
            dedupeKey: 'sparkplug-redcon:3',
            createdAtMs: new Date(2026, 3, 13, 14, 49, 36).getTime(),
            expiresAtMs: 5_000,
          },
          {
            id: 'notification-2',
            tone: 'error',
            message: 'Board video signaling closed',
            dedupeKey: 'board-video-viewer:Board video signaling closed',
            createdAtMs: new Date(2026, 3, 13, 14, 49, 40).getTime(),
            expiresAtMs: 5_000,
          },
        ]}
        onDismiss={() => {}}
      />,
    )

    expect(markup).toContain('class="notification-tray"')
    expect(markup).toContain('notification-card notification-card-success')
    expect(markup).toContain('notification-card notification-card-error')
    expect(markup).toContain('2026-04-13 14:49:36')
    expect(markup).toContain('Sparkplug DCMD.redcon -&gt; 3')
    expect(markup).toContain(
      'aria-label="Dismiss notification: 2026-04-13 14:49:36: Sparkplug DCMD.redcon -&gt; 3"',
    )
    expect(markup).toContain(
      'aria-label="Dismiss notification: 2026-04-13 14:49:40: Board video signaling closed"',
    )
  })
})
