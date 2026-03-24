/**
 * Frontend extensions to generated Zod schemas.
 *
 * This file contains Zod schemas for types that are:
 * 1. Frontend-only (not in backend Pydantic models)
 * 2. Referenced by generated code but need frontend-specific handling
 *
 * DO NOT modify generated-schemas.ts directly - it will be overwritten.
 * Add frontend-only schemas here instead.
 *
 * The generation script (scripts/generate_types.py) imports these schemas
 * when generating generated-schemas.ts.
 */

import { z } from "zod";

// ============================================================================
// Frontend-Only Schemas (not in backend)
// ============================================================================

/**
 * Tool call status - frontend-only type.
 */
export const ToolCallStatusSchema = z.enum([
  "completed",
  "failed",
  "running",
  "pending",
]);
export type ToolCallStatus = z.infer<typeof ToolCallStatusSchema>;

/**
 * Tool call information - frontend-only schema.
 * Used for displaying tool execution details in the UI.
 *
 * NOTE: This type is NOT in the backend Pydantic models. It's used
 * by the frontend to track tool execution state during agent reasoning.
 */
export const ToolCallSchema = z.object({
  /** Unique tool call identifier */
  tool_call_id: z.string().optional(),
  /** Tool name (e.g., "fetch_table_metadata") */
  tool_name: z.string(),
  /** Human-readable tool name (e.g., "Fetch Table Metadata") */
  friendly_name: z.string().optional(),
  /** Tool execution status */
  status: ToolCallStatusSchema.optional(),
  /** Tool arguments/parameters */
  arguments: z.record(z.string(), z.unknown()).optional(),
  /** Tool execution result */
  result: z.unknown().optional(),
  /** Error message if tool failed */
  error: z.string().optional(),
  /** Execution duration in milliseconds */
  duration_ms: z.number().optional(),
});
export type ToolCall = z.infer<typeof ToolCallSchema>;
