/**
 * Custom code component for ReactMarkdown that renders syntax-highlighted code blocks.
 * Uses CodeBlockWithActions for multi-line code blocks, plain code for inline.
 * 
 * Note: react-markdown v10.x changed how `inline` is passed - it may be undefined
 * for inline code. We use multiple heuristics to detect block vs inline code to
 * prevent hydration errors (div inside p).
 */

"use client";

import React from "react";
import { CodeBlockWithActions } from "../CodeBlockWithActions";

export interface MarkdownCodeRendererProps {
  inline?: boolean;
  className?: string;
  children?: React.ReactNode;
  node?: { tagName?: string; position?: { start?: { line?: number }; end?: { line?: number } } };
}

export const MarkdownCodeRenderer: React.FC<MarkdownCodeRendererProps> = ({
  inline,
  className,
  children,
  ...props
}) => {
  const match = /language-(\w+)/.exec(className || "");
  const language = match ? match[1] : "";
  const code = String(children).replace(/\n$/, "");

  // Determine if this is inline code using multiple heuristics:
  // 1. Explicit inline prop (may be undefined in react-markdown v10.x)
  // 2. No language class (fenced code blocks have language-* class)
  // 3. Single line content (no newlines)
  // 4. Short content (inline code is typically short)
  const hasNewlines = code.includes("\n");
  const hasLanguageClass = Boolean(className && className.includes("language-"));
  const isShortContent = code.length < 100;
  
  // Consider it inline if:
  // - explicit inline=true, OR
  // - no language class AND no newlines AND reasonably short
  const isInlineCode = inline === true || 
    (inline !== false && !hasLanguageClass && !hasNewlines && isShortContent);

  // Inline code - render as <code> (valid inside <p>)
  if (isInlineCode) {
    return (
      <code
        style={{
          backgroundColor: "rgba(0, 0, 0, 0.05)",
          padding: "2px 6px",
          borderRadius: "4px",
          fontSize: "0.9em",
          fontFamily: "'JetBrains Mono', 'Fira Code', Consolas, monospace",
        }}
        {...props}
      >
        {children}
      </code>
    );
  }

  // Multi-line code block - use CodeBlockWithActions
  // This is a block-level element and must NOT be inside a <p>
  // Auto-enable line numbers for blocks > 10 lines
  const lineCount = code.split("\n").length;
  const showLineNumbers = lineCount > 10;

  // If language is specified via markdown (```python), use it
  // Otherwise, let CodeBlockWithActions auto-detect from content
  return (
    <CodeBlockWithActions
      code={code}
      language={language || undefined}
      showLineNumbers={showLineNumbers}
    />
  );
};

