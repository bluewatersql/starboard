/**
 * LazyCodeBlock component.
 *
 * Wraps CodeBlockWithActions with React.lazy + Suspense so that the
 * Shiki (~200 KB) syntax-highlighting bundle is only downloaded when
 * a code block is about to be rendered.
 *
 * Drop-in replacement for CodeBlockWithActions — identical props interface.
 *
 * NOTE: Do NOT use this wrapper inside streaming message rendering.
 * During streaming, CodeBlockWithActions already skips Shiki work.
 * Using lazy here in that context would cause visible flicker as the
 * Suspense boundary mounts and unmounts with each SSE chunk.
 * Use the lazy version only for static/completed message code blocks
 * or standalone code block usages outside the stream path.
 */

"use client";

import React, { Suspense, lazy } from "react";
import { CodeBlockSkeleton } from "@/components/common/skeletons";
import type { CodeBlockWithActionsProps } from "@/components/chat/CodeBlockWithActions";

// Lazy-load the full code block (pulls in Shiki)
const CodeBlockWithActions = lazy(() =>
  import("@/components/chat/CodeBlockWithActions").then((mod) => ({
    default: mod.CodeBlockWithActions,
  }))
);

export interface LazyCodeBlockProps extends CodeBlockWithActionsProps {
  /** Number of skeleton lines to show while loading (default: 4) */
  skeletonLines?: number;
}

/**
 * Lazy-loading wrapper for CodeBlockWithActions.
 *
 * Shows a CodeBlockSkeleton while the Shiki bundle downloads, then
 * renders the full syntax-highlighted, interactive code block.
 *
 * @example
 * ```tsx
 * <LazyCodeBlock
 *   code="SELECT * FROM users;"
 *   language="sql"
 *   showLineNumbers
 * />
 * ```
 */
export function LazyCodeBlock({
  skeletonLines = 4,
  ...props
}: LazyCodeBlockProps) {
  return (
    <Suspense fallback={<CodeBlockSkeleton lines={skeletonLines} />}>
      <CodeBlockWithActions {...props} />
    </Suspense>
  );
}
