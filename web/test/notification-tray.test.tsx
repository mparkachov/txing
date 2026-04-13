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
            message: 'Sparkplug DCMD.redcon -> 3 at 14:49:36',
            dedupeKey: 'sparkplug-redcon:3',
            expiresAtMs: 10_000,
          },
          {
            id: 'notification-2',
            tone: 'error',
            message: 'Board video signaling closed',
            dedupeKey: 'board-video-viewer:Board video signaling closed',
            expiresAtMs: 10_000,
          },
        ]}
        onDismiss={() => {}}
      />,
    )

    expect(markup).toContain('class="notification-tray"')
    expect(markup).toContain('notification-card notification-card-success')
    expect(markup).toContain('notification-card notification-card-error')
    expect(markup).toContain('aria-label="Dismiss notification: Sparkplug DCMD.redcon -&gt; 3 at 14:49:36"')
    expect(markup).toContain('aria-label="Dismiss notification: Board video signaling closed"')
  })
})
