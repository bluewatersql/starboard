/**
 * Diagnostic report bubble component.
 *
 * Specialized UI for diagnostic/troubleshooting reports from DiagnosticAgent.
 * Displays evidence-based findings with confidence levels and recommendations.
 */

"use client";

import React, { useMemo, useCallback } from "react";
import {
  Box,
  Paper,
  Typography,
  Chip,
  Accordion,
  AccordionSummary,
  AccordionDetails,
  Alert,
  AlertTitle,
  LinearProgress,
} from "@mui/material";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import BugReportIcon from "@mui/icons-material/BugReport";
import WarningAmberIcon from "@mui/icons-material/WarningAmber";
import CheckCircleIcon from "@mui/icons-material/CheckCircle";
import HelpOutlineIcon from "@mui/icons-material/HelpOutline";
import { useTheme } from "@mui/material/styles";
import type {
  Message,
  DiagnosticReport,
  DiagnosticFinding,
  EvidenceWindow,
  NextStepOption,
  FeedbackRating,
  MetricsSummary,
} from "@/lib/types/api";
import { MessageStatus } from "@/lib/types/api";
import { ReportHeader, ReportFooter, BudgetExhaustedAlert } from "../shared";
import { FeedbackWidget } from "../FeedbackWidget";
import { downloadMarkdown, downloadJson } from "@/lib/utils/file-download";
import { exportDiagnosticReportToMarkdown, prepareReportForJsonExport } from "@/lib/utils/report-export";

interface DiagnosticReportBubbleProps {
  /** Message containing the diagnostic report */
  message: Message;
  /** Diagnostic report data */
  report: DiagnosticReport;
  /** Next step selection handler */
  onSelectOption?: (option: NextStepOption) => void;
  /** Feedback submission handler */
  onSubmitFeedback?: (messageId: string, rating: FeedbackRating) => Promise<void>;
}

/**
 * Get confidence color based on level.
 */
function getConfidenceColor(confidence: "high" | "medium" | "low" | number): string {
  if (typeof confidence === "number") {
    if (confidence >= 0.9) return "success";
    if (confidence >= 0.7) return "warning";
    return "error";
  }
  switch (confidence) {
    case "high":
      return "success";
    case "medium":
      return "warning";
    case "low":
      return "error";
    default:
      return "default";
  }
}

/**
 * Get confidence icon based on level.
 */
function getConfidenceIcon(confidence: "high" | "medium" | "low") {
  switch (confidence) {
    case "high":
      return <CheckCircleIcon fontSize="small" />;
    case "medium":
      return <WarningAmberIcon fontSize="small" />;
    case "low":
      return <HelpOutlineIcon fontSize="small" />;
    default:
      return <BugReportIcon fontSize="small" />;
  }
}

/**
 * Get mode badge color.
 */
function getModeColor(mode: "online" | "offline" | "hybrid"): "primary" | "default" | "secondary" {
  switch (mode) {
    case "online":
      return "primary";
    case "hybrid":
      return "secondary";
    default:
      return "default";
  }
}

/**
 * Evidence window card component.
 */
function EvidenceCard({ evidence }: { evidence: EvidenceWindow }) {
  const theme = useTheme();
  
  return (
    <Box
      sx={{
        p: 1.5,
        mb: 1,
        borderRadius: 1,
        bgcolor: theme.palette.mode === "dark"
          ? "rgba(255, 255, 255, 0.05)"
          : "rgba(0, 0, 0, 0.03)",
        borderLeft: `3px solid ${theme.palette.info.main}`,
        fontFamily: "monospace",
        fontSize: "0.85rem",
        whiteSpace: "pre-wrap",
        wordBreak: "break-word",
      }}
    >
      <Box sx={{ display: "flex", justifyContent: "space-between", mb: 0.5 }}>
        <Chip
          label={evidence.id}
          size="small"
          variant="outlined"
          sx={{ height: 20, fontSize: "0.7rem" }}
        />
        <Chip
          label={evidence.type}
          size="small"
          color="info"
          variant="outlined"
          sx={{ height: 20, fontSize: "0.7rem" }}
        />
      </Box>
      <Typography
        component="pre"
        sx={{
          m: 0,
          fontFamily: "monospace",
          fontSize: "0.8rem",
          lineHeight: 1.4,
          color: theme.palette.mode === "dark" ? "grey.300" : "grey.800",
        }}
      >
        {evidence.content}
      </Typography>
      {evidence.line_start && (
        <Typography variant="caption" color="text.secondary" sx={{ mt: 0.5 }}>
          Lines {evidence.line_start}
          {evidence.line_end && evidence.line_end !== evidence.line_start
            ? `-${evidence.line_end}`
            : ""}
        </Typography>
      )}
    </Box>
  );
}

