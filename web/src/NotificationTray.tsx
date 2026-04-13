import {
  formatRuntimeNotificationLine,
  formatRuntimeTimestamp,
  type AppNotification,
} from './app-notifications'

type NotificationTrayProps = {
  notifications: AppNotification[]
  onDismiss: (notificationId: string) => void
}

function NotificationTray({ notifications, onDismiss }: NotificationTrayProps) {
  if (notifications.length === 0) {
    return null
  }

  return (
    <section
      className="notification-tray"
      aria-label="Runtime messages"
      aria-live="polite"
      aria-atomic="false"
    >
      {notifications.map((notification) => (
        <article
          key={notification.id}
          className={`notification-card notification-card-${notification.tone}`}
        >
          <p className="notification-message">
            <time
              className="notification-message-time"
              dateTime={new Date(notification.createdAtMs).toISOString()}
            >
              {formatRuntimeTimestamp(notification.createdAtMs)}
            </time>
            <span className="notification-message-separator" aria-hidden="true">
              :{' '}
            </span>
            <span>{notification.message}</span>
          </p>
          <button
            type="button"
            className="notification-dismiss"
            aria-label={`Dismiss notification: ${formatRuntimeNotificationLine(
              notification.createdAtMs,
              notification.message,
            )}`}
            onClick={() => {
              onDismiss(notification.id)
            }}
          >
            <span aria-hidden="true">×</span>
          </button>
        </article>
      ))}
    </section>
  )
}

export default NotificationTray
