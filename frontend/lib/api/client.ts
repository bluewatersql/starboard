/**
 * API client for Starboard Chat backend.
 *
 * Provides typed HTTP client functions for all backend endpoints.
 */

import type {
  APIError,
  ConversationHistory,
  ConversationResponse,
  CreateConversationRequest,
  MessageResponse,
  SendMessageRequest,
  ServerConfig,
  SubmitFeedbackRequest,
  SubmitFeedbackResponse,
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
 * Custom error class for authentication failures.
 */
export class AuthenticationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "AuthenticationError";
  }
}

/**
 * Custom error class for rate limit exceeded.
 * Includes retry-after information when available.
 */
export class RateLimitError extends Error {
  /** Seconds to wait before retrying (from Retry-After header) */
  retryAfter: number | null;

  constructor(message: string, retryAfter: number | null = null) {
    super(message);
    this.name = "RateLimitError";
    this.retryAfter = retryAfter;
  }
}

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
      // Handle authentication failures specifically
      if (response.status === 401) {
        const error: APIError = await response.json().catch(() => ({
          detail: "Authentication required",
          status_code: 401,
        }));
        throw new AuthenticationError(error.detail);
      }

      // Handle rate limit exceeded (429)
      if (response.status === 429) {
        const retryAfterHeader = response.headers.get("Retry-After");
        const retryAfter = retryAfterHeader ? parseInt(retryAfterHeader, 10) : null;
        throw new RateLimitError(
          "Too many requests. Please wait a moment and try again.",
          retryAfter
        );
      }

      const error: APIError = await response.json().catch(() => ({
        detail: `HTTP ${response.status}: ${response.statusText}`,
        status_code: response.status,
      }));
      throw new Error(error.detail);
    }

    // Handle 204 No Content
    if (response.status === 204) {
      return {} as T;
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
// Conversation API
// ============================================================================

/**
 * Create a new conversation.
 */
export async function createConversation(
  request: CreateConversationRequest
): Promise<ConversationResponse> {
  return fetchJson<ConversationResponse>("/chat/conversations", {
    method: "POST",
    body: JSON.stringify(request),
  });
}

/**
 * List all conversations for the authenticated user.
 * 
 * Note: User filtering is now done automatically by the backend
 * based on the authenticated user from the auth middleware.
 */
export async function listConversations(): Promise<ConversationResponse[]> {
  return fetchJson<ConversationResponse[]>(`/chat/conversations`);
}

/**
 * Get conversation history.
 */
export async function getConversationHistory(
  conversationId: string
): Promise<ConversationHistory> {
  return fetchJson<ConversationHistory>(
    `/chat/conversations/${conversationId}/history`
  );
}

/**
 * Export a conversation in the specified format.
 * Returns the raw text content (markdown or JSON string).
 */
export async function exportConversation(
  conversationId: string,
  format: "markdown" | "json" = "markdown"
): Promise<string> {
  const url = `${getApiUrl()}/chat/conversations/${conversationId}/export?format=${format}`;
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json" },
  });
  if (!response.ok) {
    throw new Error(`Export failed: ${response.status}`);
  }
  return response.text();
}

/**
 * Delete a conversation.
 */
export async function deleteConversation(
  conversationId: string
): Promise<void> {
  return fetchJson<void>(`/chat/conversations/${conversationId}`, {
    method: "DELETE",
  });
}

/**
 * Delete all conversations for the authenticated user (batch operation).
 *
 * Much more efficient than calling deleteConversation in a loop.
 * The backend handles this as a single database operation.
 */
export async function deleteAllConversations(): Promise<void> {
  return fetchJson<void>("/chat/conversations", {
    method: "DELETE",
  });
}

// ============================================================================
// Message API
// ============================================================================

/**
 * Send a message to a conversation.
 */
export async function sendMessage(
  conversationId: string,
  request: SendMessageRequest
): Promise<MessageResponse> {
  return fetchJson<MessageResponse>(
    `/chat/conversations/${conversationId}/messages`,
    {
      method: "POST",
      body: JSON.stringify(request),
    }
  );
}

// ============================================================================
// Configuration API
// ============================================================================

/**
 * Get server configuration including domain model defaults.
 */
export async function getServerConfig(): Promise<ServerConfig> {
  return fetchJson<{
    default_model: string;
    default_temperature: number;
    default_max_tokens: number;
    domain_model_overrides: Record<string, string>;
    domain_temperature_overrides: Record<string, number>;
  }>("/chat/config");
}

// ============================================================================
// Feedback API (Pattern 4: Feedback Collection)
// ============================================================================

/**
 * Submit feedback for a message.
 */
export async function submitFeedback(
  conversationId: string,
  request: SubmitFeedbackRequest
): Promise<SubmitFeedbackResponse> {
  return fetchJson<SubmitFeedbackResponse>(
    `/conversations/${conversationId}/feedback`,
    {
      method: "POST",
      body: JSON.stringify(request),
    }
  );
}

// ============================================================================
// Health Check
// ============================================================================

/**
 * Check API health.
 */
export async function checkHealth(): Promise<{
  status: string;
  service: string;
  version: string;
}> {
  return fetchJson<{ status: string; service: string; version: string }>(
    "/chat/health"
  );
}

// ============================================================================
// Exports
// ============================================================================

export const api = {
  createConversation,
  listConversations,
  getConversationHistory,
  exportConversation,
  deleteConversation,
  deleteAllConversations,
  sendMessage,
  submitFeedback,
  getServerConfig,
  checkHealth,
  getApiUrl,
};

// AuthenticationError is already exported via 'export class' above

