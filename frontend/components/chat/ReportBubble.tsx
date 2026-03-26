/**
 * ReportBubble component.
 *
 * Router component that dispatches to specialized report bubbles based on report_type.
 * Supports:
 * - "analytics": AnalyticsReportBubble (FinOps/cost analysis)
 * - "advisor": AdvisorReportBubble (performance optimization)
 * - "warehouse": WarehouseReportBubble (warehouse portfolio analysis)
 * - "cluster": WarehouseReportBubble (cluster analysis - uses same component)
 * - "compute": WarehouseReportBubble (legacy, deprecated)
 * - Legacy: Falls back to markdown rendering for backward compatibility
 */

"use client";

import React, { useMemo } from "react";
import { Box, Paper, Typography, IconButton, Tooltip, Divider } from "@mui/material";
import DownloadIcon from "@mui/icons-material/Download";
import CodeIcon from "@mui/icons-material/Code";
import { useTheme, alpha } from "@mui/material/styles";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { MessageStatus, FeedbackRating } from "@/lib/types/api";
import type { Message, NextStepOption, AnalyticsReport, AdvisorReport, WarehouseReport, DiagnosticReport } from "@/lib/types/api";
import { FeedbackWidget } from "./FeedbackWidget";
import { AnalyticsReportBubble, AdvisorReportBubble, WarehouseReportBubble, DiagnosticReportBubble } from "./reports";
import { downloadMarkdown, downloadJson } from "@/lib/utils/file-download";

interface ReportBubbleProps {
  message: Message;
  onSelectOption?: (option: NextStepOption) => void;
  onSubmitFeedback?: (messageId: string, rating: FeedbackRating) => Promise<void>;
}

/**
 * Check if report contains findings or next steps.
 * Returns true if the report has substantive recommendations/findings.
 */
function hasFindings(formattedReport: string): boolean {
  const lowerReport = formattedReport.toLowerCase();
  
  // Check for common sections that indicate findings
  const findingIndicators = [
    "## findings",
    "## recommendations",
    "## next steps",
    "## action items",
    "### finding",
    "### recommendation",
    "priority:",
    "impact:",
  ];
  
  return findingIndicators.some(indicator => lowerReport.includes(indicator));
}

/**
 * Extract next steps section from markdown report for removal.
 * Next steps should come as structured data from backend, but we still
 * remove the markdown section to avoid duplication.
 */
function removeNextStepsSection(formattedReport: string): string {
  // Remove various next steps heading formats from markdown:
  // - "## 🎯 Suggested Next Actions" (current backend format)
  // - "## Next Steps" / "## Recommended Next Steps" / "### Next Steps"
  // - "## Suggested Actions" / "## Action Items"
  // Match heading and everything after it until next ## heading or end of string
  const nextStepsPattern = /#{1,3}\s*🎯\s*Suggested\s+Next\s+Actions[\s\S]*$/i;
  
  const nextStepsMatch = formattedReport.match(nextStepsPattern);
  
  if (!nextStepsMatch) {
    return formattedReport;
  }
  
  // Remove next steps section from report
  return formattedReport.replace(nextStepsMatch[0], "").trim();
}


/**
 * Report bubble component (router).
 *
 * Routes to specialized report components based on report_type:
 * - "analytics": AnalyticsReportBubble (FinOps/cost analysis)
 * - "advisor": AdvisorReportBubble (performance optimization)
 * - Fallback: MarkdownReportBubble (generic markdown renderer)
 *
 * @param props - Component props
 * @returns Report bubble component
 *
 * @example
 * ```tsx
 * <ReportBubble message={message} onSelectOption={handleOption} />
 * ```
 */
