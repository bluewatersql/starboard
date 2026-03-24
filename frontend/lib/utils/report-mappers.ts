/**
 * Report data transformation utilities.
 *
 * Maps backend report structures to frontend-friendly formats for UI components.
 */

import type { RecommendationItem } from "@/components/chat/reports/RecommendationCard";

/**
 * Backend Finding structure (from LLM schemas).
 */
export interface Finding {
  id: string;
  title: string;
  recommendation: string;
  category:
    | "QUERY"
    | "TABLE"
    | "WAREHOUSE"
    | "JOB_CONFIG"
    | "CODE"
    | "CLUSTER"
    | "DATA"
    | "RUNTIME"
    | "SCHEMA"
    | "RESOURCE";
  impact_estimate: {
    query_time_pct: number;
    data_read_pct?: number;
    cost_pct?: number;
    shuffle_pct?: number;
    confidence: "low" | "medium" | "high";
  };
  effort: {
    level: "low" | "medium" | "high";
    estimate_hours?: number | null;
  };
  fixes?: Array<{
    type:
      | "SQL_REWRITE"
      | "DDL_DML"
      | "CONFIG_CHANGE"
      | "PROCESS_CHANGE"
      | "CODE_REWRITE"
      | "CLUSTER_TUNING"
      | "DATA_OPTIMIZATION";
    snippet: string;
    notes?: string;
  }>;
  rank: number;
  [key: string]: unknown; // Allow additional fields
}

/**
 * Convert impact estimate to simple high/medium/low classification.
 *
 * Uses query_time_pct as primary signal, with fallback to cost_pct.
 *
 * @param impact - Impact estimate from backend
 * @returns Impact level for frontend badge
 */
export function convertImpactEstimate(
  impact: Finding["impact_estimate"] | undefined | null
): "high" | "medium" | "low" {
  // Handle missing impact estimate - defensive for different report types
  if (!impact) {
    return "medium"; // Default to medium when unknown
  }

  // Primary: Use query time percentage
  const timePct = impact.query_time_pct || 0;
  if (timePct >= 20) return "high";
  if (timePct >= 10) return "medium";

  // Fallback: Use cost percentage
  const costPct = impact.cost_pct || 0;
  if (costPct >= 20) return "high";
  if (costPct >= 10) return "medium";

  return "low";
}

/**
 * Extract SQL code from fixes array.
 *
 * Prioritizes SQL_REWRITE and DDL_DML fix types.
 *
 * @param fixes - Array of fix suggestions
 * @returns First SQL snippet found, or undefined
 */
export function extractSQLFromFixes(
  fixes?: Finding["fixes"]
): string | undefined {
  if (!fixes || fixes.length === 0) return undefined;

  // Prioritize SQL-related fixes (with non-empty snippets)
  const sqlFix = fixes.find(
    (f) =>
      (f.type === "SQL_REWRITE" || f.type === "DDL_DML") &&
      f.snippet &&
      f.snippet.trim()
  );

  if (sqlFix) return sqlFix.snippet;

  // Fallback: Return first fix with a non-empty snippet
  const anyFix = fixes.find((f) => f.snippet && f.snippet.trim());
  return anyFix?.snippet;
}

/**
 * Format category string for display.
 *
 * Converts SCREAMING_SNAKE_CASE to Title Case.
 *
 * @param category - Backend category enum value
 * @returns Formatted category string
 *
 * @example
 * formatCategory("QUERY_OPTIMIZATION") // "Query Optimization"
 * formatCategory("TABLE") // "Table"
 */
