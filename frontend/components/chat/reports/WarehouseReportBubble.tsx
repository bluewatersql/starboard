/**
 * Warehouse report bubble component.
 *
 * Specialized UI for SQL Warehouse agent reports with:
 * - Portfolio overview with health distribution
 * - Individual resource health gauges
 * - Topology analysis with consolidation opportunities
 * - User activity for chargeback reporting
 */

"use client";

import React, { useMemo, useCallback } from "react";
import { Box, Paper, Typography, Divider } from "@mui/material";
import { useTheme } from "@mui/material/styles";
import type {
  Message,
  WarehouseReport,
  FeedbackRating,
} from "@/lib/types/api";
import { MessageStatus } from "@/lib/types/api";
import { ReportHeader, ReportFooter, BudgetExhaustedAlert } from "../shared";
import { FeedbackWidget } from "../FeedbackWidget";
import { downloadMarkdown, downloadJson } from "@/lib/utils/file-download";
import { exportWarehouseReportToMarkdown, prepareReportForJsonExport } from "@/lib/utils/report-export";
import {
  PortfolioOverview,
  HealthGauge,
  TopologyCard,
  UserActivityTable,
  WarehouseTable,
  DataTableView,
} from "./warehouse";

interface WarehouseReportBubbleProps {
  /** Message containing the warehouse report */
  message: Message;
  /** Warehouse report data */
  report: WarehouseReport;
  /** Feedback submission handler */
  onSubmitFeedback?: (messageId: string, rating: FeedbackRating) => Promise<void>;
}

/**
 * Warehouse report bubble component.
 *
 * Renders warehouse analysis reports with specialized UI:
 * - Portfolio overview with health distribution bar
 * - Health gauge with metric breakdown
 * - Topology analysis with consolidation opportunities
 * - User activity table for chargeback
 *
 * @param props - Component props
 * @returns Warehouse report bubble component
 *
 * @example
 * ```tsx
 * <WarehouseReportBubble
 *   message={message}
 *   report={warehouseReport}
 *   onSubmitFeedback={handleFeedback}
 * />
 * ```
 */
export function WarehouseReportBubble({
  message,
  report,
  onSubmitFeedback,
}: WarehouseReportBubbleProps) {
  const theme = useTheme();

  // Get stable timestamp for downloads
  const reportTimestamp = useMemo(() => {
    return message.timestamp
      ? new Date(message.timestamp).toISOString().split("T")[0]
      : new Date().toISOString().split("T")[0];
  }, [message.timestamp]);

  // Download handlers - BB-04: Generate comprehensive, visually stunning exports
  const handleDownloadMarkdown = useCallback(() => {
    // Use comprehensive markdown export utility
    const markdown = exportWarehouseReportToMarkdown({
      report: report as unknown as Record<string, unknown>,
      timestamp: message.timestamp,
    });
    downloadMarkdown(markdown, `warehouse-report-${reportTimestamp}.md`);
  }, [report, message.timestamp, reportTimestamp]);

  const handleDownloadJson = useCallback(() => {
    // Export complete report with metadata
    const exportData = prepareReportForJsonExport(report, {
      timestamp: message.timestamp,
      domain: "warehouse",
      conversationId: message.conversation_id,
    });
    downloadJson(exportData, `warehouse-report-${reportTimestamp}.json`);
  }, [report, message.timestamp, message.conversation_id, reportTimestamp]);

  // Determine which sections to show (agent decides what to include)
  const hasPortfolio = !!report.portfolio_summary;
  const hasHealth = !!report.health_metrics;
  const hasTopology = !!(
    report.topology_analysis?.clusters?.length ||
    report.topology_analysis?.consolidation_opportunities?.length
  );
  const hasUserActivity = !!(report.user_activity?.top_users?.length);
  // Agent includes warehouses when user requests a data listing
  const hasWarehouses = !!(report.warehouses && report.warehouses.length > 0);
  // Agent includes data_table for report requests (chargeback, breakdowns, etc.)
  const hasDataTable = !!(report.data_table?.rows?.length);

  return (
    <Paper
      variant="outlined"
      sx={{
        p: 2,
        maxWidth: "100%",
        bgcolor: theme.palette.mode === "dark"
          ? "rgba(255, 255, 255, 0.02)"
          : "rgba(0, 0, 0, 0.02)",
        borderRadius: 2,
      }}
    >
      {/* Header */}
      <ReportHeader
        title="Warehouse Analysis"
        icon="🏢"
        onDownloadMarkdown={handleDownloadMarkdown}
        onDownloadJSON={handleDownloadJson}
        hasCompleteReport={true}
      />

      {/* Budget exhaustion warning */}
      {(report as WarehouseReport & { budget_exhausted?: boolean }).budget_exhausted && <BudgetExhaustedAlert />}

      {/* Summary */}
      {report.summary?.overview && (
        <Box sx={{ mb: 2 }}>
          <Typography variant="body1">
            {report.summary.overview}
          </Typography>
          {report.summary.current_state?.key_symptoms && 
           report.summary.current_state.key_symptoms.length > 0 && (
            <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
              Key observations: {report.summary.current_state.key_symptoms.join(", ")}
            </Typography>
          )}
        </Box>
      )}

      <Divider sx={{ my: 2 }} />

      {/* Portfolio Overview */}
      {hasPortfolio && (
        <PortfolioOverview portfolio={report.portfolio_summary!} />
      )}

      {/* Warehouse Table - Agent includes when user requests data listing */}
      {hasWarehouses && (
        <WarehouseTable warehouses={report.warehouses!} />
      )}

      {/* Health Gauge */}
      {hasHealth && (
        <HealthGauge health={report.health_metrics!} />
      )}

      {/* Topology Analysis */}
      {hasTopology && (
        <TopologyCard topology={report.topology_analysis!} />
      )}

      {/* User Activity */}
      {hasUserActivity && (
        <UserActivityTable activity={report.user_activity!} />
      )}

      {/* Data Table - Agent includes for report requests (chargeback, breakdown, etc.) */}
      {hasDataTable && (
        <DataTableView table={report.data_table!} />
      )}

      {/* Empty state */}
      {!hasPortfolio && !hasHealth && !hasTopology && !hasUserActivity && !hasWarehouses && !hasDataTable && (
        <Typography variant="body2" color="text.secondary" sx={{ py: 2 }}>
          No detailed analysis sections available. See summary above.
        </Typography>
      )}

      {/* NOTE: Next steps are rendered separately by MessageList via NextStepsBubble */}
      {/* Do NOT render next_steps here to avoid duplication */}

      {/* Footer with metadata */}
      <ReportFooter metadata={message.metadata} />

      {/* Feedback widget */}
      {message.status === MessageStatus.COMPLETED && onSubmitFeedback && message.message_id && (
        <Box sx={{ mt: 2 }}>
          <FeedbackWidget
            messageId={message.message_id}
            conversationId={message.conversation_id || ""}
            onSubmitFeedback={onSubmitFeedback}
          />
        </Box>
      )}
    </Paper>
  );
}

