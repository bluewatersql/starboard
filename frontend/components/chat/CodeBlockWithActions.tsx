/**
 * CodeBlockWithActions component.
 *
 * Syntax-highlighted code block with copy functionality, line numbers,
 * and optional apply button. Uses Shiki for accurate syntax highlighting.
 */

"use client";

import React, { useState, useEffect, useMemo, useRef } from "react";
import { Box, IconButton, Typography, Paper, Tooltip } from "@mui/material";
import ContentCopyIcon from "@mui/icons-material/ContentCopy";
import CheckIcon from "@mui/icons-material/Check";
import WrapTextIcon from "@mui/icons-material/WrapText";
import FormatAlignLeftIcon from "@mui/icons-material/FormatAlignLeft";
import { sanitizeShikiHtml } from "@/lib/utils/sanitize";
import { useTheme } from "@mui/material/styles";
import { useMessageStore } from "@/lib/store/messageStore";

export interface CodeBlockWithActionsProps {
  /** The code to display */
  code: string;
  /** Programming language for syntax highlighting */
  language?: string;
  /** Optional filename to display */
  filename?: string;
  /** Whether to show line numbers (auto-enabled for >10 lines) */
  showLineNumbers?: boolean;
  /** Lines to highlight (1-indexed) */
  highlightLines?: number[];
  /** Maximum height of the code block */
  maxHeight?: string;
  /** Whether to show the wrap toggle button */
  enableWrapToggle?: boolean;
  /** Callback when Apply button is clicked (renders button if provided) */
  onApply?: (code: string) => void;
}

// Shiki highlighter instance (lazily loaded)
import type { Highlighter } from "shiki";

let shikiHighlighter: Highlighter | null = null;
let shikiLoadPromise: Promise<Highlighter | null> | null = null;

/**
 * Load Shiki highlighter lazily.
 */
async function getHighlighter() {
  if (shikiHighlighter) {
    return shikiHighlighter;
  }

  if (!shikiLoadPromise) {
    shikiLoadPromise = (async () => {
      try {
        const shiki = await import("shiki");
        shikiHighlighter = await shiki.createHighlighter({
          themes: ["github-dark", "github-light"],
          langs: ["sql", "python", "scala", "json", "yaml", "bash", "typescript", "javascript", "plaintext"],
        });
        return shikiHighlighter;
      } catch (error) {
        console.error("Failed to load Shiki highlighter:", error);
        return null;
      }
    })();
  }

  return shikiLoadPromise;
}

/**
 * Auto-detect programming language from code content.
 * Returns the detected language or "text" if unable to determine.
 */
