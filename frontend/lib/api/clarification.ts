/**
 * API client for clarification endpoints.
 *
 * Provides typed HTTP client functions for Phase 7: Clarification Pattern.
 */

import type {
  RespondToClarificationRequest,
  RespondToClarificationResponse,
  APIError,
} from "../types/api";

/**
 * Get API base URL from environment.
 */
const getApiUrl = (): string => {
  const url = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
  const basePath = process.env.NEXT_PUBLIC_API_BASE_PATH || "/api";
  return `${url}${basePath}`;
};

/**
 * Fetch wrapper with error handling.
 */
async function fetchJson<T>(
  endpoint: string,
  options?: RequestInit
): Promise<T> {
  const url = `${getApiUrl()}${endpoint}`;

  try {
    const response = await fetch(url, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        ...options?.headers,
      },
    });

    if (!response.ok) {
      const error: APIError = await response.json().catch(() => ({
        detail: `HTTP ${response.status}: ${response.statusText}`,
        status_code: response.status,
      }));
      throw new Error(error.detail);
    }

    return await response.json();
  } catch (error) {
    if (error instanceof Error) {
      throw error;
    }
    throw new Error("Network error");
  }
}

// ============================================================================
// Clarification API
// ============================================================================

/**
 * Respond to a clarification request.
 *
 * @param conversationId - ID of the conversation
 * @param clarificationId - ID of the clarification request
 * @param request - Response data (option selection or custom text)
 * @returns Response with enriched query and status
 *
 * @example
 * ```ts
 * // User selects option 2
 * const response = await sendClarificationResponse(
 *   "conv_123",
 *   "clar_abc",
 *   {
 *     clarification_id: "clar_abc",
 *     response_type: "option_selected",
 *     selected_option_id: "2",
 *   }
 * );
 *
 * // User provides custom text
 * const response = await sendClarificationResponse(
 *   "conv_123",
 *   "clar_abc",
 *   {
 *     clarification_id: "clar_abc",
 *     response_type: "custom_text",
 *     custom_text: "my-custom-warehouse",
 *   }
 * );
 * ```
 */
export async function sendClarificationResponse(
  conversationId: string,
  clarificationId: string,
  request: RespondToClarificationRequest
): Promise<RespondToClarificationResponse> {
  return fetchJson<RespondToClarificationResponse>(
    `/conversations/${conversationId}/clarifications/${clarificationId}/respond`,
    {
      method: "POST",
      body: JSON.stringify(request),
    }
  );
}

