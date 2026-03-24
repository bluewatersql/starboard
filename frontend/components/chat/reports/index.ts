/**
 * Specialized report bubble components and shared report UI.
 */

// Report bubble components
export { AnalyticsReportBubble } from "./AnalyticsReportBubble";
export { AdvisorReportBubble } from "./AdvisorReportBubble";
export { WarehouseReportBubble } from "./WarehouseReportBubble";
export { DiagnosticReportBubble } from "./DiagnosticReportBubble";
/** @deprecated Use WarehouseReportBubble instead */
export { WarehouseReportBubble as ComputeReportBubble } from "./WarehouseReportBubble";

// Report structure components
export { ImpactBadge, type ImpactLevel } from "./ImpactBadge";
export { EffortBadge, type EffortLevel } from "./EffortBadge";
export { RecommendationCard, type RecommendationItem } from "./RecommendationCard";
export { ReportSection, type ReportSectionData, type SeverityLevel } from "./ReportSection";
export { ReportSummary, type ReportSummaryMetadata } from "./ReportSummary";
export { ImplementationPlan } from "./ImplementationPlan";
export { FindingCard } from "./FindingCard";

// Loading states
export { ReportSkeleton } from "./ReportSkeleton";

