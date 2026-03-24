/**
 * React Query mutation hook for action execution.
 *
 * Provides consistent error handling and success feedback for user actions.
 * Integrates with the notification system for user feedback.
 */

import { useMutation, UseMutationResult } from "@tanstack/react-query";
import { useUIStore } from "@/lib/store/uiStore";

export interface ActionParams {
  /** Action identifier */
  actionId: string;
  /** ID of the recommendation these actions apply to */
  recommendationId: string;
  /** Additional action-specific data */
  data?: Record<string, unknown>;
}

export interface ActionResult {
  /** Whether the action succeeded */
  success: boolean;
  /** Optional message from the action */
  message?: string;
}

export interface UseActionMutationOptions {
  /** Callback when action is performed */
  onAction: (
    actionId: string,
    recommendationId: string,
    data?: Record<string, unknown>
  ) => void | Promise<void>;
  /** Custom success message (defaults to "Action completed successfully") */
  successMessage?: string;
  /** Whether to show success notification (defaults to true) */
  showSuccessNotification?: boolean;
  /** Whether to show error notification (defaults to true) */
  showErrorNotification?: boolean;
}

/**
 * React Query mutation hook for executing actions with notifications.
 *
 * @param options - Hook options including action callback and notification settings
 * @returns Mutation result with execute function and state
 *
 * @example
 * ```tsx
 * const mutation = useActionMutation({
 *   onAction: async (actionId, recId) => {
 *     await api.executeAction(actionId, recId);
 *   },
 *   successMessage: "Recommendation applied!",
 * });
 *
 * // Execute the action
 * mutation.mutate({
 *   actionId: "mark_applied",
 *   recommendationId: "rec-123",
 * });
 *
 * // Check state
 * if (mutation.isPending) return <CircularProgress />;
 * if (mutation.isSuccess) return <CheckIcon />;
 * ```
 */
export function useActionMutation({
  onAction,
  successMessage = "Action completed successfully",
  showSuccessNotification = true,
  showErrorNotification = true,
}: UseActionMutationOptions): UseMutationResult<
  ActionResult,
  Error,
  ActionParams
> {
  const addNotification = useUIStore((s) => s.addNotification);

  return useMutation({
    mutationFn: async ({
      actionId,
      recommendationId,
      data,
    }: ActionParams): Promise<ActionResult> => {
      await onAction(actionId, recommendationId, data);
      return { success: true, message: successMessage };
    },
    onSuccess: (result) => {
      if (showSuccessNotification) {
        addNotification({
          message: result.message || successMessage,
          type: "success",
          duration: 3000,
        });
      }
    },
    onError: (error: Error) => {
      if (showErrorNotification) {
        addNotification({
          message: error.message || "Action failed. Please try again.",
          type: "error",
          duration: 5000,
        });
      }
    },
  });
}

/**
 * Simple action mutation without notification integration.
 * Use when you want to handle success/error states manually.
 */
export function useSimpleActionMutation(
  onAction: (
    actionId: string,
    recommendationId: string,
    data?: Record<string, unknown>
  ) => void | Promise<void>
): UseMutationResult<void, Error, ActionParams> {
  return useMutation({
    mutationFn: async ({
      actionId,
      recommendationId,
      data,
    }: ActionParams): Promise<void> => {
      await onAction(actionId, recommendationId, data);
    },
  });
}

