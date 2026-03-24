/**
 * Grouped conversations component.
 *
 * Groups conversations by time period (Today, Yesterday, This Week, etc.)
 * with collapsible sections.
 */

"use client";

import React, { useMemo, useState } from "react";
import { Box, Typography, Collapse, IconButton } from "@mui/material";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import ExpandLessIcon from "@mui/icons-material/ExpandLess";
import { useTheme } from "@mui/material/styles";
import { ConversationItemEnhanced } from "./ConversationItemEnhanced";
import type { Conversation } from "@/lib/types/api";

interface GroupedConversationsProps {
  /** Conversations to group and display */
  conversations: Conversation[];
  /** Currently active conversation ID */
  currentConversationId?: string;
}

type TimeGroup = "Today" | "Yesterday" | "This Week" | "This Month" | "Older";

/**
 * Check if a date is today.
 */
function isToday(date: Date): boolean {
  const today = new Date();
  return (
    date.getDate() === today.getDate() &&
    date.getMonth() === today.getMonth() &&
    date.getFullYear() === today.getFullYear()
  );
}

/**
 * Check if a date is yesterday.
 */
function isYesterday(date: Date): boolean {
  const yesterday = new Date();
  yesterday.setDate(yesterday.getDate() - 1);
  return (
    date.getDate() === yesterday.getDate() &&
    date.getMonth() === yesterday.getMonth() &&
    date.getFullYear() === yesterday.getFullYear()
  );
}

/**
 * Check if a date is within this week.
 */
function isThisWeek(date: Date): boolean {
  const now = new Date();
  const startOfWeek = new Date(now);
  startOfWeek.setDate(now.getDate() - now.getDay());
  startOfWeek.setHours(0, 0, 0, 0);
  return date >= startOfWeek && !isToday(date) && !isYesterday(date);
}

/**
 * Check if a date is within this month.
 */
function isThisMonth(date: Date): boolean {
  const now = new Date();
  return (
    date.getMonth() === now.getMonth() &&
    date.getFullYear() === now.getFullYear() &&
    !isThisWeek(date) &&
    !isYesterday(date) &&
    !isToday(date)
  );
}

/**
 * Get the time group for a date.
 */
function getTimeGroup(date: Date): TimeGroup {
  if (isToday(date)) return "Today";
  if (isYesterday(date)) return "Yesterday";
  if (isThisWeek(date)) return "This Week";
  if (isThisMonth(date)) return "This Month";
  return "Older";
}

/**
 * Group conversations by time period.
 */
function groupConversations(
  conversations: Conversation[]
): Array<[TimeGroup, Conversation[]]> {
  const groups: Record<TimeGroup, Conversation[]> = {
    Today: [],
    Yesterday: [],
    "This Week": [],
    "This Month": [],
    Older: [],
  };

  conversations.forEach((conv) => {
    const date = new Date(conv.updated_at || conv.created_at);
    const group = getTimeGroup(date);
    groups[group].push(conv);
  });

  // Return only non-empty groups, in order
  const orderedGroups: TimeGroup[] = [
    "Today",
    "Yesterday",
    "This Week",
    "This Month",
    "Older",
  ];
  return orderedGroups
    .filter((group) => groups[group].length > 0)
    .map((group) => [group, groups[group]]);
}

/**
 * Grouped conversations list.
 *
 * @example
 * ```tsx
 * <GroupedConversations
 *   conversations={filteredConversations}
 *   currentConversationId={activeId}
 * />
 * ```
 */
export function GroupedConversations({
  conversations,
  currentConversationId,
}: GroupedConversationsProps) {
  const grouped = useMemo(
    () => groupConversations(conversations),
    [conversations]
  );

  if (conversations.length === 0) {
    return (
      <Box sx={{ p: 4, textAlign: "center" }}>
        <Typography variant="body2" color="text.secondary">
          No conversations found
        </Typography>
      </Box>
    );
  }

  return (
    <Box sx={{ px: 1 }}>
      {grouped.map(([groupName, items]) => (
        <ConversationGroup
          key={groupName}
          name={groupName}
          conversations={items}
          currentConversationId={currentConversationId}
          defaultExpanded={groupName === "Today" || groupName === "Yesterday"}
        />
      ))}
    </Box>
  );
}

interface ConversationGroupProps {
  name: TimeGroup;
  conversations: Conversation[];
  currentConversationId?: string;
  defaultExpanded?: boolean;
}

/**
 * Single conversation group with collapsible header.
 */
function ConversationGroup({
  name,
  conversations,
  currentConversationId,
  defaultExpanded = true,
}: ConversationGroupProps) {
  const theme = useTheme();
  const isDark = theme.palette.mode === "dark";
  const [isExpanded, setIsExpanded] = useState(defaultExpanded);

  return (
    <Box sx={{ mb: 2 }}>
      {/* Group Header */}
      <Box
        onClick={() => setIsExpanded(!isExpanded)}
        sx={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          px: 1.5,
          py: 1,
          cursor: "pointer",
          borderRadius: 1,
          "&:hover": {
            bgcolor: isDark
              ? "rgba(255,255,255,0.03)"
              : "rgba(0,0,0,0.02)",
          },
        }}
        role="button"
        tabIndex={0}
        aria-expanded={isExpanded}
        aria-controls={`group-${name}`}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            setIsExpanded(!isExpanded);
          }
        }}
      >
        <Typography
          variant="caption"
          sx={{
            fontWeight: 600,
            textTransform: "uppercase",
            letterSpacing: "0.05em",
            color: "text.secondary",
          }}
        >
          {name} ({conversations.length})
        </Typography>
        <IconButton size="small" sx={{ p: 0.25 }} tabIndex={-1}>
          {isExpanded ? (
            <ExpandLessIcon sx={{ fontSize: 18 }} />
          ) : (
            <ExpandMoreIcon sx={{ fontSize: 18 }} />
          )}
        </IconButton>
      </Box>

      {/* Group Items */}
      <Collapse in={isExpanded} id={`group-${name}`}>
        <Box sx={{ display: "flex", flexDirection: "column", gap: 1, px: 0.5 }}>
          {conversations.map((conv) => (
            <ConversationItemEnhanced
              key={conv.conversation_id}
              conversation={conv}
              isActive={conv.conversation_id === currentConversationId}
            />
          ))}
        </Box>
      </Collapse>
    </Box>
  );
}

export default GroupedConversations;

