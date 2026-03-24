/**
 * Debug utility for conditional console logging.
 * 
 * Respects NEXT_PUBLIC_DEBUG environment variable:
 * - Set to "true" or "1" to enable debug logging
 * - Unset or "false" to disable (production mode)
 * 
 * Usage:
 *   import { debug } from '@/lib/utils/debug';
 *   debug.log('Debug message:', data);
 *   debug.warn('Warning:', issue);
 *   debug.error('Error:', error); // Always logs in production
 */

const IS_DEBUG = process.env.NEXT_PUBLIC_DEBUG === 'true' || 
                 process.env.NEXT_PUBLIC_DEBUG === '1' ||
                 process.env.NODE_ENV === 'development';

/**
 * Get timestamp in format HH:MM:SS.mmm for correlation with backend logs.
 */
function getTimestamp(): string {
  const now = new Date();
  const hours = now.getHours().toString().padStart(2, '0');
  const mins = now.getMinutes().toString().padStart(2, '0');
  const secs = now.getSeconds().toString().padStart(2, '0');
  const ms = now.getMilliseconds().toString().padStart(3, '0');
  return `${hours}:${mins}:${secs}.${ms}`;
}

export const debug = {
  /**
   * Log debug information (only in debug mode)
   */
  log: (...args: unknown[]): void => {
    if (IS_DEBUG) {
      console.log(`[${getTimestamp()}]`, ...args);
    }
  },

  /**
   * Log warnings (only in debug mode)
   */
  warn: (...args: unknown[]): void => {
    if (IS_DEBUG) {
      console.warn(`[${getTimestamp()}]`, ...args);
    }
  },

  /**
   * Log errors (ALWAYS logs, even in production)
   */
  error: (...args: unknown[]): void => {
    console.error(`[${getTimestamp()}]`, ...args);
  },

  /**
   * Log info messages (only in debug mode)
   */
  info: (...args: unknown[]): void => {
    if (IS_DEBUG) {
      console.info(`[${getTimestamp()}]`, ...args);
    }
  },

  /**
   * Check if debug mode is enabled
   */
  isEnabled: (): boolean => IS_DEBUG,
};

/**
 * Performance timing utility (only measures in debug mode)
 */
export const debugTime = {
  start: (label: string): void => {
    if (IS_DEBUG) {
      console.time(label);
    }
  },

  end: (label: string): void => {
    if (IS_DEBUG) {
      console.timeEnd(label);
    }
  },
};

