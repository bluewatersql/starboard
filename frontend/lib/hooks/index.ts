/**
 * Hooks module exports.
 */

// SSE and streaming
export { useSSE } from "./useSSE";
export type { UseSSEOptions } from "./useSSE";

// UI utilities
export { useSlashCommands } from "./useSlashCommands";
export type { SlashCommand } from "./useSlashCommands";

// Authentication
export { useAuth } from "./useAuth";

// Dialog handling
export { useClarification } from "./useClarification";

// Data fetching hooks (React Query)
export { useChartData, isChartExpiredError, ChartExpiredError } from "./useChartData";
export type { UseChartDataOptions, ChartDataResult } from "./useChartData";

export { useTableData, isTableDataExpiredError, TableDataExpiredError } from "./useTableData";
export type { UseTableDataOptions } from "./useTableData";

// Action mutation hooks (React Query)
export { useActionMutation, useSimpleActionMutation } from "./useActionMutation";
export type { ActionParams, ActionResult, UseActionMutationOptions } from "./useActionMutation";

// Confirmation dialog hook
export { useConfirmation } from "./useConfirmation";
export type { ConfirmOptions, UseConfirmationReturn } from "./useConfirmation";

// Keyboard shortcuts
export { useKeyboardShortcuts } from "./useKeyboardShortcuts";
export type { KeyboardShortcutCallbacks } from "./useKeyboardShortcuts";
