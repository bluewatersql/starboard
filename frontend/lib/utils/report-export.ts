/**
 * Report Export Utilities.
 *
 * Generates comprehensive, visually stunning markdown and JSON exports
 * for domain-specific reports (Advisor, Diagnostic, Warehouse, etc.)
 *
 * BB-04: Full analysis report export with emphasis on markdown aesthetics.
 *
 * @module lib/utils/report-export
 */

import type {
  AdvisorReport,
  DiagnosticReport,
  DiagnosticFingerprint,
  EvidenceWindow,
  Finding,
  ImpactEstimate,
  EffortEstimate,
} from "@/lib/types/api";

// ============================================================================
// EXTENDED TYPES FOR EXPORT
// These interfaces capture optional fields that the LLM may include beyond
// the strict schema definitions. They are used only in export functions.
// ============================================================================

/** Fields that query/job agents may include on top of AdvisorReport. */
interface AdvisorReportExtended extends AdvisorReport {
  /** Query ID for query-domain reports */
  entity_id?: string;
  /** Optimized SQL rewrite suggested by LLM */
  optimized_query?: string;
  /** Domain label (e.g. "query", "job") */
  domain?: string;
  /** Whether the analysis budget was exhausted */
  budget_exhausted?: boolean;
}

/** Query-info block that may appear on Analysis for query-domain reports. */
interface AnalysisWithQueryInfo {
  query_info?: {
    warehouse_id?: string;
    duration_ms?: number;
    rows_produced?: number;
    bytes_read?: number;
  };
}

/** DiagnosticFingerprint may include an error_category field. */
interface DiagnosticFingerprintExtended extends DiagnosticFingerprint {
  error_category?: string;
}

// ============================================================================
// COMMON UTILITIES
// ============================================================================

/**
 * Format a timestamp for display in reports.
 */
function formatTimestamp(timestamp?: string): string {
  if (!timestamp) return new Date().toISOString();
  return new Date(timestamp).toISOString();
}

/**
 * Get current date as YYYY-MM-DD.
 */
function getDateString(timestamp?: string): string {
  const date = timestamp ? new Date(timestamp) : new Date();
  return date.toISOString().split("T")[0] ?? "";
}

/**
 * Escape pipe characters for markdown tables.
 */
function escapeTableCell(value: string | number | undefined | null): string {
  if (value === undefined || value === null) return "-";
  return String(value).replace(/\|/g, "\\|").replace(/\n/g, " ");
}

/**
 * Format bytes to human-readable size.
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
  if (ms < 60000) return `${(ms / 1000).toFixed(1)} s`;
  if (ms < 3600000) return `${(ms / 60000).toFixed(1)} min`;
  return `${(ms / 3600000).toFixed(1)} hr`;
}

/**
 * Get severity emoji for findings.
 */
function getSeverityEmoji(severity: string | undefined): string {
  switch (severity?.toLowerCase()) {
    case "critical":
    case "high":
      return "🔴";
    case "warning":
    case "medium":
      return "🟠";
    case "info":
    case "low":
      return "🟡";
    case "positive":
    case "success":
      return "🟢";
    default:
      return "⚪";
  }
}

/**
 * Get confidence badge text.
 */
function getConfidenceBadge(confidence: string | number | undefined): string {
  if (typeof confidence === "number") {
    const pct = Math.round(confidence * 100);
    if (pct >= 90) return `✅ ${pct}%`;
    if (pct >= 70) return `⚠️ ${pct}%`;
    return `❓ ${pct}%`;
  }
  switch (confidence) {
    case "high":
      return "✅ High";
    case "medium":
      return "⚠️ Medium";
    case "low":
      return "❓ Low";
    default:
      return confidence || "Unknown";
  }
}

/**
 * Map confidence level to display severity for findings table.
 * BB-09: Use consistent severity labels in reports.
 */
function mapConfidenceToSeverity(confidence: string | number | undefined): string {
  if (typeof confidence === "number") {
    if (confidence >= 0.9) return "High";
    if (confidence >= 0.7) return "Medium";
    return "Low";
  }
  switch (confidence) {
    case "high":
      return "High";
    case "medium":
      return "Medium";
    case "low":
      return "Low";
    default:
      return "Info";
  }
}

/**
 * Format ImpactEstimate for display.
 * Shows percentage impact with confidence indicator.
 */
