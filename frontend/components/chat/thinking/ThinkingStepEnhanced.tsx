/**
 * Enhanced thinking step component.
 *
 * Displays a single thinking step with status icon, progress bar,
 * duration, and expandable sub-tasks with metrics.
 */

"use client";

import React, { useState } from "react";
import {
  Box,
  Typography,
  IconButton,
  Collapse,
  LinearProgress,
  Accordion,
  AccordionSummary,
  AccordionDetails,
} from "@mui/material";
import CheckCircleIcon from "@mui/icons-material/CheckCircle";
import ErrorIcon from "@mui/icons-material/Error";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import ExpandLessIcon from "@mui/icons-material/ExpandLess";
import RadioButtonUncheckedIcon from "@mui/icons-material/RadioButtonUnchecked";
import SearchIcon from "@mui/icons-material/Search";
import BarChartIcon from "@mui/icons-material/BarChart";
import TableChartIcon from "@mui/icons-material/TableChart";
import ScienceIcon from "@mui/icons-material/Science";
import DescriptionIcon from "@mui/icons-material/Description";
import AccessTimeIcon from "@mui/icons-material/AccessTime";
import CodeIcon from "@mui/icons-material/Code";
import { useTheme } from "@mui/material/styles";
import type { SvgIconComponent } from "@mui/icons-material";

export type StepStatus = "pending" | "in_progress" | "completed" | "failed";

export interface SubTask {
  /** Unique identifier */
  id: string;
  /** Description of the sub-task */
  description: string;
  /** Current status */
  status: StepStatus;
  /** Optional value/metric (e.g., "342 nodes", "10 shuffles") */
  value?: string | number;
}

/**
 * Call details for accordion expansion (U3 enhancement).
 */
export interface ToolCallDetails {
  /** Tool function name */
  toolName: string;
  /** Input parameters (JSON-serializable) */
  parameters?: Record<string, unknown>;
  /** Output response (JSON-serializable, may be truncated) */
  response?: unknown;
  /** Whether response is truncated */
  responseIsTruncated?: boolean;
  /** Error message if failed */
  error?: string;
}

export interface ThinkingStep {
  /** Unique step identifier */
  id: string;
  /** Step title */
  title: string;
  /** Current status */
  status: StepStatus;
  /** Start timestamp (ms) */
  startTime?: number;
  /** End timestamp (ms) */
  endTime?: number;
  /** Progress percentage (0-100) for in_progress steps */
  progress?: number;
  /** Step type for icon mapping */
  stepType?: string;
  /** Sub-tasks with details */
  subTasks?: SubTask[];
  /** Additional metadata */
  metadata?: Record<string, unknown>;
  /** Call details for accordion expansion (U3) */
  callDetails?: ToolCallDetails;
}

interface ThinkingStepEnhancedProps {
  /** The thinking step to display */
  step: ThinkingStep;
  /** Initial expanded state */
  defaultExpanded?: boolean;
  /** Callback when expand state changes */
  onToggleExpand?: (stepId: string, expanded: boolean) => void;
}

// Map step types to icons
const STEP_ICONS: Record<string, SvgIconComponent> = {
  resolving_query: SearchIcon,
  resolve_query: SearchIcon,
  analyzing_plan: BarChartIcon,
  analyze_query_plan: BarChartIcon,
  discovering_tables: TableChartIcon,
  discover_tables: TableChartIcon,
  fetching_metadata: TableChartIcon,
  get_table_metadata: TableChartIcon,
  generating_recommendations: ScienceIcon,
  formatting_report: DescriptionIcon,
};

/**
 * Get icon component for a step type.
 */
function getStepIcon(stepType?: string): SvgIconComponent {
  if (!stepType) return ScienceIcon;
  return STEP_ICONS[stepType] || ScienceIcon;
}

/**
 * Format duration in seconds.
 */
function formatDuration(startTime?: number, endTime?: number): string | null {
  if (!startTime || !endTime) return null;
  const duration = (endTime - startTime) / 1000;
  return duration.toFixed(2);
}

