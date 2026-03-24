/**
 * AssistantMessage component.
 * Renders assistant messages with thinking text and inline tool calls.
 * 
 * Tool calls are rendered as plain text `→ Tool Name` that is selectable
 * and behaves like regular content.
 * 
 * ThinkingStepsContainer is rendered separately after message completion.
 */

"use client";

import React, { useMemo } from "react";
import { Box, Paper, Typography, Slide } from "@mui/material";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import sbd from "sbd";
import { FeedbackRating } from "@/lib/types/api";
import type { Message, AgentType, ToolPosition, ToolCall } from "@/lib/types/api";
import {
  MessageAvatar,
  MessageFooter,
  MarkdownCodeRenderer,
  TypingIndicatorInline,
} from "../message-parts";
import { ThinkingIndicator } from "../ThinkingIndicator";
import { useMessageStore, type ThinkingIndicatorState } from "@/lib/store/messageStore";
import { ReasoningTimeline } from "../ReasoningTimeline";

/** Stable default for thinking indicator to avoid infinite re-renders in Zustand selectors */

/** Stable reference for ReactMarkdown components to prevent re-renders */
const MARKDOWN_COMPONENTS = { code: MarkdownCodeRenderer };
const DEFAULT_THINKING_STATE: ThinkingIndicatorState = { state: "idle" };

export interface AssistantMessageProps {
  message: Message;
  onRetry?: (messageId: string) => void;
  onSubmitFeedback?: (messageId: string, rating: FeedbackRating) => Promise<void>;
}

/**
 * Check if a tool should be hidden from the UI.
 * Internal tools like 'complete', 'request_user_input', etc. are hidden.
 */
function shouldHideTool(toolName: string, debugMode: boolean = false): boolean {
  const hiddenTools = new Set([
    "complete",
    "request_user_input",
  ]);

  if (debugMode) {
    return false; // Show everything in debug mode
  }

  return hiddenTools.has(toolName);
}

/**
 * Format tool name for display.
 * Converts snake_case to Title Case.
 */
