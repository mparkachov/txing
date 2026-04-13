import type { AppNotification } from './app-notifications'

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
      aria-label="Runtime notifications"
      aria-live="polite"
      aria-atomic="false"
    >
      {notifications.map((notification) => (
        <article
          key={notification.id}
          className={`notification-card notification-card-${notification.tone}`}
        >
          <p className="notification-message">{notification.message}</p>
          <button
            type="button"
            className="notification-dismiss"
            aria-label={`Dismiss notification: ${notification.message}`}
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