/**
 * Format bytes to human-readable string.
 */
function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(2))} ${sizes[i]}`;
}

/**
 * Format milliseconds to human-readable duration.
 */
function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms} ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  if (ms < 3600000) return `${(ms / 60000).toFixed(1)} min`;
  return `${(ms / 3600000).toFixed(1)} hr`;
}

/**
 * BB-09: Metrics summary section component.
 */
function MetricsSummarySection({ metrics }: { metrics: MetricsSummary }) {
  const theme = useTheme();
  
  return (
    <Box sx={{ display: "flex", flexDirection: "column", gap: 2 }}>
      {/* Execution Summary */}
      {metrics.execution && (
        <Box>
          <Typography variant="subtitle2" sx={{ fontWeight: 600, mb: 1 }}>
            ⏱️ Execution Summary
          </Typography>
          <Box
            component="table"
            sx={{
              width: "100%",
              borderCollapse: "collapse",
              fontSize: "0.85rem",
              "& th, & td": {
                p: 0.75,
                borderBottom: `1px solid ${theme.palette.divider}`,
                textAlign: "left",
              },
              "& th": { fontWeight: 600, width: "40%" },
            }}
          >
            <tbody>
              {metrics.execution.total_time_ms !== undefined && (
                <tr>
                  <th>Total Time</th>
                  <td>{formatDuration(metrics.execution.total_time_ms)}</td>
                </tr>
              )}
              {metrics.execution.compilation_time_ms !== undefined && (
                <tr>
                  <th>Compilation Time</th>
                  <td>{formatDuration(metrics.execution.compilation_time_ms)}</td>
                </tr>
              )}
              {metrics.execution.execution_time_ms !== undefined && (
                <tr>
                  <th>Execution Time</th>
                  <td>{formatDuration(metrics.execution.execution_time_ms)}</td>
                </tr>
              )}
              {metrics.execution.rows_produced !== undefined && (
                <tr>
                  <th>Rows Produced</th>
                  <td>{metrics.execution.rows_produced.toLocaleString()}</td>
                </tr>
              )}
            </tbody>
          </Box>
        </Box>
      )}
      
      {/* I/O Statistics */}
      {metrics.io && (
        <Box>
          <Typography variant="subtitle2" sx={{ fontWeight: 600, mb: 1 }}>
            💾 I/O Statistics
          </Typography>
          <Box
            component="table"
            sx={{
              width: "100%",
              borderCollapse: "collapse",
              fontSize: "0.85rem",
              "& th, & td": {
                p: 0.75,
                borderBottom: `1px solid ${theme.palette.divider}`,
                textAlign: "left",
              },
              "& th": { fontWeight: 600, width: "40%" },
            }}
          >
            <tbody>
              {metrics.io.bytes_read !== undefined && (
                <tr>
                  <th>Bytes Read</th>
                  <td>{formatBytes(metrics.io.bytes_read)}</td>
                </tr>
              )}
              {metrics.io.bytes_pruned !== undefined && (
                <tr>
                  <th>Bytes Pruned</th>
                  <td>✅ {formatBytes(metrics.io.bytes_pruned)}</td>
                </tr>
              )}
              {metrics.io.rows_scanned !== undefined && (
                <tr>
                  <th>Rows Scanned</th>
                  <td>{metrics.io.rows_scanned.toLocaleString()}</td>
                </tr>
              )}
              {metrics.io.cache_hit_pct !== undefined && (
                <tr>
                  <th>Cache Hit Ratio</th>
                  <td>
                    {metrics.io.cache_hit_pct >= 80 ? "✅" : metrics.io.cache_hit_pct >= 50 ? "⚠️" : "❌"}{" "}
                    {metrics.io.cache_hit_pct}%
                  </td>
                </tr>
              )}
            </tbody>
          </Box>
        </Box>
      )}
      
      {/* Processing Efficiency */}
      {metrics.processing && (
        <Box>
          <Typography variant="subtitle2" sx={{ fontWeight: 600, mb: 1 }}>
            ⚡ Processing Efficiency
          </Typography>
          <Box
            component="table"
            sx={{
              width: "100%",
              borderCollapse: "collapse",
              fontSize: "0.85rem",
              "& th, & td": {
                p: 0.75,
                borderBottom: `1px solid ${theme.palette.divider}`,
                textAlign: "left",
              },
              "& th": { fontWeight: 600, width: "40%" },
            }}
          >
            <tbody>
              {metrics.processing.photon_enabled !== undefined && (
                <tr>
                  <th>Photon Enabled</th>
                  <td>{metrics.processing.photon_enabled ? "✅ Yes" : "❌ No"}</td>
                </tr>
              )}
              {metrics.processing.photon_coverage_pct !== undefined && (
                <tr>
                  <th>Photon Coverage</th>
                  <td>{metrics.processing.photon_coverage_pct}%</td>
                </tr>
              )}
              {metrics.processing.peak_memory !== undefined && (
                <tr>
                  <th>Peak Memory Usage</th>
                  <td>{formatBytes(metrics.processing.peak_memory)}</td>
                </tr>
              )}
              {metrics.processing.spill_to_disk !== undefined && (
                <tr>
                  <th>Spill to Disk</th>
                  <td>
                    {metrics.processing.spill_to_disk > 0
                      ? `⚠️ ${formatBytes(metrics.processing.spill_to_disk)}`
                      : "0 bytes"}
                  </td>
                </tr>
              )}
            </tbody>
          </Box>
        </Box>
      )}
    </Box>
  );
}

/**
 * Diagnostic finding card component.
 */
function DiagnosticFindingCard({
  finding,
  index,
  evidenceMap,
  defaultExpanded,
}: {
  finding: DiagnosticFinding;
  index: number;
  evidenceMap: Record<string, EvidenceWindow>;
  defaultExpanded?: boolean;
}) {
  const theme = useTheme();
  const confidenceColor = getConfidenceColor(finding.confidence);
  
  return (
    <Accordion
      defaultExpanded={defaultExpanded}
      sx={{
        mb: 1,
        "&:before": { display: "none" },
        borderRadius: "8px !important",
        overflow: "hidden",
        boxShadow: theme.shadows[1],
      }}
    >
      <AccordionSummary
        expandIcon={<ExpandMoreIcon />}
        sx={{
          bgcolor: theme.palette.mode === "dark"
            ? "rgba(244, 67, 54, 0.08)"
            : "rgba(244, 67, 54, 0.04)",
          borderLeft: `4px solid ${theme.palette.error.main}`,
          "&:hover": {
            bgcolor: theme.palette.mode === "dark"
              ? "rgba(244, 67, 54, 0.12)"
              : "rgba(244, 67, 54, 0.08)",
          },
        }}
      >
        <Box sx={{ display: "flex", alignItems: "center", gap: 1, flex: 1 }}>
          <Typography
            variant="body2"
            sx={{
              fontWeight: 600,
              bgcolor: theme.palette.error.main,
              color: "white",
              px: 1,
              py: 0.25,
              borderRadius: 0.5,
              fontSize: "0.75rem",
            }}
          >
            #{index + 1}
          </Typography>
          <Chip
            label={finding.category}
            size="small"
            variant="outlined"
            sx={{ height: 22, fontSize: "0.7rem" }}
          />
          <Typography variant="subtitle2" sx={{ fontWeight: 600, flex: 1 }}>
            {finding.title}
          </Typography>
          <Chip
            icon={getConfidenceIcon(finding.confidence)}
            label={finding.confidence}
            size="small"
            color={confidenceColor as "success" | "warning" | "error" | "default"}
            sx={{ height: 24 }}
          />
        </Box>
      </AccordionSummary>
      <AccordionDetails sx={{ pt: 2 }}>
        {/* Explanation */}
        <Typography variant="body2" paragraph>
          {finding.explanation}
        </Typography>
        
        {/* Evidence References */}
        {finding.evidence_refs.length > 0 && (
          <Box sx={{ mb: 2 }}>
            <Typography
              variant="subtitle2"
              sx={{ fontWeight: 600, mb: 1, display: "flex", alignItems: "center", gap: 0.5 }}
            >
              📋 Evidence
            </Typography>
            {finding.evidence_refs.map((ref) => {
              const evidence = evidenceMap[ref];
              return evidence ? (
                <EvidenceCard key={ref} evidence={evidence} />
              ) : (
                <Chip key={ref} label={ref} size="small" sx={{ mr: 0.5, mb: 0.5 }} />
              );
            })}
          </Box>
        )}
        
        {/* Recommendations */}
        {finding.recommendations.length > 0 && (
          <Box>
            <Typography
              variant="subtitle2"
              sx={{ fontWeight: 600, mb: 1, display: "flex", alignItems: "center", gap: 0.5 }}
            >
              💡 Recommendations
            </Typography>
            <Box component="ul" sx={{ m: 0, pl: 2.5 }}>
              {finding.recommendations.map((rec, i) => (
                <Typography key={i} component="li" variant="body2" sx={{ mb: 0.5 }}>
                  {rec}
                </Typography>
              ))}
            </Box>
          </Box>
        )}
      </AccordionDetails>
    </Accordion>
  );
}

/**
 * Diagnostic report bubble component.
 *
 * Renders diagnostic/troubleshooting reports with evidence and findings.
 */
export function DiagnosticReportBubble({
  message,
  report,
  onSubmitFeedback,
}: Omit<DiagnosticReportBubbleProps, "onSelectOption">) {
  const theme = useTheme();
  
  // Build evidence lookup map
  const evidenceMap = useMemo(() => {
    const map: Record<string, EvidenceWindow> = {};
    report.evidence_windows?.forEach((ev) => {
      map[ev.id] = ev;
    });
    return map;
  }, [report.evidence_windows]);
  
  // Get stable timestamp for downloads
  const reportTimestamp = useMemo(() => {
    return message.timestamp
      ? new Date(message.timestamp).toISOString().split("T")[0]
      : new Date().toISOString().split("T")[0];
  }, [message.timestamp]);
  
  // Download handlers - BB-04: Generate comprehensive, visually stunning exports
  const handleDownloadMarkdown = useCallback(() => {
    // Use comprehensive markdown export utility
    const markdown = exportDiagnosticReportToMarkdown({
      report,
      timestamp: message.timestamp,
    });
    downloadMarkdown(markdown, `diagnostic-report-${reportTimestamp}.md`);
  }, [report, message.timestamp, reportTimestamp]);
  
  const handleDownloadJSON = useCallback(() => {
    // Export complete report with metadata
    const exportData = prepareReportForJsonExport(
      message.metadata?.complete_report || report,
      {
        timestamp: message.timestamp,
        domain: "diagnostic",
        conversationId: message.conversation_id,
      }
    );
    downloadJson(exportData, `diagnostic-report-${reportTimestamp}.json`);
  }, [message.metadata, message.timestamp, message.conversation_id, report, reportTimestamp]);
  
  // Calculate overall confidence percentage for progress bar
  const confidencePercent = (report.summary?.confidence || 0) * 100;
  
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
              bgcolor: theme.palette.mode === "dark"
                ? "rgba(244, 67, 54, 0.08)"
                : "rgba(244, 67, 54, 0.04)",
              borderRadius: 2,
              borderLeft: `4px solid ${theme.palette.error.main}`,
            }}
          >
            {/* Header */}
            <ReportHeader
              title="Diagnostic Analysis"
              icon="🔍"
              onDownloadMarkdown={handleDownloadMarkdown}
              onDownloadJSON={handleDownloadJSON}
              hasCompleteReport={!!message.metadata?.complete_report}
              conversationId={message.conversation_id}
            />
            
            {/* Budget exhaustion warning */}
            {report.budget_exhausted && <BudgetExhaustedAlert />}
            
            {/* Mode and confidence badges */}
            <Box sx={{ display: "flex", gap: 1, mb: 2, flexWrap: "wrap" }}>
              {report.summary?.mode && (
                <Chip
                  label={`Mode: ${report.summary.mode.toUpperCase()}`}
                  size="small"
                  color={getModeColor(report.summary.mode)}
                  variant="outlined"
                />
              )}
              {report.summary?.artifact_type && (
                <Chip
                  label={`Artifact: ${report.summary.artifact_type}`}
                  size="small"
                  variant="outlined"
                />
              )}
            </Box>
            
            {/* Confidence meter */}
            {report.summary?.confidence !== undefined && (
              <Box sx={{ mb: 2 }}>
                <Box sx={{ display: "flex", justifyContent: "space-between", mb: 0.5 }}>
                  <Typography variant="caption" color="text.secondary">
                    Confidence
                  </Typography>
                  <Typography
                    variant="caption"
                    color={
                      confidencePercent >= 90
                        ? "success.main"
                        : confidencePercent >= 70
                          ? "warning.main"
                          : "error.main"
                    }
                    fontWeight={600}
                  >
                    {confidencePercent.toFixed(0)}%
                  </Typography>
                </Box>
                <LinearProgress
                  variant="determinate"
                  value={confidencePercent}
                  color={
                    confidencePercent >= 90
                      ? "success"
                      : confidencePercent >= 70
                        ? "warning"
                        : "error"
                  }
                  sx={{ height: 6, borderRadius: 3 }}
                />
              </Box>
            )}
            
            {/* Overview */}
            {report.summary?.overview && (
              <Alert
                severity={confidencePercent >= 70 ? "info" : "warning"}
                sx={{ mb: 2 }}
              >
                <AlertTitle>
                  {confidencePercent >= 90
                    ? "Diagnosis"
                    : confidencePercent >= 70
                      ? "Likely Diagnosis"
                      : "Analysis"}
                </AlertTitle>
                {report.summary.overview}
              </Alert>
            )}
            
            {/* Findings */}
            {report.findings && report.findings.length > 0 && (
              <Box sx={{ mb: 2 }}>
                <Typography
                  variant="h6"
                  sx={{
                    fontWeight: 600,
                    mb: 1.5,
                    display: "flex",
                    alignItems: "center",
                    gap: 1,
                  }}
                >
                  🔎 Findings ({report.findings.length})
                </Typography>
                {report.findings.map((finding, index) => (
                  <DiagnosticFindingCard
                    key={finding.id || index}
                    finding={finding}
                    index={index}
                    evidenceMap={evidenceMap}
                    defaultExpanded={index === 0}
                  />
                ))}
              </Box>
            )}
            
            {/* BB-09: Metrics Summary - only show for applicable artifact types */}
            {report.metrics_summary && (
              <Accordion defaultExpanded sx={{ mb: 2 }}>
                <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                  <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
                    📊 Metrics Summary
                  </Typography>
                </AccordionSummary>
                <AccordionDetails>
                  <MetricsSummarySection metrics={report.metrics_summary} />
                </AccordionDetails>
              </Accordion>
            )}
            
            {/* Evidence Windows (collapsed by default) */}
            {report.evidence_windows && report.evidence_windows.length > 0 && (
              <Accordion sx={{ mb: 2 }}>
                <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                  <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
                    📋 All Evidence ({report.evidence_windows.length} items)
                  </Typography>
                </AccordionSummary>
                <AccordionDetails>
                  {report.evidence_windows.map((ev) => (
                    <EvidenceCard key={ev.id} evidence={ev} />
                  ))}
                </AccordionDetails>
              </Accordion>
            )}
            
            {/* BB-09: Optimized Code Section */}
            {report.optimized_code && (
              <Accordion sx={{ mb: 2 }}>
                <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                  <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
                    ✨ Optimized Query/Code
                  </Typography>
                </AccordionSummary>
                <AccordionDetails>
                  <Paper
                    variant="outlined"
                    sx={{
                      p: 1.5,
                      bgcolor: theme.palette.mode === "dark"
                        ? "rgba(0, 0, 0, 0.2)"
                        : "rgba(0, 0, 0, 0.02)",
                    }}
                  >
                    <Typography
                      component="pre"
                      sx={{
                        m: 0,
                        fontFamily: "monospace",
                        fontSize: "0.85rem",
                        lineHeight: 1.4,
                        whiteSpace: "pre-wrap",
                        wordBreak: "break-word",
                      }}
                    >
                      {report.optimized_code}
                    </Typography>
                  </Paper>
                </AccordionDetails>
              </Accordion>
            )}
            
            {/* Handoff suggestion */}
            {report.fingerprint?.recommended_handoff_target &&
              report.fingerprint.recommended_handoff_target !== "diagnostic" && (
                <Alert severity="info" sx={{ mb: 2 }}>
                  <AlertTitle>Specialist Recommended</AlertTitle>
                  This issue may benefit from analysis by the{" "}
                  <strong>{report.fingerprint.recommended_handoff_target}</strong> agent.
                  {report.fingerprint.primary_symptom && (
                    <Typography variant="body2" sx={{ mt: 0.5 }}>
                      Primary symptom: {report.fingerprint.primary_symptom}
                    </Typography>
                  )}
                </Alert>
              )}
            
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