function formatToolName(name: string): string {
  return name
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

/**
 * Build content with inline tool calls as plain text.
 * 
 * Tool calls are inserted at their position as simple text: `→ Tool Name`
 * This makes them selectable and behave like regular content.
 */
/**
 * Sentence boundary detection options for sbd library.
 * Configured to handle common abbreviations and preserve newlines as boundaries.
 */
const SBD_OPTIONS: import("sbd").Options = {
  newline_boundaries: true,  // Treat newlines as sentence boundaries
  html_boundaries: false,    // Don't split on HTML tags
  sanitize: false,           // Don't remove HTML tags
  allowed_tags: false,       // No tag whitelist
  preserve_whitespace: true, // Keep original spacing
};

/**
 * Snap a position to the nearest sentence boundary using sbd library.
 * 
 * Uses proper NLP-based sentence boundary detection that handles:
 * - Common abbreviations (e.g., i.e., Mr., Dr., etc.)
 * - Decimal numbers (2.5, 3.14)
 * - URLs and email addresses
 * - Ellipses (...)
 * 
 * This prevents tools from being inserted mid-sentence like:
 *   "for performance anti-patterns (e. → Tool → g., per-table schema reads)"
 * 
 * Instead, we get:
 *   "for performance anti-patterns (e.g., per-table schema reads)."
 *   → Tool
 * 
 * @param content - The full content string
 * @param position - Raw position to snap
 * @returns Position snapped to sentence boundary
 */
function snapToSentenceBoundary(content: string, position: number): number {
  // Clamp to valid range
  const pos = Math.min(Math.max(0, position), content.length);
  
  // If at start or end, use as-is
  if (pos === 0 || pos === content.length) return pos;
  
  // Use sbd to split content into sentences
  const sentences = sbd.sentences(content, SBD_OPTIONS);
  
  if (sentences.length === 0) {
    // No sentences found - return original position
    return pos;
  }
  
  // Find sentence boundaries by tracking cumulative positions
  let currentPos = 0;
  for (const sentence of sentences) {
    // Find where this sentence actually starts in the content
    // (accounting for whitespace between sentences)
    const sentenceStart = content.indexOf(sentence, currentPos);
    if (sentenceStart === -1) {
      // Sentence not found - continue with estimate
      currentPos += sentence.length;
      continue;
    }
    
    const sentenceEnd = sentenceStart + sentence.length;
    
    // If tool position is within this sentence, return end of sentence
    if (pos >= sentenceStart && pos < sentenceEnd) {
      // Skip trailing whitespace after sentence
      let endPos = sentenceEnd;
      while (endPos < content.length && content[endPos] === ' ') {
        endPos++;
      }
      return endPos;
    }
    
    // If tool position is before this sentence starts (in whitespace between sentences)
    if (pos < sentenceStart) {
      // Use the previous sentence boundary (current position)
      return currentPos > 0 ? currentPos : pos;
    }
    
    currentPos = sentenceEnd;
  }
  
  // Position is after all sentences - return end of content
  return content.length;
}

function buildContentWithInlineTools(
  content: string,
  toolCalls?: ToolCall[],
  toolPositions?: ToolPosition[],
  debugMode?: boolean
): string {
  if (!content) return "";
  
  // No tool positions - return content as-is
  if (!toolPositions || toolPositions.length === 0) {
    return content;
  }
  
  // No tool calls - return content as-is
  if (!toolCalls || toolCalls.length === 0) {
    return content;
  }

  // Build a map of tool calls by ID
  const toolCallMap = new Map<string, ToolCall>();
  for (const tc of toolCalls) {
    if (tc.tool_call_id) {
      toolCallMap.set(tc.tool_call_id, tc);
    }
  }

  // Filter to inline positions and sort by position (ascending for forward pass)
  const inlinePositions = toolPositions
    .filter((p) => p.display === "inline")
    .sort((a, b) => a.position - b.position);

  // Build output by interleaving text segments with tool indicators
  let result = "";
  let lastPos = 0;
  const seenToolIds = new Set<string>();
  
  for (const pos of inlinePositions) {
    // Skip duplicates
    if (seenToolIds.has(pos.tool_call_id)) continue;
    seenToolIds.add(pos.tool_call_id);
    
    const toolCall = toolCallMap.get(pos.tool_call_id);
    if (!toolCall) continue;
    
    // Skip hidden tools
    if (shouldHideTool(toolCall.tool_name, debugMode)) continue;
    
    // Get display name
    const displayName = toolCall.friendly_name || formatToolName(toolCall.tool_name);
    
    // Snap position to sentence boundary to avoid mid-sentence tool insertion
    const insertPos = snapToSentenceBoundary(content, pos.position);
    
    if (insertPos > lastPos) {
      let textBefore = content.slice(lastPos, insertPos);
      // Trim whitespace from text segment
      textBefore = textBefore.trim();
      if (textBefore) {
        // Ensure newline before text if we just added a tool indicator
        if (result.length > 0 && !result.endsWith('\n')) {
          result += '\n';
        }
        result += textBefore;
      }
    }
    
    // Add the tool indicator on its own line
    // Ensure newline before tool indicator
    if (result.length > 0 && !result.endsWith('\n')) {
      result += '\n';
    }
    result += `→ ${displayName}`;
    
    lastPos = insertPos;
  }
  
  // Add remaining content
  if (lastPos < content.length) {
    let remaining = content.slice(lastPos);
    // Trim leading whitespace from remaining content  
    remaining = remaining.replace(/^\s+/, '');
    if (remaining) {
      // Add newline separator between tool and following text
      if (result.length > 0 && !result.endsWith('\n')) {
        result += '\n';
      }
      result += remaining;
    }
  }

  // Clean up: normalize multiple newlines, but keep single newlines
  result = result
    .replace(/\n{3,}/g, '\n\n')
    .replace(/^\n+/, '')
    .trim();

  return result;
}

/** Markdown styles for report sections */
const markdownStyles = {
  "& h1": {
    fontSize: "1.5rem",
    fontWeight: 700,
    marginTop: 2,
    marginBottom: 1.5,
    "&:first-of-type": { marginTop: 0 },
  },
  "& h2": {
    fontSize: "1.25rem",
    fontWeight: 600,
    marginTop: 2,
    marginBottom: 1,
    "&:first-of-type": { marginTop: 0 },
  },
  "& h3": {
    fontSize: "1.1rem",
    fontWeight: 600,
    marginTop: 1.5,
    marginBottom: 0.75,
  },
  "& p": {
    margin: 0,
    marginBottom: 1,
    "&:last-child": { marginBottom: 0 },
  },
  "& ul, & ol": {
    margin: 0,
    marginBottom: 1,
    paddingLeft: 3,
  },
  "& strong": {
    fontWeight: 600,
  },
};

export function AssistantMessage({
  message,
  onRetry,
  onSubmitFeedback,
}: AssistantMessageProps) {
  // Get thinking indicator state from store (ephemeral, not persisted)
  const thinkingIndicator = useMessageStore(
    (state) => state.thinkingByMessage[message.message_id ?? ""] ?? DEFAULT_THINKING_STATE
  );
  
  // Check if this message is currently streaming - skip expensive rendering during streaming
  const isMessageStreaming = useMessageStore(
    (state) => state.streamingMessageId === message.message_id
  );

  // Memoize whether report will be rendered separately
  const willRenderReportSeparately = useMemo(() => {
    return (
      message.metadata?.complete_report !== undefined &&
      message.metadata?.complete_report !== null
    );
  }, [message.metadata?.complete_report]);

  // Build content with inline tools as plain text
  const contentWithTools = useMemo(() => {
    return buildContentWithInlineTools(
      message.content,
      message.tool_calls,
      message.tool_positions,
      message.debug
    );
  }, [message.content, message.tool_calls, message.tool_positions, message.debug]);

  // Memoize content parts split (for markdown rendering)
  const contentParts = useMemo(() => {
    return contentWithTools.split(/\n---\n/);
  }, [contentWithTools]);

  // Render content with tool indicators styled
  const renderStyledContent = (text: string) => {
    // Split by lines and style tool indicators differently
    const lines = text.split('\n');
    return lines.map((line, idx) => {
      const isToolIndicator = line.trim().startsWith('→');
      const isLastLine = idx === lines.length - 1;
      
      if (isToolIndicator) {
        return (
          <React.Fragment key={idx}>
            <Box
              component="span"
              sx={{
                display: "block",
                color: "text.secondary",
                fontStyle: "italic",
                fontSize: "0.9em",
                opacity: 0.65,
              }}
            >
              {line}
            </Box>
          </React.Fragment>
        );
      }
      
      return (
        <React.Fragment key={idx}>
          {line}
          {!isLastLine && '\n'}
        </React.Fragment>
      );
    });
  };

  // Render thinking text content
  const renderThinkingContent = () => (
    <Typography
      variant="body1"
      component="div"
      sx={{
        whiteSpace: "pre-wrap",
        wordBreak: "break-word",
        color: "text.primary",
      }}
    >
      {renderStyledContent(contentWithTools)}
    </Typography>
  );

  // Render message content based on structure
  const renderContent = () => {
    if (willRenderReportSeparately) {
      // Report is rendered separately in ReportBubble
      return renderThinkingContent();
    }

    const parts = contentParts;

    // During streaming, skip ReactMarkdown rendering to prevent infinite loops
    // from Shiki syntax highlighting. Show plain text until message completes.
    if (parts.length > 1 && !isMessageStreaming) {
      // Has both thinking and report sections - render with markdown (only when not streaming)
      return (
        <>
          {/* Thinking section */}
          <Typography
            variant="body1"
            component="div"
            sx={{
              whiteSpace: "pre-wrap",
              wordBreak: "break-word",
              color: "text.primary",
            }}
          >
            {renderStyledContent(parts[0])}
          </Typography>

          {/* Separator */}
          <Box sx={{ borderTop: 1, borderColor: "divider", my: 2 }} />

          {/* Report section with markdown */}
          <Box sx={markdownStyles}>
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={MARKDOWN_COMPONENTS}
            >
              {parts.slice(1).join("\n---\n")}
            </ReactMarkdown>
          </Box>
        </>
      );
    }

    // Only thinking section (no report yet)
    const hasVisibleContent =
      contentWithTools &&
      contentWithTools.replace(/→[^\n]*/g, "").trim().length > 0;

    return (
      <Typography
        variant="body1"
        component="div"
        sx={{
          whiteSpace: "pre-wrap",
          wordBreak: "break-word",
          color: "text.primary",
        }}
      >
        {renderStyledContent(contentWithTools)}

        {/* Show helpful note if message completed without visible content */}
        {!hasVisibleContent && message.status === "completed" && (
          <Typography
            variant="body2"
            sx={{
              fontStyle: "italic",
              color: "text.secondary",
              mt:
                message.tool_calls && message.tool_calls.length > 0 ? 1 : 0,
            }}
          >
            The analysis completed successfully. Use the conversation history
            or tool results above for details.
          </Typography>
        )}
      </Typography>
    );
  };

  return (
    <Slide direction="right" in={true} timeout={300} mountOnEnter unmountOnExit>
      <Box
        sx={{
          display: "flex",
          justifyContent: "flex-start",
          mb: 2,
          px: 2,
        }}
      >
        <Box
          sx={{
            display: "flex",
            gap: 1,
            maxWidth: "70%",
            flexDirection: "row",
          }}
        >
          {/* Assistant Avatar with agent badge */}
          <MessageAvatar
            isUser={false}
            agentType={message.agent_type as AgentType}
          />

          {/* Message content */}
          <Box sx={{ flex: 1, minWidth: 0 }}>
            <Paper
              elevation={1}
              sx={{
                p: 1.5,
                bgcolor: "background.paper",
                borderRadius: 2,
                borderTopLeftRadius: 0,
                borderTopRightRadius: 2,
              }}
            >
              <Box>
                {/* Main content: thinking text with inline tool indicators */}
                {renderContent()}

                {/* Inline thinking indicator when processing */}
                {message.status === "processing" && thinkingIndicator.state !== "idle" && (
                  <ThinkingIndicator
                    state={thinkingIndicator.state}
                    durationSeconds={thinkingIndicator.durationSeconds}
                    startTime={thinkingIndicator.startTime}
                    stepTitle={thinkingIndicator.stepTitle}
                  />
                )}

                {/* Fallback typing indicator when no thinking state yet */}
                {message.status === "processing" && thinkingIndicator.state === "idle" && (
                  <TypingIndicatorInline />
                )}

                {/* User Input Request - at the very bottom of message content */}
                {message.metadata?.user_input_request && (() => {
                  const inputRequest = message.metadata.user_input_request as {
                    question?: string;
                    response?: string | null;
                  };
                  // Active = waiting for input (no response yet and message is not completed with next steps)
                  const isActive = !inputRequest.response && !message.next_steps?.length;
                  
                  return isActive ? (
                    // Active state: emphasized prompt at bottom
                    <Box
                      sx={{
                        mt: 2,
                        p: 2,
                        bgcolor: (theme) =>
                          theme.palette.mode === "dark"
                            ? "rgba(255, 152, 0, 0.15)"
                            : "rgba(255, 152, 0, 0.08)",
                        borderRadius: 2,
                        borderLeft: "4px solid",
                        borderColor: "warning.main",
                      }}
                    >
                      <Typography
                        variant="subtitle2"
                        sx={{
                          fontWeight: 600,
                          color: "warning.dark",
                          mb: 1,
                          display: "flex",
                          alignItems: "center",
                          gap: 1,
                        }}
                      >
                        💬 Your input needed:
                      </Typography>
                      <Typography variant="body2" sx={{ color: "text.primary" }}>
                        {inputRequest.question}
                      </Typography>
                      <Typography
                        variant="caption"
                        sx={{ mt: 1, display: "block", color: "text.secondary" }}
                      >
                        Type your response in the message box below.
                      </Typography>
                    </Box>
                  ) : (
                    // Inactive state: de-emphasized, looks like normal thinking text
                    <Typography
                      variant="body2"
                      sx={{
                        mt: 1,
                        color: "text.secondary",
                        fontStyle: "italic",
                      }}
                    >
                      Asked: {inputRequest.question}
                    </Typography>
                  );
                })()}
              </Box>
            </Paper>

            {/* Reasoning timeline for completed messages */}
            {message.status === "completed" && message.tool_calls && message.tool_calls.length > 0 && (
              <ReasoningTimeline toolCalls={message.tool_calls} />
            )}

            {/* Footer with timestamp, status, and feedback */}
            <MessageFooter
              timestamp={message.timestamp}
              status={message.status}
              messageId={message.message_id}
              conversationId={message.conversation_id}
              retryCount={message.retry_count}
              isAssistant={true}
              hasReport={!!message.metadata?.complete_report}
              hasNextSteps={!!message.next_steps?.length}
              onRetry={onRetry}
              onSubmitFeedback={onSubmitFeedback}
            />
          </Box>
        </Box>
      </Box>
    </Slide>
  );
}