export function ReportBubble({ message, onSubmitFeedback }: ReportBubbleProps) {
  // Memoize the report normalization to avoid creating new objects on every render
  // which causes unstable props cascading to child components
  /** Normalized report object. Typed as unknown so callers cast to the specific report type. */
  const report = useMemo((): Record<string, unknown> | null => {
    const rawReport = message.metadata?.complete_report as Record<string, unknown> | null | undefined;

    if (!rawReport) return null;

    // BUGFIX: LLM sometimes double-wraps the report under a "report" key
    // E.g., { report_type: "analytics", report: { summary: {...}, cost_summary: {...} } }
    // We need to flatten this so AnalyticsReportBubble receives the correct structure
    if (rawReport.report) {
      const nestedReport = rawReport.report;
      if (typeof nestedReport === 'object' && nestedReport !== null) {
        const nested = nestedReport as Record<string, unknown>;
        // Merge the nested report fields with the root (preserving report_type)
        return {
          ...nested,
          report_type: rawReport.report_type ?? nested.report_type,
          next_steps: rawReport.next_steps ?? nested.next_steps,
        };
      }
    }

    return rawReport;
  }, [message.metadata?.complete_report]);
  
  // Route to specialized component based on report_type
  if (report && report.report_type) {
    switch (report.report_type) {
      case "analytics":
        return (
          <AnalyticsReportBubble
            message={message}
            report={report as unknown as AnalyticsReport}
            onSubmitFeedback={onSubmitFeedback}
          />
        );

      case "advisor":
        return (
          <AdvisorReportBubble
            message={message}
            report={report as unknown as AdvisorReport}
            onSubmitFeedback={onSubmitFeedback}
          />
        );

      case "diagnostic":
        return (
          <DiagnosticReportBubble
            message={message}
            report={report as unknown as DiagnosticReport}
            onSubmitFeedback={onSubmitFeedback}
          />
        );

      case "discovery":
        return (
          <AdvisorReportBubble
            message={message}
            report={report as unknown as AdvisorReport}
            onSubmitFeedback={onSubmitFeedback}
          />
        );

      case "warehouse":
      case "cluster":
      case "compute": // Legacy - deprecated
        return (
          <WarehouseReportBubble
            message={message}
            report={report as unknown as WarehouseReport}
            onSubmitFeedback={onSubmitFeedback}
          />
        );
      
      default:
        // Unknown report type - fall back to markdown rendering
        return (
          <MarkdownReportBubble
            message={message}
            onSubmitFeedback={onSubmitFeedback}
          />
        );
    }
  }
  
  // No structured report - fall back to markdown rendering
  return (
    <MarkdownReportBubble
      message={message}
      onSubmitFeedback={onSubmitFeedback}
    />
  );
}

/**
 * Markdown report bubble component.
 *
 * Generic markdown renderer for reports without specialized components.
 * Used as fallback when report_type is unknown or missing.
 * 
 * Note: This generates markdown on-the-fly from complete_report.
 */
