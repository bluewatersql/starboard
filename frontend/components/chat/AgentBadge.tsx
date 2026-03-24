"use client";

import { Box, Tooltip } from "@mui/material";
import QueryStatsIcon from "@mui/icons-material/QueryStats";
import WorkIcon from "@mui/icons-material/Work";
import TableChartIcon from "@mui/icons-material/TableChart";
import BugReportIcon from "@mui/icons-material/BugReport";
import MemoryIcon from "@mui/icons-material/Memory";
import SmartToyIcon from "@mui/icons-material/SmartToy";
import RouteIcon from "@mui/icons-material/Route";
import StorageIcon from "@mui/icons-material/Storage";
import AccountBalanceIcon from "@mui/icons-material/AccountBalance";
import HealthAndSafetyIcon from "@mui/icons-material/HealthAndSafety";
import HubIcon from "@mui/icons-material/Hub";
import type { AgentType } from "@/lib/types/extended-api";
import type { SvgIconComponent } from "@mui/icons-material";

/**
 * Agent configuration for visual display.
 */
interface AgentConfig {
  icon: SvgIconComponent;
  color: string;
  name: string;
  description: string;
}

/**
 * Agent configuration mapping.
 * Maps agent types to their visual representation.
 */
const AGENT_CONFIG: Record<AgentType, AgentConfig> = {
  router: {
    icon: RouteIcon,
    color: "#6366f1", // Indigo
    name: "Router",
    description: "Routes your query to the most appropriate specialist",
  },
  query: {
    icon: QueryStatsIcon,
    color: "#3b82f6", // Blue
    name: "Query Expert",
    description: "Optimizes SQL queries and analyzes execution plans",
  },
  job: {
    icon: WorkIcon,
    color: "#22c55e", // Green
    name: "Job Expert",
    description: "Analyzes Databricks jobs and provides performance recommendations",
  },
  table: {
    icon: TableChartIcon,
    color: "#a855f7", // Purple
    name: "Table Expert",
    description: "Manages table metadata, schemas, and lineage",
  },
  uc: {
    icon: HubIcon,
    color: "#8b5cf6", // Violet
    name: "Unity Catalog Expert",
    description: "Manages metadata, lineage, governance, and storage optimization",
  },
  warehouse: {
    icon: StorageIcon,
    color: "#06b6d4", // Cyan
    name: "Warehouse Expert",
    description: "Analyzes SQL warehouse performance and health",
  },
  analytics: {
    icon: AccountBalanceIcon,
    color: "#10b981", // Emerald
    name: "FinOps Expert",
    description: "Analyzes costs, billing, and usage trends",
  },
  diagnostic: {
    icon: BugReportIcon,
    color: "#f59e0b", // Amber
    name: "Diagnostic Expert",
    description: "Troubleshoots errors and diagnoses issues",
  },
  cluster: {
    icon: MemoryIcon,
    color: "#ec4899", // Pink
    name: "Cluster Expert",
    description: "Analyzes Databricks cluster configurations",
  },
  compute: {
    icon: MemoryIcon,
    color: "#ec4899", // Pink (legacy - kept for backward compatibility)
    name: "Compute Expert",
    description: "Analyzes cluster and warehouse configurations",
  },
  discovery: {
    icon: HealthAndSafetyIcon,
    color: "#14b8a6", // Teal
    name: "Discovery Expert",
    description: "Runs workspace health assessments and produces graded reports",
  },
  general: {
    icon: SmartToyIcon,
    color: "#64748b", // Slate
    name: "Assistant",
    description: "General purpose AI assistant",
  },
};

export interface AgentBadgeProps {
  /** Agent type to display */
  agentType: AgentType;
  /** Badge size variant */
  size?: "small" | "medium";
}

/**
 * AgentBadge - Displays a badge indicating which agent is responding.
 * 
 * Shows an icon badge with tooltip containing agent name and description.
 * Positioned as an overlay on the avatar in MessageBubble.
 * 
 * @example
 * ```tsx
 * <AgentBadge agentType="query" size="small" />
 * ```
 */
export function AgentBadge({ agentType, size = "small" }: AgentBadgeProps) {
  const config = AGENT_CONFIG[agentType] || AGENT_CONFIG.general;
  const AgentIcon = config.icon;
  
  const dimensions = size === "small" ? 18 : 24;
  const iconSize = size === "small" ? 12 : 16;
  
  return (
    <Tooltip 
      title={
        <Box sx={{ textAlign: "center" }}>
          <Box sx={{ fontWeight: 600, mb: 0.5 }}>{config.name}</Box>
          <Box sx={{ fontSize: "0.75rem", opacity: 0.9 }}>{config.description}</Box>
        </Box>
      }
      placement="top"
      arrow
    >
      <Box
        role="img"
        aria-label={`${config.name} responding`}
        sx={{
          position: "absolute",
          bottom: -4,
          right: -4,
          width: dimensions,
          height: dimensions,
          borderRadius: "50%",
          bgcolor: config.color,
          border: 2,
          borderColor: "background.paper",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          color: "white",
          zIndex: 1,
          cursor: "help",
          transition: "transform 0.15s ease-in-out",
          "&:hover": {
            transform: "scale(1.1)",
          },
        }}
      >
        <AgentIcon sx={{ fontSize: iconSize }} />
      </Box>
    </Tooltip>
  );
}

/**
 * Get agent display name for UI.
 */
export function getAgentName(agentType: AgentType): string {
  return AGENT_CONFIG[agentType]?.name || AGENT_CONFIG.general.name;
}

/**
 * Get agent color for UI.
 */
export function getAgentColor(agentType: AgentType): string {
  return AGENT_CONFIG[agentType]?.color || AGENT_CONFIG.general.color;
}

/**
 * Get agent icon component for UI.
 * Used by both AgentBadge and ConversationItemEnhanced.
 */
export function getAgentIcon(agentType: AgentType): SvgIconComponent {
  return AGENT_CONFIG[agentType]?.icon || AGENT_CONFIG.general.icon;
}

/**
 * Export AGENT_CONFIG for reuse in other components.
 */
export { AGENT_CONFIG };

export default AgentBadge;