function formatImpactEstimate(impact: ImpactEstimate | undefined): string {
  if (!impact) return "Unknown";
  
  const parts: string[] = [];
  
  // Primary metric is query_time_pct
  if (impact.query_time_pct !== undefined) {
    parts.push(`${impact.query_time_pct.toFixed(0)}% Query Time`);
  }
  if (impact.data_read_pct !== undefined && impact.data_read_pct > 0) {
    parts.push(`${impact.data_read_pct.toFixed(0)}% Data Read`);
  }
  if (impact.cost_pct !== undefined && impact.cost_pct > 0) {
    parts.push(`${impact.cost_pct.toFixed(0)}% Cost`);
  }
  
  if (parts.length === 0) return "Unknown";
  
  const confidenceEmoji = getSeverityEmoji(impact.confidence);
  return `${confidenceEmoji} ${parts.join(", ")} (${impact.confidence} confidence)`;
}

/**
 * Format EffortEstimate for display.
 * Shows level with optional time estimate.
 */
function formatEffortEstimate(effort: EffortEstimate | string | undefined): string {
  if (!effort) return "Unknown";
  
  // Handle string fallback for compatibility
  if (typeof effort === "string") {
    return effort;
  }
  
  const level = effort.level?.charAt(0).toUpperCase() + effort.level?.slice(1) || "Unknown";
  
  if (effort.estimate_hours != null && effort.estimate_hours > 0) {
    if (effort.estimate_hours < 1) {
      return `${level} (~${Math.round(effort.estimate_hours * 60)} min)`;
    }
    return `${level} (~${effort.estimate_hours.toFixed(1)} hrs)`;
  }
  
  return level;
}

// ============================================================================
// ADVISOR REPORT EXPORT
// ============================================================================

export interface AdvisorExportOptions {
  /** Report data */
  report: AdvisorReport;
  /** Message timestamp */
  timestamp?: string;
  /** Include raw JSON in appendix */
  includeRawJson?: boolean;
}

/**
 * Export an Advisor report to comprehensive markdown.
 */
