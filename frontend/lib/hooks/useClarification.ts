/**
import { debug } from "../utils/debug";
 * React hook for handling clarification requests.
 *
 * Provides state management and API calls for Phase 7: Clarification Pattern.
 */

import { useState, useCallback } from "react";
import { logger } from "@/lib/utils/logger";
import type {
  ClarificationRequest,
  RespondToClarificationRequest,
  RespondToClarificationResponse,
} from "../types/api";
import { sendClarificationResponse } from "../api/clarification";

export interface UseClarificationReturn {
  /** Current active clarification request (if any) */
  activeClarification: ClarificationRequest | null;

  /** Whether a clarification response is being submitted */
  isSubmitting: boolean;

  /** Error from last submission attempt */
  error: Error | null;

  /** Set the active clarification (typically from SSE event) */
  setActiveClarification: (request: ClarificationRequest | null) => void;

  /** Respond with a selected option */
  respondWithOption: (optionId: string, metadata?: Record<string, unknown>) => Promise<void>;

  /** Respond with custom text */
  respondWithCustomText: (text: string, metadata?: Record<string, unknown>) => Promise<void>;

  /** Clear the active clarification */
  clear: () => void;
}

/**
 * Hook for managing clarification requests and responses.
 *
 * This hook:
 * 1. Maintains state for the active clarification request
 * 2. Provides methods to respond with option selection or custom text
 * 3. Handles API submission and error states
 * 4. Integrates with SSE event handling (via setActiveClarification)
 *
 * @example
 * ```tsx
 * const {
 *   activeClarification,
 *   isSubmitting,
 *   respondWithOption,
 *   respondWithCustomText,
 *   setActiveClarification,
 * } = useClarification();
 *
 * // In SSE event handler (EventType.CLARIFICATION_REQUEST):
 * useEffect(() => {
 *   if (event.type === EventType.CLARIFICATION_REQUEST) {
 *     setActiveClarification(event.data as ClarificationRequest);
 *   }
 * }, [event]);
 *
 * // In UI: User clicks option button
 * <button onClick={() => respondWithOption("2")}>Medium</button>
 *
 * // Or: User types custom text
 * <button onClick={() => respondWithCustomText(inputValue)}>Submit</button>
 * ```
 */
export function useClarification(): UseClarificationReturn {
  const [activeClarification, setActiveClarification] =
    useState<ClarificationRequest | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  /**
   * Respond to clarification with a selected option.
   */
  const respondWithOption = useCallback(
    async (optionId: string, metadata?: Record<string, unknown>) => {
      if (!activeClarification) {
        throw new Error("No active clarification to respond to");
      }

      setIsSubmitting(true);
      setError(null);

      try {
        const request: RespondToClarificationRequest = {
          clarification_id: activeClarification.clarification_id,
          response_type: "option_selected",
          selected_option_id: optionId,
          metadata,
        };

        const response: RespondToClarificationResponse =
          await sendClarificationResponse(
            activeClarification.conversation_id,
            activeClarification.clarification_id,
            request
          );

        logger.debug("Clarification response submitted:", response);

        // Clear active clarification after successful submission
        setActiveClarification(null);
      } catch (err) {
        const error = err instanceof Error ? err : new Error(String(err));
        setError(error);
        console.error("Failed to submit clarification response:", error);
        throw error;
      } finally {
        setIsSubmitting(false);
      }
    },
    [activeClarification]
  );

  /**
   * Respond to clarification with custom text.
   */
  const respondWithCustomText = useCallback(
    async (text: string, metadata?: Record<string, unknown>) => {
      if (!activeClarification) {
        throw new Error("No active clarification to respond to");
      }

      if (!text.trim()) {
        throw new Error("Custom text cannot be empty");
      }

      setIsSubmitting(true);
      setError(null);

      try {
        const request: RespondToClarificationRequest = {
          clarification_id: activeClarification.clarification_id,
          response_type: "custom_text",
          custom_text: text.trim(),
          metadata,
        };

        const response: RespondToClarificationResponse =
          await sendClarificationResponse(
            activeClarification.conversation_id,
            activeClarification.clarification_id,
            request
          );

        logger.debug("Clarification response submitted:", response);

        // Clear active clarification after successful submission
        setActiveClarification(null);
      } catch (err) {
        const error = err instanceof Error ? err : new Error(String(err));
        setError(error);
        console.error("Failed to submit clarification response:", error);
        throw error;
      } finally {
        setIsSubmitting(false);
      }
    },
    [activeClarification]
  );

  /**
   * Clear the active clarification.
   */
  const clear = useCallback(() => {
    setActiveClarification(null);
    setError(null);
  }, []);

  return {
    activeClarification,
    isSubmitting,
    error,
    setActiveClarification,
    respondWithOption,
    respondWithCustomText,
    clear,
  };
}