/**
 * Enhanced thinking step with progress bar, duration, and expandable sub-tasks.
 *
 * @example
 * ```tsx
 * <ThinkingStepEnhanced
 *   step={{
 *     id: "resolve_query",
 *     title: "Resolving Query",
 *     status: "completed",
 *     startTime: 1000,
 *     endTime: 2500,
 *     subTasks: [
 *       { id: "1", description: "Retrieved SQL", status: "completed", value: "1,247 lines" }
 *     ]
 *   }}
 * />
 * ```
 */
export function ThinkingStepEnhanced({
  step,
  defaultExpanded = false,
  onToggleExpand,
}: ThinkingStepEnhancedProps) {
  const theme = useTheme();
  const isDark = theme.palette.mode === "dark";
  const [expanded, setExpanded] = useState(defaultExpanded);

  const duration = formatDuration(step.startTime, step.endTime);
  const hasSubTasks = step.subTasks && step.subTasks.length > 0;
  const hasCallDetails = !!step.callDetails;
  const hasExpandableContent = hasSubTasks || hasCallDetails;
  // Get icon once outside render to avoid creating component during render
  const stepIcon = step.stepType;

  const handleToggle = () => {
    const newExpanded = !expanded;
    setExpanded(newExpanded);
    onToggleExpand?.(step.id, newExpanded);
  };

  return (
    <Box
      sx={{
        py: 1.5,
        animation: "slideInFromLeft 300ms ease-out",
        "@keyframes slideInFromLeft": {
          from: { opacity: 0, transform: "translateX(-20px)" },
          to: { opacity: 1, transform: "translateX(0)" },
        },
      }}
      role="listitem"
      aria-label={`${step.title}: ${step.status}`}
    >
      {/* Main Step Row */}
      <Box sx={{ display: "flex", alignItems: "flex-start", gap: 1.5 }}>
        {/* Status Icon */}
        <Box sx={{ flexShrink: 0, mt: 0.25 }}>
          {step.status === "completed" && (
            <CheckCircleIcon
              sx={{ fontSize: 20, color: "success.main" }}
              aria-label="Completed"
            />
          )}
          {step.status === "in_progress" && (
            <AccessTimeIcon
              sx={{
                fontSize: 20,
                color: "primary.main",
                animation: "pulse 1.5s infinite",
                "@keyframes pulse": {
                  "0%, 100%": { opacity: 1 },
                  "50%": { opacity: 0.5 },
                },
              }}
              aria-label="In progress"
            />
          )}
          {step.status === "failed" && (
            <ErrorIcon
              sx={{ fontSize: 20, color: "error.main" }}
              aria-label="Failed"
            />
          )}
          {step.status === "pending" && (
            <RadioButtonUncheckedIcon
              sx={{ fontSize: 20, color: "text.disabled" }}
              aria-label="Pending"
            />
          )}
        </Box>

        {/* Step Icon */}
        <Box sx={{ flexShrink: 0, mt: 0.25 }}>
          {React.createElement(getStepIcon(stepIcon), { fontSize: "small" })}
        </Box>

        {/* Content */}
        <Box sx={{ flex: 1, minWidth: 0 }}>
          {/* Title Row */}
          <Box
            sx={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              gap: 2,
            }}
          >
            <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
              <Typography
                variant="body2"
                sx={{
                  fontWeight: 500,
                  color:
                    step.status === "completed"
                      ? "text.primary"
                      : step.status === "in_progress"
                        ? "primary.main"
                        : step.status === "failed"
                          ? "error.main"
                          : "text.secondary",
                }}
              >
                {step.title}
              </Typography>

              {/* Expand/Collapse Button */}
              {hasExpandableContent && (
                <IconButton
                  size="small"
                  onClick={handleToggle}
                  aria-label={expanded ? "Collapse details" : "Expand details"}
                  sx={{ p: 0.25 }}
                >
                  {expanded ? (
                    <ExpandLessIcon sx={{ fontSize: 18 }} />
                  ) : (
                    <ExpandMoreIcon sx={{ fontSize: 18 }} />
                  )}
                </IconButton>
              )}
            </Box>

            {/* Duration/Status */}
            <Box sx={{ display: "flex", alignItems: "center", gap: 1, flexShrink: 0 }}>
              {duration && step.status === "completed" && (
                <Typography
                  variant="caption"
                  sx={{
                    fontFamily: "monospace",
                    color: "text.secondary",
                  }}
                >
                  {duration}s
                </Typography>
              )}

              {step.status === "in_progress" && (
                <Typography
                  variant="caption"
                  sx={{
                    color: "primary.main",
                    fontWeight: 500,
                    animation: "pulse 1.5s infinite",
                  }}
                >
                  Processing
                </Typography>
              )}

              {step.status === "failed" && (
                <Typography
                  variant="caption"
                  sx={{ color: "error.main", fontWeight: 500 }}
                >
                  Failed
                </Typography>
              )}
            </Box>
          </Box>

          {/* Progress Bar - Show indeterminate progress when in_progress */}
          {step.status === "in_progress" && (
            <Box sx={{ mt: 1 }}>
              <LinearProgress
                variant="indeterminate"
                sx={{
                  height: 4,
                  borderRadius: 2,
                  backgroundColor: isDark
                    ? "rgba(255,255,255,0.1)"
                    : "rgba(0,0,0,0.08)",
                }}
              />
            </Box>
          )}

          {/* Sub-tasks and Call Details */}
          <Collapse in={expanded && (hasSubTasks || !!step.callDetails)}>
            <Box
              sx={{
                mt: 1.5,
                ml: 2,
                pl: 2,
                borderLeft: 2,
                borderColor: isDark
                  ? "rgba(255,255,255,0.1)"
                  : "rgba(0,0,0,0.08)",
              }}
            >
              {step.subTasks?.map((subTask) => (
                <SubTaskItem key={subTask.id} subTask={subTask} />
              ))}
              
              {/* U3: Call Details Accordion */}
              {step.callDetails && (
                <CallDetailsAccordion details={step.callDetails} isDark={isDark} />
              )}
            </Box>
          </Collapse>
        </Box>
      </Box>

      {/* Screen reader announcement for completion */}
      {step.status === "completed" && duration && (
        <Box
          component="span"
          sx={{
            position: "absolute",
            width: 1,
            height: 1,
            padding: 0,
            margin: -1,
            overflow: "hidden",
            clip: "rect(0, 0, 0, 0)",
            whiteSpace: "nowrap",
            border: 0,
          }}
          role="status"
          aria-live="polite"
        >
          {step.title} completed in {duration} seconds
        </Box>
      )}
    </Box>
  );
}