function MarkdownReportBubble({ message, onSubmitFeedback }: Omit<ReportBubbleProps, 'onSelectOption'>) {
  const theme = useTheme();
  
  // Generate markdown from complete_report on-the-fly
  const formattedMarkdown = useMemo(() => {
    if (!message.metadata?.complete_report) return "";
    
    try {
      // Use formatter to generate markdown
      // TODO(BACKLOG-005): Import formatter function when available in frontend
      // For now, return empty string - this fallback should rarely be used
      return "";
    } catch (error) {
      console.error("Failed to generate markdown from complete_report:", error);
      return "";
    }
  }, [message.metadata?.complete_report]);
  
  const reportWithoutNextSteps = useMemo(
    () => removeNextStepsSection(formattedMarkdown || ""),
    [formattedMarkdown]
  );
  
  // Early returns AFTER all hooks
  // Only render if we have a complete_report
  if (!message.metadata?.complete_report) {
    return null;
  }
  
  // Check if report has findings - if not, don't render separately
  if (!hasFindings(formattedMarkdown)) {
    return null;
  }

  const handleDownloadMarkdown = () => {
    // Generate markdown from complete_report on-the-fly
    // For MarkdownReportBubble fallback, this is a best-effort attempt
    if (formattedMarkdown) {
      const timestamp = message.timestamp 
        ? new Date(message.timestamp).toISOString().split("T")[0]
        : new Date().toISOString().split("T")[0];
      downloadMarkdown(formattedMarkdown, `analyst-report-${timestamp}.md`);
    }
  };

  const handleDownloadJSON = () => {
    if (message.metadata?.complete_report) {
      const timestamp = message.timestamp 
        ? new Date(message.timestamp).toISOString().split("T")[0]
        : new Date().toISOString().split("T")[0];
      downloadJson(message.metadata.complete_report, `analyst-report-${timestamp}.json`);
    }
  };

  return (
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
          maxWidth: "85%",
          flexDirection: "row",
        }}
      >
        {/* Report content */}
        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Paper
            elevation={2}
            sx={{
              p: 2,
              bgcolor: theme.palette.mode === "dark"
                ? alpha(theme.palette.primary.main, 0.08)
                : alpha(theme.palette.primary.main, 0.04),
              borderRadius: 2,
              borderLeft: `4px solid ${theme.palette.primary.main}`,
            }}
          >
            {/* Header with controls */}
            <Box
              sx={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                mb: 1.5,
              }}
            >
              <Typography
                variant="h6"
                sx={{
                  fontWeight: 600,
                  color: "primary.main",
                  fontSize: "1.1rem",
                }}
              >
                📊 Analysis Report
              </Typography>
              
              <Box sx={{ display: "flex", gap: 0.5 }}>
                <Tooltip title="Download as Markdown">
                  <IconButton
                    size="small"
                    aria-label="Download as Markdown"
                    onClick={handleDownloadMarkdown}
                    sx={{
                      "&:hover": {
                        bgcolor: "action.hover",
                      },
                    }}
                  >
                    <DownloadIcon fontSize="small" />
                  </IconButton>
                </Tooltip>

                {!!message.metadata?.complete_report && (
                  <Tooltip title="Download as JSON">
                    <IconButton
                      size="small"
                      aria-label="Download as JSON"
                      onClick={handleDownloadJSON}
                      sx={{
                        "&:hover": {
                          bgcolor: "action.hover",
                        },
                      }}
                    >
                      <CodeIcon fontSize="small" />
                    </IconButton>
                  </Tooltip>
                )}
              </Box>
            </Box>

            <Divider sx={{ mb: 2 }} />

            {/* Report content with markdown */}
            <Box
              sx={{
                "& h1": {
                  fontSize: "1.5rem",
                  fontWeight: 700,
                  marginTop: 2,
                  marginBottom: 1.5,
                  color: "text.primary",
                  "&:first-of-type": { marginTop: 0 },
                },
                "& h2": {
                  fontSize: "1.25rem",
                  fontWeight: 600,
                  marginTop: 2,
                  marginBottom: 1,
                  color: "text.primary",
                  "&:first-of-type": { marginTop: 0 },
                },
                "& h3": {
                  fontSize: "1.1rem",
                  fontWeight: 600,
                  marginTop: 1.5,
                  marginBottom: 0.75,
                  color: "text.primary",
                },
                "& p": {
                  margin: 0,
                  marginBottom: 1,
                  lineHeight: 1.6,
                  "&:last-child": { marginBottom: 0 },
                },
                "& ul, & ol": {
                  margin: 0,
                  marginBottom: 1,
                  paddingLeft: 3,
                  "& li": {
                    marginBottom: 0.5,
                  },
                },
                "& strong": {
                  fontWeight: 600,
                  color: theme.palette.mode === "dark" ? "primary.light" : "primary.dark",
                },
                "& code": {
                  bgcolor: theme.palette.mode === "dark"
                    ? alpha(theme.palette.common.white, 0.1)
                    : alpha(theme.palette.common.black, 0.05),
                  padding: "2px 6px",
                  borderRadius: 1,
                  fontSize: "0.9em",
                  fontFamily: "monospace",
                },
                "& pre": {
                  bgcolor: theme.palette.mode === "dark"
                    ? alpha(theme.palette.common.black, 0.3)
                    : alpha(theme.palette.common.black, 0.05),
                  padding: 2,
                  borderRadius: 1,
                  overflow: "auto",
                  marginBottom: 1,
                  "& code": {
                    bgcolor: "transparent",
                    padding: 0,
                  },
                },
                "& hr": {
                  border: "none",
                  borderTop: `1px solid ${theme.palette.divider}`,
                  margin: "16px 0",
                },
              }}
            >
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {reportWithoutNextSteps}
              </ReactMarkdown>
            </Box>

            {/* Footer with metadata */}
            {message.metadata && (
              <>
                <Divider sx={{ my: 2 }} />
                <Box
                  sx={{
                    display: "flex",
                    gap: 2,
                    flexWrap: "wrap",
                    fontSize: "0.85rem",
                    color: "text.secondary",
                  }}
                >
                  {typeof message.metadata.tokens_used === 'number' && (
                    <Typography variant="caption">
                      <strong>Tokens:</strong> {message.metadata.tokens_used.toLocaleString()}
                    </Typography>
                  )}
                  {typeof message.metadata.cost_usd === 'number' && (
                    <Typography variant="caption">
                      <strong>Cost:</strong> ${message.metadata.cost_usd.toFixed(4)}
                    </Typography>
                  )}
                  {typeof message.metadata.duration_seconds === 'number' && (
                    <Typography variant="caption">
                      <strong>Duration:</strong> {message.metadata.duration_seconds.toFixed(1)}s
                    </Typography>
                  )}
                  {typeof message.metadata.steps_taken === 'number' && (
                    <Typography variant="caption">
                      <strong>Steps:</strong> {message.metadata.steps_taken}
                    </Typography>
                  )}
                </Box>
              </>
            )}
          </Paper>
          
          {/* Timestamp */}
          {message.timestamp && (
            <Box sx={{ display: "flex", mt: 0.5, px: 1 }}>
              <Typography variant="caption" color="text.secondary">
                {new Date(message.timestamp).toLocaleTimeString([], {
                  hour: "2-digit",
                  minute: "2-digit",
                })}
              </Typography>
            </Box>
          )}

          {/* Next Steps are now rendered separately by MessageList (Phase 2) */}

          {/* Feedback Widget - Positioned after analysis report */}
          {/* Hide feedback when there are next_steps (agent is waiting for user input) */}
          {message.status === MessageStatus.COMPLETED && 
           onSubmitFeedback && 
           !message.next_steps?.length && (
            <Box 
              sx={{ 
                display: "flex", 
                justifyContent: "flex-end",
                mt: 1,
                px: 1,
              }}
            >
              <FeedbackWidget
                messageId={message.message_id || ""}
                conversationId={message.conversation_id || ""}
                onSubmitFeedback={onSubmitFeedback}
                disabled={false}
              />
            </Box>
          )}
        </Box>
      </Box>
    </Box>
  );
}