function detectLanguage(code: string): string {
  const trimmed = code.trim();
  
  // SQL patterns
  const sqlKeywords = /^(select|insert|update|delete|create|alter|drop|with|explain|show|describe|use|from|where|join|group by|order by|having|limit|union|into|values|set|grant|revoke)\b/i;
  const sqlPatterns = /(select\s+.+\s+from|insert\s+into|update\s+.+\s+set|delete\s+from|create\s+(table|view|index|database)|alter\s+table|drop\s+(table|view|index))/i;
  if (sqlKeywords.test(trimmed) || sqlPatterns.test(trimmed)) {
    return "sql";
  }
  
  // JSON patterns - starts with { or [, or contains clear JSON structure
  if (/^\s*[\[{]/.test(trimmed)) {
    try {
      JSON.parse(trimmed);
      return "json";
    } catch {
      // Not valid JSON, continue checking
    }
  }
  
  // YAML patterns - key: value structure, or starts with ---
  if (/^---\s*$/m.test(trimmed) || /^\s*[\w-]+:\s*[^\[{]/.test(trimmed)) {
    // Check it's not Python (which also uses :)
    if (!/^\s*(def|class|import|from|if|for|while|try|except|with|return|yield|lambda|async|await)\b/.test(trimmed)) {
      return "yaml";
    }
  }
  
  // Python patterns
  const pythonPatterns = /^(import\s+|from\s+\w+\s+import|def\s+\w+\s*\(|class\s+\w+|if\s+__name__\s*==|print\s*\(|#\s*!.*python|@\w+\s*(\(|$)|async\s+def|await\s+)/m;
  if (pythonPatterns.test(trimmed)) {
    return "python";
  }
  
  // Scala patterns
  const scalaPatterns = /^(package\s+|import\s+\w+\.\w+|object\s+\w+|class\s+\w+|trait\s+\w+|def\s+\w+\s*[\[(]|val\s+\w+\s*[=:]|var\s+\w+\s*[=:]|case\s+class|sealed\s+(trait|class)|implicit\s+)/m;
  if (scalaPatterns.test(trimmed)) {
    return "scala";
  }
  
  // JavaScript/TypeScript patterns
  const jsPatterns = /^(const\s+|let\s+|var\s+|function\s+|export\s+(default\s+)?|import\s+.+\s+from|class\s+\w+\s*\{|interface\s+\w+|type\s+\w+\s*=|=>|\(\)\s*=>)/m;
  if (jsPatterns.test(trimmed)) {
    // Check for TypeScript-specific syntax
    if (/:\s*(string|number|boolean|void|any|unknown|never)\b|<\w+>|interface\s+|type\s+\w+\s*=/.test(trimmed)) {
      return "typescript";
    }
    return "javascript";
  }
  
  // Bash/Shell patterns
  const bashPatterns = /^(#!\/bin\/(ba)?sh|export\s+\w+=|echo\s+|source\s+|alias\s+|\.\s+\w+|if\s+\[\[?|for\s+\w+\s+in|while\s+\[\[?|function\s+\w+\s*\{|\$\(|`\w+`)/m;
  if (bashPatterns.test(trimmed)) {
    return "bash";
  }
  
  // Default to SQL for Databricks-related content (common in this app)
  if (/spark\.|databricks|dbfs|delta|parquet|hive/i.test(trimmed)) {
    return "sql";
  }
  
  // Default fallback - use plain text, not SQL
  return "text";
}

/**
 * CodeBlockWithActions component.
 *
 * Features:
 * - Shiki syntax highlighting for SQL, Python, Scala, JSON, Bash
 * - Copy to clipboard with visual feedback
 * - Optional line numbers (auto-enabled for >10 lines)
 * - Line highlighting
 * - Wrap toggle
 * - Optional Apply button
 *
 * @example
 * ```tsx
 * <CodeBlockWithActions
 *   code="SELECT * FROM users WHERE id = 1;"
 *   language="sql"
 *   showLineNumbers
 * />
 * ```
 */
export function CodeBlockWithActions({
  code,
  language,
  filename,
  showLineNumbers,
  highlightLines = [],
  maxHeight = "500px",
  enableWrapToggle = true,
  onApply,
}: CodeBlockWithActionsProps) {
  const theme = useTheme();
  const isDark = theme.palette.mode === "dark";
  
  // Check if any message is currently streaming - skip expensive Shiki highlighting during streaming
  // to prevent "Maximum update depth exceeded" errors from rapid SSE updates
  const isStreaming = useMessageStore((state) => state.streamingMessageId !== null);
  
  const [copied, setCopied] = useState(false);
  const [isWrapped, setIsWrapped] = useState(true);
  const [highlightedHtml, setHighlightedHtml] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  const trimmedCode = code.trim();
  const lines = trimmedCode.split("\n");
  const lineCount = lines.length;
  
  // Auto-enable line numbers for code > 10 lines or if highlight lines specified
  const shouldShowLineNumbers = showLineNumbers ?? (lineCount > 10 || highlightLines.length > 0);

  // Determine language: use provided, or auto-detect
  const effectiveLanguage = useMemo(() => {
    if (language && language !== "auto" && language !== "") {
      return language;
    }
    // Auto-detect language from code content
    const detected = detectLanguage(trimmedCode);
    return detected;
  }, [language, trimmedCode]);

  // Derived language badge + Shiki language key (avoid setState in effect).
  const normalizedLang = useMemo(() => {
    const langMap: Record<string, string> = {
      sql: "sql",
      python: "python",
      py: "python",
      scala: "scala",
      json: "json",
      yaml: "yaml",
      yml: "yaml",
      bash: "bash",
      sh: "bash",
      shell: "bash",
      typescript: "typescript",
      ts: "typescript",
      javascript: "javascript",
      js: "javascript",
      text: "plaintext",
      plaintext: "plaintext",
      plain: "plaintext",
      txt: "plaintext",
    };
    return langMap[effectiveLanguage.toLowerCase()] || "plaintext";
  }, [effectiveLanguage]);

  // Track pending highlight timeout to debounce during rapid streaming updates
  const highlightTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastHighlightedCodeRef = useRef<string>("");

  // Load syntax highlighting - SKIP during streaming to prevent infinite loops
  // When SSE events rapidly update content, Shiki async highlighting + setState
  // can cause "Maximum update depth exceeded" errors
  useEffect(() => {
    // Skip effect entirely during streaming - no state updates at all
    // This prevents the cascading re-renders that cause infinite loops
    if (isStreaming) {
      return;
    }

    let mounted = true;

    async function highlight() {
      try {
        const highlighter = await getHighlighter();
        if (!highlighter || !mounted) {
          setIsLoading(false);
          return;
        }

        const themeName = isDark ? "github-dark" : "github-light";

        const html = highlighter.codeToHtml(trimmedCode, {
          lang: normalizedLang,
          theme: themeName,
        });

        if (mounted) {
          lastHighlightedCodeRef.current = trimmedCode;
          setHighlightedHtml(html);
          setIsLoading(false);
        }
      } catch (error) {
        console.error("Syntax highlighting failed:", error);
        if (mounted) {
          setIsLoading(false);
        }
      }
    }

    // Clear any pending highlight
    if (highlightTimeoutRef.current) {
      clearTimeout(highlightTimeoutRef.current);
      highlightTimeoutRef.current = null;
    }

    // Skip if code hasn't meaningfully changed (avoids redundant work)
    if (trimmedCode === lastHighlightedCodeRef.current) {
      return;
    }

    // Debounce: wait 100ms before highlighting to batch rapid streaming updates
    highlightTimeoutRef.current = setTimeout(() => {
      highlight();
    }, 100);

    return () => {
      mounted = false;
      if (highlightTimeoutRef.current) {
        clearTimeout(highlightTimeoutRef.current);
        highlightTimeoutRef.current = null;
      }
    };
  }, [trimmedCode, normalizedLang, isDark, isStreaming]);

  // Handle copy to clipboard
  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(trimmedCode);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (err) {
      console.error("Failed to copy code:", err);
    }
  };

  // Handle apply action
  const handleApply = () => {
    if (onApply) {
      onApply(trimmedCode);
    }
  };

  // Render lines with optional line numbers and highlighting
  const renderedContent = useMemo(() => {
    if (highlightedHtml) {
      // Parse the Shiki output and add line numbers
      // Shiki outputs: <pre class="shiki ..."><code>...tokens...</code></pre>
      // We need to extract the inner content and wrap with line numbers
      return (
        <Box
          component="div"
          sx={{
            "& pre": {
              margin: 0,
              padding: 2,
              overflow: "auto",
              maxHeight,
              whiteSpace: isWrapped ? "pre-wrap" : "pre",
              wordBreak: isWrapped ? "break-word" : "normal",
              backgroundColor: "transparent !important",
              fontFamily: "'JetBrains Mono', 'Fira Code', Consolas, Monaco, monospace",
              fontSize: "0.875rem",
              lineHeight: 1.6,
            },
            "& code": {
              fontFamily: "inherit",
              backgroundColor: "transparent !important",
            },
            // Line number styling when line numbers are shown
            ...(shouldShowLineNumbers && {
              "& .line": {
                display: "table-row",
              },
              "& .line::before": {
                content: "attr(data-line)",
                display: "table-cell",
                textAlign: "right",
                paddingRight: "1em",
                userSelect: "none",
                opacity: 0.5,
                width: "2em",
              },
            }),
          }}
          dangerouslySetInnerHTML={{ __html: sanitizeShikiHtml(highlightedHtml) }}
        />
      );
    }

    // Fallback: plain text rendering
    return (
      <Box
        component="pre"
        sx={{
          margin: 0,
          padding: 2,
          overflow: "auto",
          maxHeight,
          whiteSpace: isWrapped ? "pre-wrap" : "pre",
          wordBreak: isWrapped ? "break-word" : "normal",
          fontFamily: "'JetBrains Mono', 'Fira Code', Consolas, Monaco, monospace",
          fontSize: "0.875rem",
          lineHeight: 1.6,
          color: "text.primary",
        }}
      >
        {shouldShowLineNumbers ? (
          lines.map((line, index) => {
            const lineNum = index + 1;
            const isHighlighted = highlightLines.includes(lineNum);
            return (
              <Box
                key={index}
                component="div"
                data-line={lineNum}
                data-highlighted={isHighlighted || undefined}
                className={isHighlighted ? "highlighted" : undefined}
                sx={{
                  display: "flex",
                  ...(isHighlighted && {
                    backgroundColor: "rgba(255, 235, 59, 0.1)",
                    borderLeft: "2px solid",
                    borderLeftColor: "warning.main",
                    marginLeft: -2,
                    paddingLeft: 1.75,
                  }),
                }}
              >
                <Box
                  component="span"
                  sx={{
                    display: "inline-block",
                    width: "2em",
                    textAlign: "right",
                    marginRight: "1em",
                    userSelect: "none",
                    opacity: 0.5,
                    color: "text.secondary",
                  }}
                >
                  {lineNum}
                </Box>
                <Box component="code" sx={{ flex: 1 }}>
                  {line || " "}
                </Box>
              </Box>
            );
          })
        ) : (
          <code>{trimmedCode}</code>
        )}
      </Box>
    );
  }, [highlightedHtml, lines, shouldShowLineNumbers, highlightLines, isWrapped, maxHeight, trimmedCode]);

  return (
    <Paper
      elevation={0}
      sx={{
        my: 2,
        borderRadius: 2,
        overflow: "hidden",
        border: 1,
        borderColor: "divider",
        backgroundColor: isDark ? "grey.900" : "grey.50",
      }}
    >
      {/* Header */}
      <Box
        sx={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          px: 2,
          py: 1,
          borderBottom: 1,
          borderColor: "divider",
          backgroundColor: isDark ? "grey.800" : "grey.100",
        }}
      >
        {/* Language badge and filename */}
        <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
          <Typography
            variant="caption"
            sx={{
              fontWeight: 600,
              textTransform: "lowercase",
              color: "primary.main",
              fontFamily: "monospace",
            }}
          >
            {normalizedLang}
          </Typography>
          {filename && (
            <>
              <Typography variant="caption" color="text.disabled">
                •
              </Typography>
              <Typography variant="caption" color="text.secondary">
                {filename}
              </Typography>
            </>
          )}
        </Box>

        {/* Action buttons */}
        <Box sx={{ display: "flex", alignItems: "center", gap: 0.5 }}>
          {/* Wrap toggle */}
          {enableWrapToggle && (
            <Tooltip title={isWrapped ? "Disable wrap" : "Enable wrap"}>
              <IconButton
                size="small"
                onClick={() => setIsWrapped(!isWrapped)}
                sx={{ color: "text.secondary" }}
              >
                {isWrapped ? (
                  <FormatAlignLeftIcon fontSize="small" />
                ) : (
                  <WrapTextIcon fontSize="small" />
                )}
              </IconButton>
            </Tooltip>
          )}

          {/* Copy button */}
          <Tooltip title={copied ? "Copied!" : "Copy to clipboard"}>
            <IconButton
              size="small"
              onClick={handleCopy}
              aria-label={copied ? "Copied to clipboard" : "Copy code to clipboard"}
              sx={{
                color: copied ? "success.main" : "text.secondary",
                transition: "color 0.2s",
              }}
            >
              {copied ? (
                <CheckIcon fontSize="small" />
              ) : (
                <ContentCopyIcon fontSize="small" />
              )}
            </IconButton>
          </Tooltip>

          {/* Apply button (optional) */}
          {onApply && (
            <Tooltip title="Apply this code">
              <IconButton
                size="small"
                onClick={handleApply}
                aria-label="Apply code"
                sx={{
                  ml: 0.5,
                  color: "primary.main",
                  "&:hover": {
                    backgroundColor: "primary.main",
                    color: "primary.contrastText",
                  },
                }}
              >
                <Typography variant="caption" sx={{ fontWeight: 600, px: 0.5 }}>
                  Apply
                </Typography>
              </IconButton>
            </Tooltip>
          )}
        </Box>
      </Box>

      {/* Code content */}
      <Box
        sx={{
          position: "relative",
          backgroundColor: isDark ? "grey.900" : "grey.50",
        }}
      >
        {isLoading ? (
          // Loading skeleton
          <Box sx={{ p: 2 }}>
            <Box
              sx={{
                height: "1em",
                backgroundColor: isDark ? "grey.800" : "grey.200",
                borderRadius: 0.5,
                width: "75%",
                mb: 1,
              }}
            />
            <Box
              sx={{
                height: "1em",
                backgroundColor: isDark ? "grey.800" : "grey.200",
                borderRadius: 0.5,
                width: "50%",
              }}
            />
          </Box>
        ) : (
          renderedContent
        )}
      </Box>
    </Paper>
  );
}

export default CodeBlockWithActions;