/**
 * Sub-task item within a thinking step.
 */
function SubTaskItem({ subTask }: { subTask: SubTask }) {
  return (
    <Box
      sx={{
        display: "flex",
        alignItems: "flex-start",
        gap: 1,
        py: 0.5,
      }}
    >
      {/* Status indicator */}
      <Typography
        component="span"
        sx={{
          flexShrink: 0,
          fontSize: "0.75rem",
          lineHeight: 1.6,
        }}
      >
        {subTask.status === "completed" && (
          <Box component="span" sx={{ color: "success.main" }}>
            ✓
          </Box>
        )}
        {subTask.status === "in_progress" && (
          <Box
            component="span"
            sx={{
              color: "primary.main",
              animation: "pulse 1.5s infinite",
            }}
          >
            ●
          </Box>
        )}
        {subTask.status === "failed" && (
          <Box component="span" sx={{ color: "error.main" }}>
            ✗
          </Box>
        )}
        {subTask.status === "pending" && (
          <Box component="span" sx={{ color: "text.disabled" }}>
            ○
          </Box>
        )}
      </Typography>

      {/* Description */}
      <Typography
        variant="caption"
        sx={{ flex: 1, color: "text.secondary", lineHeight: 1.6 }}
      >
        {subTask.description}
      </Typography>

      {/* Value/Metric */}
      {subTask.value !== undefined && (
        <Typography
          variant="caption"
          sx={{
            fontFamily: "monospace",
            fontWeight: 500,
            color: "text.primary",
            flexShrink: 0,
          }}
        >
          {subTask.value}
        </Typography>
      )}
    </Box>
  );
}

