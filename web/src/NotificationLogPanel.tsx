import {
  formatRuntimeTimestamp,
  type AppNotificationLogEntry,
} from './app-notifications'

type NotificationLogPanelProps = {
  notificationLog: AppNotificationLogEntry[]
}

function NotificationLogPanel({ notificationLog }: NotificationLogPanelProps) {
  return (
    <section className="card notification-log-panel" aria-label="Current session runtime log">
      <div className="notification-log-header">
        <div>
          <h2 className="notification-log-title">Session Log</h2>
          <p className="notification-log-subtitle">Runtime messages stored for this browser session</p>
        </div>
        <span className="notification-log-count">
          {notificationLog.length} {notificationLog.length === 1 ? 'message' : 'messages'}
        </span>
      </div>

      {notificationLog.length === 0 ? (
        <p className="notification-log-empty">No runtime messages in this session yet.</p>
      ) : (
        <div className="notification-log-list" role="list">
          {notificationLog.map((entry) => (
            <article
              key={entry.id}
              role="listitem"
              className={`notification-log-entry notification-log-entry-${entry.tone}`}
            >
              <p className="notification-log-message">
                <time
                  className="notification-log-time"
                  dateTime={new Date(entry.createdAtMs).toISOString()}
                >
                  {formatRuntimeTimestamp(entry.createdAtMs)}
                </time>
                <span className="notification-log-separator" aria-hidden="true">
                  :{' '}
                </span>
                <span>{entry.message}</span>
              </p>
            </article>
          ))}
        </div>
      )}
    </section>
  )
}

export default NotificationLogPanel