export function exportAdvisorReportToMarkdown(options: AdvisorExportOptions): string {
  const { report: reportBase, timestamp } = options;
  const report = reportBase as AdvisorReportExtended;
  const date = getDateString(timestamp);
  const sections: string[] = [];

  // Header
  sections.push(`# 📊 Performance Analysis Report`);
  sections.push(`> Generated on ${formatTimestamp(timestamp)}`);
  sections.push("");

  // Table of Contents
  sections.push(`## 📋 Table of Contents`);
  sections.push(`1. [Executive Summary](#executive-summary)`);
  if (report.analysis?.findings?.length) {
    sections.push(`2. [Key Findings](#key-findings)`);
    sections.push(`3. [Recommendations](#recommendations)`);
  }
  if (report.optimized_query) {
    sections.push(`4. [Optimized Query](#optimized-query)`);
  }
  sections.push(`5. [Appendix](#appendix)`);
  sections.push("");

  // Executive Summary
  sections.push(`## 📝 Executive Summary`);
  sections.push("");
  if (report.summary?.overview) {
    sections.push(report.summary.overview);
  } else {
    sections.push("*No summary available.*");
  }
  sections.push("");

  // Query Info (if available)
  const analysisWithQI = report.analysis as AnalysisWithQueryInfo | undefined;
  if (report.entity_id || analysisWithQI?.query_info) {
    sections.push(`### Query Information`);
    sections.push("");
    sections.push(`| Property | Value |`);
    sections.push(`|----------|-------|`);
    if (report.entity_id) {
      sections.push(`| **Query ID** | \`${escapeTableCell(report.entity_id)}\` |`);
    }
    if (analysisWithQI?.query_info) {
      const qi = analysisWithQI.query_info;
      if (qi.warehouse_id) {
        sections.push(`| **Warehouse** | \`${escapeTableCell(qi.warehouse_id)}\` |`);
      }
      if (qi.duration_ms) {
        sections.push(`| **Duration** | ${formatDuration(qi.duration_ms)} |`);
      }
      if (qi.rows_produced) {
        sections.push(`| **Rows Produced** | ${qi.rows_produced.toLocaleString()} |`);
      }
      if (qi.bytes_read) {
        sections.push(`| **Data Read** | ${formatBytes(qi.bytes_read)} |`);
      }
    }
    sections.push("");
  }

  // Key Findings
  if (report.analysis?.findings?.length) {
    sections.push(`## 🔍 Key Findings`);
    sections.push("");
    sections.push(`| # | Category | Severity | Issue |`);
    sections.push(`|---|----------|----------|-------|`);
    report.analysis.findings.forEach((finding, idx) => {
      // Handle both Finding type (with impact_estimate) and legacy format (with impact)
      const typedFinding = finding as Finding & { impact?: string; description?: string; explanation?: string; code_fix?: string };
      const impactConfidence = typedFinding.impact_estimate?.confidence || typedFinding.impact;
      const emoji = getSeverityEmoji(impactConfidence);
      const severity = mapConfidenceToSeverity(impactConfidence);
      sections.push(
        `| ${idx + 1} | ${emoji} ${escapeTableCell(finding.category)} | ${severity} | ${escapeTableCell(finding.title)} |`
      );
    });
    sections.push("");

    // Detailed Recommendations
    sections.push(`## 💡 Recommendations`);
    sections.push("");
    report.analysis.findings.forEach((finding, idx) => {
      // Handle both Finding type (with impact_estimate/effort) and legacy format
      const typedFinding = finding as Finding & { impact?: string; description?: string; explanation?: string; code_fix?: string };
      
      sections.push(`### ${idx + 1}. ${finding.title}`);
      sections.push("");
      sections.push(`**Category:** ${finding.category}`);
      sections.push(`**Impact:** ${formatImpactEstimate(typedFinding.impact_estimate)}`);
      sections.push(`**Effort:** ${formatEffortEstimate(typedFinding.effort)}`);
      sections.push("");
      sections.push(typedFinding.explanation || typedFinding.description || "*No description available.*");
      sections.push("");
      if (finding.recommendation) {
        sections.push(`**Recommendation:**`);
        sections.push(finding.recommendation);
        sections.push("");
      }
      if (typedFinding.code_fix) {
        sections.push(`**Suggested Fix:**`);
        sections.push("```sql");
        sections.push(typedFinding.code_fix);
        sections.push("```");
        sections.push("");
      }
      sections.push("---");
      sections.push("");
    });
  }

  // Optimized Query
  if (report.optimized_query) {
    sections.push(`## ✨ Optimized Query`);
    sections.push("");
    sections.push("```sql");
    sections.push(report.optimized_query);
    sections.push("```");
    sections.push("");
  }

  // Appendix
  sections.push(`## 📎 Appendix`);
  sections.push("");
  sections.push(`### Metadata`);
  sections.push("");
  sections.push(`| Property | Value |`);
  sections.push(`|----------|-------|`);
  sections.push(`| **Report Date** | ${date} |`);
  sections.push(`| **Domain** | ${report.domain ?? "query"} |`);
  if (report.budget_exhausted) {
    sections.push(`| **Budget Status** | ⚠️ Exhausted |`);
  }
  sections.push("");

  sections.push("---");
  sections.push(`*Report generated by Starboard AI Agent*`);

  return sections.join("\n");
}

// ============================================================================
// DIAGNOSTIC REPORT EXPORT
// ============================================================================

export interface DiagnosticExportOptions {
  /** Report data */
  report: DiagnosticReport;
  /** Message timestamp */
  timestamp?: string;
  /** Include raw JSON in appendix */
  includeRawJson?: boolean;
}

/**
 * Export a Diagnostic report to comprehensive markdown.
 * BB-09: Enhanced format with flexible sections based on context.
 */
