type LogLevel = "info" | "warn" | "error";
type LogMetadata = Record<string, string | number | boolean | null | undefined>;

const appLogPrefix = "[pdf-chat]";

function shouldLog() {
  return import.meta.env.DEV || import.meta.env.VITE_ENABLE_FRONTEND_LOGS === "true";
}

function write(level: LogLevel, event: string, metadata: LogMetadata = {}) {
  if (!shouldLog()) return;

  const payload = {
    event,
    ...metadata
  };

  if (level === "error") {
    console.error(appLogPrefix, payload);
    return;
  }

  if (level === "warn") {
    console.warn(appLogPrefix, payload);
    return;
  }

  console.info(appLogPrefix, payload);
}

export const logger = {
  info: (event: string, metadata?: LogMetadata) => write("info", event, metadata),
  warn: (event: string, metadata?: LogMetadata) => write("warn", event, metadata),
  error: (event: string, metadata?: LogMetadata) => write("error", event, metadata)
};
