import { describe, expect, test } from 'bun:test'
import {
  appendNotificationLogEntry,
  deserializeNotificationLog,
  dismissAppNotification,
  enqueueAppNotification,
  expireAppNotifications,
  formatRuntimeNotificationLine,
  formatRuntimeTimestamp,
  getNextBoardVideoLastErrorNotification,
  serializeNotificationLog,
  runtimeNotificationLifetimeMs,
} from '../src/app-notifications'

describe('app notification helpers', () => {
  test('adds a new notification with a 10 second lifetime', () => {
    const notifications = enqueueAppNotification(
      [],
      {
        tone: 'success',
        message: 'Sparkplug DCMD.redcon -> 3',
        dedupeKey: 'sparkplug-redcon:3',
      },
      1_000,
      'notification-1',
    )

    expect(notifications).toEqual([
      {
        id: 'notification-1',
        tone: 'success',
        message: 'Sparkplug DCMD.redcon -> 3',
        dedupeKey: 'sparkplug-redcon:3',
        createdAtMs: 1_000,
        expiresAtMs: 1_000 + runtimeNotificationLifetimeMs,
      },
    ])
  })

  test('refreshes and reorders an active notification with the same dedupe key', () => {
    const notifications = enqueueAppNotification(
      [
        {
          id: 'older',
          tone: 'neutral',
          message: 'Older message',
          dedupeKey: 'older',
          createdAtMs: 4_000,
          expiresAtMs: 5_000,
        },
        {
          id: 'notification-1',
          tone: 'error',
          message: 'Original runtime error',
          dedupeKey: 'runtime-error',
          createdAtMs: 5_000,
          expiresAtMs: 8_000,
        },
      ],
      {
        tone: 'error',
        message: 'Updated runtime error',
        dedupeKey: 'runtime-error',
      },
      6_000,
      'notification-2',
    )

    expect(notifications).toEqual([
      {
        id: 'notification-1',
        tone: 'error',
        message: 'Updated runtime error',
        dedupeKey: 'runtime-error',
        createdAtMs: 6_000,
        expiresAtMs: 6_000 + runtimeNotificationLifetimeMs,
      },
      {
        id: 'older',
        tone: 'neutral',
        message: 'Older message',
        dedupeKey: 'older',
        createdAtMs: 4_000,
        expiresAtMs: 5_000,
      },
    ])
  })

  test('dismisses notifications by id and expires old entries', () => {
    const notifications = [
      {
        id: 'notification-1',
        tone: 'success' as const,
        message: 'Success',
        dedupeKey: 'success',
        createdAtMs: 1_000,
        expiresAtMs: 5_000,
      },
      {
        id: 'notification-2',
        tone: 'error' as const,
        message: 'Error',
        dedupeKey: 'error',
        createdAtMs: 2_000,
        expiresAtMs: 10_000,
      },
    ]

    expect(dismissAppNotification(notifications, 'notification-1')).toEqual([
      {
        id: 'notification-2',
        tone: 'error',
        message: 'Error',
        dedupeKey: 'error',
        createdAtMs: 2_000,
        expiresAtMs: 10_000,
      },
    ])
    expect(expireAppNotifications(notifications, 15_000)).toEqual([
      {
        id: 'notification-2',
        tone: 'error',
        message: 'Error',
        dedupeKey: 'error',
        createdAtMs: 2_000,
        expiresAtMs: 10_000,
      },
    ])
  })

  test('formats runtime timestamps and rendered message lines', () => {
    const createdAtMs = new Date(2026, 3, 13, 14, 49, 36).getTime()
    expect(formatRuntimeTimestamp(createdAtMs)).toBe('2026-04-13 14:49:36')
    expect(formatRuntimeNotificationLine(createdAtMs, 'Sparkplug DCMD.redcon -> 3')).toBe(
      '2026-04-13 14:49:36: Sparkplug DCMD.redcon -> 3',
    )
  })

  test('only emits board video lastError notifications for changed non-empty errors', () => {
    expect(
      getNextBoardVideoLastErrorNotification(
        null,
        "failed to describe signaling channel 'txing-board-video'",
      ),
    ).toBe("failed to describe signaling channel 'txing-board-video'")
    expect(
      getNextBoardVideoLastErrorNotification(
        "failed to describe signaling channel 'txing-board-video'",
        "  failed to describe signaling channel 'txing-board-video'  ",
      ),
    ).toBeNull()
    expect(
      getNextBoardVideoLastErrorNotification(
        "failed to describe signaling channel 'txing-board-video'",
        'token refreshed cleanly',
      ),
    ).toBe('token refreshed cleanly')
    expect(getNextBoardVideoLastErrorNotification('previous', '   ')).toBeNull()
  })

  test('appends log entries and restores them from session storage JSON', () => {
    const notificationLog = appendNotificationLogEntry(
      [],
      {
        tone: 'error',
        message: 'Board video signaling closed',
        dedupeKey: 'board-video-viewer:Board video signaling closed',
      },
      2_000,
      'runtime-log-1',
    )

    expect(notificationLog).toEqual([
      {
        id: 'runtime-log-1',
        tone: 'error',
        message: 'Board video signaling closed',
        dedupeKey: 'board-video-viewer:Board video signaling closed',
        createdAtMs: 2_000,
      },
    ])
    expect(deserializeNotificationLog(serializeNotificationLog(notificationLog))).toEqual(
      notificationLog,
    )
    expect(deserializeNotificationLog('{"invalid":true}')).toEqual([])
  })
})