/**
 * U3: Call details accordion for showing parameters and response.
 */
function CallDetailsAccordion({
  details,
  isDark,
}: {
  details: ToolCallDetails;
  isDark: boolean;
}) {
  return (
    <Accordion
      elevation={0}
      sx={{
        mt: 1,
        bgcolor: isDark ? "rgba(255,255,255,0.03)" : "rgba(0,0,0,0.02)",
        "&:before": { display: "none" },
        borderRadius: 1,
      }}
    >
      <AccordionSummary
        expandIcon={<ExpandMoreIcon sx={{ fontSize: 16 }} />}
        sx={{
          minHeight: 36,
          py: 0,
          "& .MuiAccordionSummary-content": { my: 0.5 },
        }}
      >
        <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
          <CodeIcon sx={{ fontSize: 14, color: "text.secondary" }} />
          <Typography
            variant="caption"
            sx={{ fontFamily: "monospace", color: "text.secondary" }}
          >
            Call Details
          </Typography>
        </Box>
      </AccordionSummary>
      <AccordionDetails sx={{ p: 1.5, pt: 0 }}>
        <Box sx={{ fontFamily: "monospace", fontSize: "0.72rem" }}>
          {/* Parameters */}
          {details.parameters && Object.keys(details.parameters).length > 0 && (
            <Box sx={{ mb: 1.5 }}>
              <Typography
                variant="caption"
                sx={{
                  fontWeight: 600,
                  color: "text.secondary",
                  display: "block",
                  mb: 0.5,
                  fontFamily: "inherit",
                }}
              >
                Parameters
              </Typography>
              <Box
                component="pre"
                sx={{
                  m: 0,
                  p: 1,
                  bgcolor: isDark ? "rgba(0,0,0,0.2)" : "rgba(0,0,0,0.04)",
                  borderRadius: 1,
                  overflow: "auto",
                  maxHeight: 150,
                  whiteSpace: "pre-wrap",
                  wordBreak: "break-word",
                  fontSize: "inherit",
                }}
              >
                {JSON.stringify(details.parameters, null, 2)}
              </Box>
            </Box>
          )}

          {/* Response */}
          {details.response !== undefined && (
            <Box>
              <Typography
                variant="caption"
                sx={{
                  fontWeight: 600,
                  color: "text.secondary",
                  display: "block",
                  mb: 0.5,
                  fontFamily: "inherit",
                }}
              >
                Response
                {details.responseIsTruncated && (
                  <Typography
                    component="span"
                    variant="caption"
                    sx={{ ml: 1, fontStyle: "italic" }}
                  >
                    (truncated)
                  </Typography>
                )}
              </Typography>
              <Box
                component="pre"
                sx={{
                  m: 0,
                  p: 1,
                  bgcolor: isDark ? "rgba(0,0,0,0.2)" : "rgba(0,0,0,0.04)",
                  borderRadius: 1,
                  overflow: "auto",
                  maxHeight: 200,
                  whiteSpace: "pre-wrap",
                  wordBreak: "break-word",
                  fontSize: "inherit",
                }}
              >
                {typeof details.response === "string"
                  ? details.response
                  : JSON.stringify(details.response, null, 2)}
              </Box>
            </Box>
          )}

          {/* Error */}
          {details.error && (
            <Box
              sx={{
                mt: 1,
                p: 1,
                bgcolor: "error.light",
                color: "error.contrastText",
                borderRadius: 1,
                fontSize: "0.75rem",
              }}
            >
              {details.error}
            </Box>
          )}
        </Box>
      </AccordionDetails>
    </Accordion>
  );
}

export default ThinkingStepEnhanced;