export function formatCategory(category: string): string {
  return category
    .toLowerCase()
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

/**
 * Format impact estimate as human-readable percentage.
 *
 * @param impact - Impact estimate from backend
 * @returns Formatted percentage string, or undefined
 *
 * @example
 * formatImpactPercentage({ query_time_pct: 25, confidence: "high" })
 * // "~25% faster"
 */
export function formatImpactPercentage(
  impact: Finding["impact_estimate"] | undefined | null
): string | undefined {
  // Handle missing impact estimate - defensive for different report types
  if (!impact) {
    return undefined;
  }

  const timePct = impact.query_time_pct || 0;
  if (timePct > 0) {
    return `~${Math.round(timePct)}% faster`;
  }

  const costPct = impact.cost_pct || 0;
  if (costPct > 0) {
    return `~${Math.round(costPct)}% cheaper`;
  }

  const dataReadPct = impact.data_read_pct || 0;
  if (dataReadPct > 0) {
    return `~${Math.round(dataReadPct)}% less data`;
  }

  return undefined;
}

/**
 * Format effort estimate as time string.
 *
 * @param effort - Effort estimate from backend
 * @returns Formatted time string, or undefined
 *
 * @example
 * formatEffortTime({ level: "low", estimate_hours: 0.5 }) // "0.5h"
 * formatEffortTime({ level: "medium" }) // undefined
 */
export function formatEffortTime(
  effort: Finding["effort"] | undefined | null
): string | undefined {
  // Handle missing effort estimate - defensive for different report types
  if (!effort) {
    return undefined;
  }
  if (effort.estimate_hours !== null && effort.estimate_hours !== undefined) {
    return `${effort.estimate_hours}h`;
  }
  return undefined;
}

/**
 * Transform backend findings to frontend recommendation format.
 *
 * Maps the detailed backend Finding structure to the simplified
 * RecommendationItem format expected by UI components.
 *
 * @param findings - Array of findings from backend report
 * @returns Array of recommendations for frontend display
 *
 * @example
 * const findings = [
 *   {
 *     id: "finding_1",
 *     title: "Add partition filter",
 *     recommendation: "Query scans entire table...",
 *     category: "QUERY",
 *     impact_estimate: { query_time_pct: 25, confidence: "high" },
 *     effort: { level: "low", estimate_hours: 0.5 },
 *     fixes: [{ type: "SQL_REWRITE", snippet: "WHERE date = ..." }],
 *     rank: 1
 *   }
 * ];
 *
 * const recommendations = mapFindingsToRecommendations(findings);
 * // [{ id: "finding_1", title: "Add partition filter", impact: "high", ... }]
 */
export function mapFindingsToRecommendations(
  findings: Finding[]
): RecommendationItem[] {
  if (!findings || !Array.isArray(findings)) {
    return [];
  }

  return findings.map((finding) => ({
    id: finding.id || `finding_${Math.random().toString(36).slice(2, 9)}`,
    title: finding.title || "Recommendation",
    description: finding.recommendation || "",
    explanation: finding.recommendation || "",
    impact: convertImpactEstimate(finding.impact_estimate),
    effort: finding.effort?.level || "medium",
    category: formatCategory(finding.category || "GENERAL"),
    sql_suggestion: extractSQLFromFixes(finding.fixes),
    estimated_improvement: formatImpactPercentage(finding.impact_estimate),
    estimated_time: formatEffortTime(finding.effort),
  }));
}

/**
 * Check if a report has recommendations that can be displayed.
 *
 * @param report - Report object from backend
 * @returns True if report has findings array
 */
export function hasRecommendations(report: unknown): boolean {
  if (!report || typeof report !== "object") return false;

  const analysis = (report as Record<string, unknown>).analysis;
  if (!analysis || typeof analysis !== "object") return false;

  const findings = (analysis as Record<string, unknown>).findings;
  return Array.isArray(findings) && findings.length > 0;
}

/**
 * Extract findings array from report object.
 *
 * Handles both flat and nested report structures.
 *
 * @param report - Report object from backend
 * @returns Findings array, or empty array if not found
 */
export function extractFindings(report: unknown): Finding[] {
  if (!report || typeof report !== "object") return [];

  const reportObj = report as Record<string, unknown>;

  // Try nested structure: report.analysis.findings
  const analysis = reportObj.analysis;
  if (analysis && typeof analysis === "object") {
    const findings = (analysis as Record<string, unknown>).findings;
    if (Array.isArray(findings)) {
      return findings as Finding[];
    }
  }

  // Try flat structure: report.findings
  if (Array.isArray(reportObj.findings)) {
    return reportObj.findings as Finding[];
  }

  return [];
}

