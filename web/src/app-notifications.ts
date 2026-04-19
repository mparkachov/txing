export type NotificationTone = "neutral" | "success" | "error";

export type AppNotification = {
  id: string;
  tone: NotificationTone;
  message: string;
  dedupeKey: string;
  createdAtMs: number;
  expiresAtMs: number;
};

export type AppNotificationLogEntry = {
  id: string;
  tone: NotificationTone;
  message: string;
  dedupeKey: string;
  createdAtMs: number;
};

export type AppNotificationInput = {
  tone: NotificationTone;
  message: string;
  dedupeKey: string;
};

export const runtimeNotificationLifetimeMs = 5_000;
export const notificationLogSessionStorageKey =
  "device.runtime-notifications.log";

const padTimestampPart = (value: number): string =>
  String(value).padStart(2, "0");

export const formatRuntimeTimestamp = (createdAtMs: number): string => {
  const timestamp = new Date(createdAtMs);
  return `${timestamp.getFullYear()}-${padTimestampPart(timestamp.getMonth() + 1)}-${padTimestampPart(
    timestamp.getDate(),
  )} ${padTimestampPart(timestamp.getHours())}:${padTimestampPart(
    timestamp.getMinutes(),
  )}:${padTimestampPart(timestamp.getSeconds())}`;
};

export const formatRuntimeNotificationLine = (
  createdAtMs: number,
  message: string,
): string => `${formatRuntimeTimestamp(createdAtMs)}: ${message}`;

export const normalizeRuntimeMessage = (
  message: string | null | undefined,
): string | null => {
  if (typeof message !== "string") {
    return null;
  }

  const normalizedMessage = message.trim();
  return normalizedMessage ? normalizedMessage : null;
};

export const enqueueAppNotification = (
  notifications: AppNotification[],
  notification: AppNotificationInput,
  nowMs: number,
  nextId: string,
): AppNotification[] => {
  const activeNotification = notifications.find(
    (candidate) => candidate.dedupeKey === notification.dedupeKey,
  );
  const nextNotification: AppNotification = {
    id: activeNotification?.id ?? nextId,
    tone: notification.tone,
    message: notification.message,
    dedupeKey: notification.dedupeKey,
    createdAtMs: nowMs,
    expiresAtMs: nowMs + runtimeNotificationLifetimeMs,
  };

  return [
    nextNotification,
    ...notifications.filter(
      (candidate) => candidate.dedupeKey !== notification.dedupeKey,
    ),
  ];
};

export const appendNotificationLogEntry = (
  notificationLog: AppNotificationLogEntry[],
  notification: AppNotificationInput,
  nowMs: number,
  nextId: string,
): AppNotificationLogEntry[] => [
  {
    id: nextId,
    tone: notification.tone,
    message: notification.message,
    dedupeKey: notification.dedupeKey,
    createdAtMs: nowMs,
  },
  ...notificationLog,
];

export const dismissAppNotification = (
  notifications: AppNotification[],
  notificationId: string,
): AppNotification[] =>
  notifications.filter((notification) => notification.id !== notificationId);

export const expireAppNotifications = (
  notifications: AppNotification[],
  nowMs: number,
): AppNotification[] =>
  notifications.filter((notification) => notification.expiresAtMs > nowMs);

export const getNextBoardVideoLastErrorNotification = (
  previousLastError: string | null,
  nextLastError: string | null,
  hasObservedInitialValue = true,
): string | null => {
  const normalizedPrevious = normalizeRuntimeMessage(previousLastError);
  const normalizedNext = normalizeRuntimeMessage(nextLastError);
  if (!hasObservedInitialValue) {
    return null;
  }
  if (!normalizedNext || normalizedNext === normalizedPrevious) {
    return null;
  }
  return normalizedNext;
};

const isNotificationTone = (value: unknown): value is NotificationTone =>
  value === "neutral" || value === "success" || value === "error";

const isLogEntryShape = (value: unknown): value is AppNotificationLogEntry => {
  if (!value || typeof value !== "object") {
    return false;
  }

  const candidate = value as Partial<AppNotificationLogEntry>;
  return (
    typeof candidate.id === "string" &&
    isNotificationTone(candidate.tone) &&
    typeof candidate.message === "string" &&
    typeof candidate.dedupeKey === "string" &&
    typeof candidate.createdAtMs === "number" &&
    Number.isFinite(candidate.createdAtMs)
  );
};

export const serializeNotificationLog = (
  notificationLog: AppNotificationLogEntry[],
): string => JSON.stringify(notificationLog);

export const deserializeNotificationLog = (
  rawValue: string | null,
): AppNotificationLogEntry[] => {
  if (!rawValue) {
    return [];
  }

  try {
    const parsed = JSON.parse(rawValue) as unknown;
    if (!Array.isArray(parsed)) {
      return [];
    }
    return parsed.filter(isLogEntryShape);
  } catch {
    return [];
  }
};
