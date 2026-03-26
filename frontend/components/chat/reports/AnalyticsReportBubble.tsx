/**
 * Analytics report bubble component.
 *
 * Specialized UI for FinOps/cost analysis reports with cost summary,
 * optimization findings, and chart visualizations.
 */

"use client";

import React, { useMemo, useCallback } from "react";
import { Box, Paper, Typography } from "@mui/material";
import { useTheme } from "@mui/material/styles";
import type {
  Message,
  AnalyticsReport,
  NextStepOption,
  FeedbackRating,
} from "@/lib/types/api";
import { MessageStatus } from "@/lib/types/api";
import { ReportHeader, ReportFooter, BudgetExhaustedAlert } from "../shared";
import { AnalyticsCostSummary, AnalyticsFindingsCard } from "../analytics";
import { FeedbackWidget } from "../FeedbackWidget";
import { downloadMarkdown, downloadJson } from "@/lib/utils/file-download";
import { LazyVisualizationPanel } from "@/components/chat/lazy";
import type { ChartConfig } from "@/lib/types/chart";

/**
 * Extended visualization type that includes chart rendering fields.
 * The backend may send these fields in addition to the VisualizationRecommendation base fields.
 */
interface ExtendedVisualization {
  // Base VisualizationRecommendation fields
  recommended_chart?: string;
  primary_metric?: string;
  primary_dimension?: string;
  notes?: string;
  // Extended fields for chart rendering
  data_reference?: string;
  chart_config?: ChartConfig;
  has_visualization?: boolean;
}

interface AnalyticsReportBubbleProps {
  /** Message containing the analytics report */
  message: Message;
  /** Analytics report data */
  report: AnalyticsReport;
  /** Next step selection handler */
  onSelectOption?: (option: NextStepOption) => void;
  /** Feedback submission handler */
  onSubmitFeedback?: (messageId: string, rating: FeedbackRating) => Promise<void>;
}


/**
 * Analytics report bubble component.
 *
 * Renders cost analysis reports with specialized UI:
 * - Cost overview with trend indicators
 * - Optimization findings ranked by savings
 * - Chart visualization (renders VisualizationPanel when data_reference available)
 * - Structured next steps
 *
 * @param props - Component props
 * @returns Analytics report bubble component
 *
 * @example
 * ```tsx
 * <AnalyticsReportBubble
 *   message={message}
 *   report={analyticsReport}
 *   onSelectOption={handleNextStep}
 *   onSubmitFeedback={handleFeedback}
 * />
 * ```
 */
export function AnalyticsReportBubble({
  message,
  report,
  onSubmitFeedback,
}: Omit<AnalyticsReportBubbleProps, 'onSelectOption'>) {
  const theme = useTheme();

  // Get stable timestamp once for use in downloads
  const reportTimestamp = useMemo(() => {
    return message.timestamp 
      ? new Date(message.timestamp).toISOString().split("T")[0]
      : new Date().toISOString().split("T")[0];
  }, [message.timestamp]);

  // Memoize download handlers to prevent child re-renders
  const handleDownloadMarkdown = useCallback(() => {
    // Generate markdown from complete_report using backend formatter
    // TODO(BACKLOG-008): Call backend formatter or implement client-side formatter
    // For now, download JSON representation as markdown placeholder
    if (message.metadata?.complete_report) {
      const timestamp = reportTimestamp;
      // Generate basic markdown from report structure
      const markdown = `# Analytics Report\n\n${report.summary.overview}\n\n## Cost Summary\n\nTotal: $${report.cost_summary.total}`;
      downloadMarkdown(markdown, `analytics-report-${timestamp}.md`);
    }
  }, [message.metadata?.complete_report, reportTimestamp, report.summary.overview, report.cost_summary.total]);

  const handleDownloadJSON = useCallback(() => {
    if (message.metadata?.complete_report) {
      downloadJson(message.metadata.complete_report, `analytics-report-${reportTimestamp}.json`);
    }
  }, [message.metadata, reportTimestamp]);

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
        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Paper
            elevation={2}
            sx={{
              p: 2,
              bgcolor:
                theme.palette.mode === "dark"
                  ? "rgba(33, 150, 243, 0.08)"
                  : "rgba(33, 150, 243, 0.04)",
              borderRadius: 2,
              borderLeft: `4px solid ${theme.palette.primary.main}`,
            }}
          >
            {/* Header with download/share/re-run (Phase 2) */}
            <ReportHeader
              title="Cost Analysis Report"
              icon="💰"
              onDownloadMarkdown={handleDownloadMarkdown}
              onDownloadJSON={handleDownloadJSON}
              hasCompleteReport={!!message.metadata?.complete_report}
              conversationId={message.conversation_id}
            />

            {/* Budget exhaustion warning */}
            {(report as AnalyticsReport & { budget_exhausted?: boolean }).budget_exhausted && <BudgetExhaustedAlert />}

            {/* Summary Section */}
            {report.summary && (
              <Box sx={{ mb: 2 }}>
                <Typography variant="body1" sx={{ lineHeight: 1.6 }}>
                  {report.summary.overview}
                </Typography>
              </Box>
            )}

            {/* Cost Summary */}
            {report.cost_summary && (
              <AnalyticsCostSummary costSummary={report.cost_summary} />
            )}

            {/* Findings */}
            {report.findings && report.findings.length > 0 && (
              <AnalyticsFindingsCard findings={report.findings} />
            )}

            {/* Visualization Section - only render if has_visualization is true */}
            {report.visualization && (() => {
              // Cast to extended type that includes chart rendering fields
              const viz = report.visualization as unknown as ExtendedVisualization;
              
              // Only show visualization section if has_visualization is true and we have data
              if (!viz.has_visualization || !viz.data_reference) {
                return null;
              }
              
              return (
                <Box sx={{ mt: 2 }}>
                  <LazyVisualizationPanel
                    dataReference={viz.data_reference}
                    chartConfig={viz.chart_config || null}
                  />
                </Box>
              );
            })()}

            {/* Footer with metadata */}
            <ReportFooter metadata={message.metadata} />
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

          {/* Feedback Widget */}
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
                  messageId={message.message_id || message.id}
                  conversationId={message.conversation_id}
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

