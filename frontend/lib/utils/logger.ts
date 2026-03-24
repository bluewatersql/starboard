type LogLevel = "debug" | "info" | "warn" | "error";

const LOG_LEVELS: Record<LogLevel, number> = {
  debug: 0,
  info: 1,
  warn: 2,
  error: 3,
};

const currentLevel: LogLevel =
  process.env.NODE_ENV === "production" ? "warn" : "debug";

export const logger = {
  debug: (...args: unknown[]) => {
    if (LOG_LEVELS.debug >= LOG_LEVELS[currentLevel]) {
      console.debug("[DEBUG]", ...args);
    }
  },
  info: (...args: unknown[]) => {
    if (LOG_LEVELS.info >= LOG_LEVELS[currentLevel]) {
      console.info("[INFO]", ...args);
    }
  },
  warn: (...args: unknown[]) => {
    if (LOG_LEVELS.warn >= LOG_LEVELS[currentLevel]) {
      console.warn("[WARN]", ...args);
    }
  },
  error: (...args: unknown[]) => {
    console.error("[ERROR]", ...args);
  },
};