export function exportDiagnosticReportToMarkdown(options: DiagnosticExportOptions): string {
  const { report, timestamp } = options;
  const date = getDateString(timestamp);
  const sections: string[] = [];

  // Header
  sections.push(`# 🔍 Diagnostic Analysis Report`);
  sections.push(`> Generated on ${formatTimestamp(timestamp)}`);
  sections.push("");

  // Mode & Confidence badges
  const badges: string[] = [];
  if (report.summary?.mode) {
    badges.push(`**Mode:** ${report.summary.mode.toUpperCase()}`);
  }
  if (report.summary?.confidence !== undefined) {
    badges.push(`**Confidence:** ${getConfidenceBadge(report.summary.confidence)}`);
  }
  if (report.summary?.artifact_type) {
    badges.push(`**Artifact:** ${report.summary.artifact_type}`);
  }
  if (badges.length > 0) {
    sections.push(badges.join(" | "));
    sections.push("");
  }

  // Determine if metrics are applicable based on artifact type
  const hasMetricsContext = report.summary?.artifact_type && 
    ["query_profile", "spark_log", "task_log", "execution_log"].includes(report.summary.artifact_type);

  // Table of Contents
  sections.push(`## 📋 Table of Contents`);
  sections.push(`1. [Summary](#summary)`);
  if (report.findings?.length) {
    sections.push(`2. [Key Findings](#key-findings)`);
  }
  if (hasMetricsContext && report.metrics_summary) {
    sections.push(`3. [Metrics Summary](#metrics-summary)`);
  }
  sections.push(`4. [Recommendations](#recommendations)`);
  if (report.optimized_code) {
    sections.push(`5. [Optimized Query/Code](#optimized-querycode)`);
  }
  sections.push(`6. [Appendix](#appendix)`);
  sections.push("");

  // Summary
  sections.push(`## 📝 Summary`);
  sections.push("");
  if (report.summary?.overview) {
    sections.push(report.summary.overview);
  } else {
    sections.push("*No summary available.*");
  }
  sections.push("");

  // Key Findings - BB-09 format with severity-based emojis
  if (report.findings?.length) {
    sections.push(`## 🔎 Key Findings`);
    sections.push("");
    
    // Summary table with severity emojis (BB-09 format)
    sections.push(`| # | Category | Severity | Issue |`);
    sections.push(`|---|----------|----------|-------|`);
    report.findings.forEach((finding, idx) => {
      const severity = mapConfidenceToSeverity(finding.confidence);
      const emoji = getSeverityEmoji(severity);
      sections.push(
        `| ${idx + 1} | ${emoji} ${escapeTableCell(finding.category)} | ${severity} | ${escapeTableCell(finding.title)} |`
      );
    });
    sections.push("");

    // Detailed Findings
    sections.push(`### Detailed Findings`);
    sections.push("");
    report.findings.forEach((finding, idx) => {
      sections.push(`#### ${idx + 1}. ${finding.title}`);
      sections.push("");
      sections.push(`**Category:** ${finding.category}`);
      sections.push(`**Confidence:** ${getConfidenceBadge(finding.confidence)}`);
      sections.push("");
      sections.push(finding.explanation || "*No explanation available.*");
      sections.push("");
      if (finding.recommendations?.length) {
        sections.push(`**Recommendations:**`);
        finding.recommendations.forEach((rec) => {
          sections.push(`- ${rec}`);
        });
        sections.push("");
      }
      if (finding.evidence_refs?.length) {
        sections.push(`**Evidence:** ${finding.evidence_refs.map((e) => `\`${e}\``).join(", ")}`);
        sections.push("");
      }
      sections.push("---");
      sections.push("");
    });
  }

  // Metrics Summary - BB-09: Only include for applicable artifact types
  if (hasMetricsContext && report.metrics_summary) {
    sections.push(`## 📊 Metrics Summary`);
    sections.push("");
    
    const metrics = report.metrics_summary as Record<string, unknown>;
    
    // Execution Summary
    if (metrics.execution) {
      const exec = metrics.execution as Record<string, unknown>;
      sections.push(`### Execution Summary`);
      sections.push("");
      sections.push(`| Metric | Value |`);
      sections.push(`|--------|-------|`);
      if (exec.total_time_ms) sections.push(`| **Total Time** | ${formatDuration(exec.total_time_ms as number)} |`);
      if (exec.compilation_time_ms) sections.push(`| **Compilation Time** | ${formatDuration(exec.compilation_time_ms as number)} |`);
      if (exec.execution_time_ms) sections.push(`| **Execution Time** | ${formatDuration(exec.execution_time_ms as number)} |`);
      if (exec.rows_produced) sections.push(`| **Rows Produced** | ${(exec.rows_produced as number).toLocaleString()} |`);
      sections.push("");
    }

    // I/O Statistics
    if (metrics.io) {
      const io = metrics.io as Record<string, unknown>;
      sections.push(`### I/O Statistics`);
      sections.push("");
      sections.push(`| Metric | Value | Notes |`);
      sections.push(`|--------|-------|-------|`);
      if (io.bytes_read) sections.push(`| **Bytes Read** | ${formatBytes(io.bytes_read as number)} | From cloud storage |`);
      if (io.bytes_pruned) sections.push(`| **Bytes Pruned** | ${formatBytes(io.bytes_pruned as number)} | ✅ Partition pruning |`);
      if (io.rows_scanned) sections.push(`| **Rows Scanned** | ${(io.rows_scanned as number).toLocaleString()} | Before filtering |`);
      if (io.cache_hit_pct !== undefined) {
        const cachePct = io.cache_hit_pct as number;
        const cacheEmoji = cachePct >= 80 ? "✅" : cachePct >= 50 ? "⚠️" : "❌";
        sections.push(`| **Cache Hit Ratio** | ${cachePct}% | ${cacheEmoji} |`);
      }
      sections.push("");
    }

    // Processing Efficiency
    if (metrics.processing) {
      const proc = metrics.processing as Record<string, unknown>;
      sections.push(`### Processing Efficiency`);
      sections.push("");
      sections.push(`| Metric | Value |`);
      sections.push(`|--------|-------|`);
      if (proc.photon_enabled !== undefined) sections.push(`| **Photon Enabled** | ${proc.photon_enabled ? "✅ Yes" : "❌ No"} |`);
      if (proc.photon_coverage_pct !== undefined) sections.push(`| **Photon Coverage** | ${proc.photon_coverage_pct}% |`);
      if (proc.peak_memory) sections.push(`| **Peak Memory Usage** | ${formatBytes(proc.peak_memory as number)} |`);
      if (proc.spill_to_disk !== undefined) {
        const spill = proc.spill_to_disk as number;
        sections.push(`| **Spill to Disk** | ${spill > 0 ? `⚠️ ${formatBytes(spill)}` : "0 bytes"} |`);
      }
      sections.push("");
    }
  } else if (report.evidence_windows?.length) {
    // Fallback: show evidence windows if no structured metrics
    sections.push(`## 📋 Evidence Windows`);
    sections.push("");
    
    // Group evidence by type
    const evidenceByType: Record<string, EvidenceWindow[]> = {};
    report.evidence_windows.forEach((ev) => {
      const type = ev.type || "other";
      if (!evidenceByType[type]) {
        evidenceByType[type] = [];
      }
      evidenceByType[type].push(ev);
    });

    for (const [type, evidence] of Object.entries(evidenceByType)) {
      sections.push(`### ${type.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())}`);
      sections.push("");
      evidence.forEach((ev) => {
        sections.push(`**${ev.id}:**`);
        sections.push("```");
        sections.push(ev.content.slice(0, 500) + (ev.content.length > 500 ? "\n..." : ""));
        sections.push("```");
        if (ev.line_start) {
          sections.push(`*Lines ${ev.line_start}${ev.line_end ? `-${ev.line_end}` : ""}*`);
        }
        sections.push("");
      });
    }
  }

  // Recommendations
  sections.push(`## 💡 Recommendations`);
  sections.push("");
  let hasRecommendations = false;
  report.findings?.forEach((finding) => {
    if (finding.recommendations?.length) {
      hasRecommendations = true;
      finding.recommendations.forEach((rec) => {
        sections.push(`- ${rec}`);
      });
    }
  });
  if (!hasRecommendations) {
    sections.push("*No specific recommendations at this time.*");
  }
  sections.push("");

  // Optimized Query/Code - BB-09: Include when available
  if (report.optimized_code) {
    sections.push(`## ✨ Optimized Query/Code`);
    sections.push("");
    sections.push("```sql");
    sections.push(report.optimized_code);
    sections.push("```");
    sections.push("");
  }

  // Appendix
  sections.push(`## 📎 Appendix`);
  sections.push("");

  // Databricks Context
  if (report.fingerprint) {
    const fingerprint = report.fingerprint as DiagnosticFingerprintExtended;
    sections.push(`### Databricks Context`);
    sections.push("");
    sections.push(`| Property | Value |`);
    sections.push(`|----------|-------|`);
    if (fingerprint.error_category) {
      sections.push(`| **Error Category** | ${fingerprint.error_category} |`);
    }
    if (report.fingerprint.primary_symptom) {
      sections.push(`| **Primary Symptom** | ${report.fingerprint.primary_symptom} |`);
    }
    if (report.fingerprint.recommended_handoff_target) {
      sections.push(`| **Recommended Specialist** | ${report.fingerprint.recommended_handoff_target} |`);
    }
    sections.push("");
  }

  // Metadata
  sections.push(`### Report Metadata`);
  sections.push("");
  sections.push(`| Property | Value |`);
  sections.push(`|----------|-------|`);
  sections.push(`| **Report Date** | ${date} |`);
  if (report.summary?.mode) {
    sections.push(`| **Analysis Mode** | ${report.summary.mode} |`);
  }
  if (report.summary?.artifact_type) {
    sections.push(`| **Artifact Type** | ${report.summary.artifact_type} |`);
  }
  if (report.budget_exhausted) {
    sections.push(`| **Budget Status** | ⚠️ Exhausted |`);
  }
  sections.push("");

  sections.push("---");
  sections.push(`*Report generated by Starboard AI Agent*`);

  return sections.join("\n");
}

// ============================================================================
// WAREHOUSE REPORT EXPORT
// ============================================================================

export interface WarehouseExportOptions {
  /** Report data */
  report: Record<string, unknown>;
  /** Message timestamp */
  timestamp?: string;
}

/**
 * Export a Warehouse report to comprehensive markdown.
 */
export function exportWarehouseReportToMarkdown(options: WarehouseExportOptions): string {
  const { report, timestamp } = options;
  const date = getDateString(timestamp);
  const sections: string[] = [];

  // Header
  sections.push(`# 🏭 SQL Warehouse Analysis Report`);
  sections.push(`> Generated on ${formatTimestamp(timestamp)}`);
  sections.push("");

  // Summary
  sections.push(`## 📝 Summary`);
  sections.push("");
  const summary = report.summary as Record<string, unknown> | undefined;
  if (summary?.overview) {
    sections.push(String(summary.overview));
  } else {
    sections.push("*No summary available.*");
  }
  sections.push("");

  // Findings
  const findings = report.findings as Array<Record<string, unknown>> | undefined;
  if (findings?.length) {
    sections.push(`## 🔍 Key Findings`);
    sections.push("");
    sections.push(`| # | Finding | Impact |`);
    sections.push(`|---|---------|--------|`);
    findings.forEach((finding, idx) => {
      const impact = String(finding.impact || "Unknown");
      sections.push(
        `| ${idx + 1} | ${escapeTableCell(String(finding.title || finding.description || ""))} | ${getSeverityEmoji(impact)} ${impact} |`
      );
    });
    sections.push("");

    // Detailed findings
    findings.forEach((finding, idx) => {
      sections.push(`### ${idx + 1}. ${finding.title || "Finding"}`);
      sections.push("");
      if (finding.description) {
        sections.push(String(finding.description));
        sections.push("");
      }
      if (finding.recommendation) {
        sections.push(`**Recommendation:** ${finding.recommendation}`);
        sections.push("");
      }
    });
  }

  // Recommendations
  const recommendations = report.recommendations as string[] | undefined;
  if (recommendations?.length) {
    sections.push(`## 💡 Recommendations`);
    sections.push("");
    recommendations.forEach((rec) => {
      sections.push(`- ${rec}`);
    });
    sections.push("");
  }

  // Appendix
  sections.push(`## 📎 Appendix`);
  sections.push("");
  sections.push(`| Property | Value |`);
  sections.push(`|----------|-------|`);
  sections.push(`| **Report Date** | ${date} |`);
  sections.push("");

  sections.push("---");
  sections.push(`*Report generated by Starboard AI Agent*`);

  return sections.join("\n");
}

// ============================================================================
// GENERIC JSON EXPORT
// ============================================================================

/**
 * Prepare a report for JSON export with consistent structure.
 */
export function prepareReportForJsonExport(
  report: unknown,
  metadata?: {
    timestamp?: string;
    domain?: string;
    conversationId?: string;
  }
): object {
  return {
    _export_metadata: {
      exported_at: formatTimestamp(metadata?.timestamp),
      domain: metadata?.domain || "unknown",
      conversation_id: metadata?.conversationId,
      version: "1.0.0",
    },
    report,
  };
}

