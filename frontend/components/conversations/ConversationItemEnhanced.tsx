/**
 * Enhanced conversation item component.
 *
 * Displays a conversation with rich metadata including recommendations count,
 * improvement estimates, status indicator, and relative time.
 * Uses optimistic delete for immediate UI feedback.
 */

"use client";

import React, { useState, useRef } from "react";
import {
  Box,
  Paper,
  Typography,
  IconButton,
  LinearProgress,
  Chip,
  Tooltip,
} from "@mui/material";
import DeleteIcon from "@mui/icons-material/Delete";
import ChatBubbleOutlineIcon from "@mui/icons-material/ChatBubbleOutline";
import CheckCircleIcon from "@mui/icons-material/CheckCircle";
import ErrorIcon from "@mui/icons-material/Error";
import AccessTimeIcon from "@mui/icons-material/AccessTime";
import { useTheme } from "@mui/material/styles";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api/client";
import { useConversationStore } from "@/lib/store/conversationStore";
import { useMessageStore } from "@/lib/store/messageStore";
import { useUIStore } from "@/lib/store/uiStore";
import type { Conversation, Message, AgentType } from "@/lib/types/api";
import { getAgentIcon as getAgentIconComponent, getAgentColor } from "@/components/chat/AgentBadge";
import { useConfirmation } from "@/lib/hooks/useConfirmation";
import { ConfirmationDialog } from "@/components/common/ConfirmationDialog";

export interface ConversationMetadata {
  recommendations_count?: number;
  estimated_improvement?: string;
  cost_reduction?: string;
  status?: "active" | "completed" | "error";
  query_id?: string;
  /** Agent type - supports all domain agents including diagnostic, query, job, etc. */
  agent_type?: AgentType;
}

interface ConversationItemEnhancedProps {
  /** Conversation data */
  conversation: Conversation;
  /** Whether this conversation is currently active */
  isActive: boolean;
}

/**
 * Format relative time (e.g., "2 hours ago", "yesterday").
 */
function formatRelativeTime(date: Date): string {
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMs / 3600000);
  const diffDays = Math.floor(diffMs / 86400000);

  if (diffMins < 1) return "just now";
  if (diffMins < 60) return `${diffMins} min ago`;
  if (diffHours < 24) return `${diffHours} hour${diffHours > 1 ? "s" : ""} ago`;
  if (diffDays === 1) return "yesterday";
  if (diffDays < 7) return `${diffDays} days ago`;

  return date.toLocaleDateString([], { month: "short", day: "numeric" });
}

/**
 * Get icon for agent type.
 * Uses shared AGENT_CONFIG from AgentBadge for consistency across all agent types.
 */
function getAgentIcon(agentType?: AgentType) {
  if (!agentType) {
    return <ChatBubbleOutlineIcon sx={{ fontSize: 16, color: "text.secondary" }} />;
  }
  
  const IconComponent = getAgentIconComponent(agentType);
  const color = getAgentColor(agentType);
  
  return <IconComponent sx={{ fontSize: 16, color }} />;
}

/**
 * Get status icon.
 */
function getStatusIcon(status?: string) {
  switch (status) {
    case "completed":
      return (
        <Tooltip title="Analysis complete">
          <CheckCircleIcon sx={{ fontSize: 16, color: "success.main" }} />
        </Tooltip>
      );
    case "error":
      return (
        <Tooltip title="Error occurred">
          <ErrorIcon sx={{ fontSize: 16, color: "error.main" }} />
        </Tooltip>
      );
    case "active":
      return (
        <Tooltip title="In progress">
          <Box
            sx={{
              width: 8,
              height: 8,
              borderRadius: "50%",
              bgcolor: "primary.main",
              animation: "pulse 1.5s infinite",
              "@keyframes pulse": {
                "0%, 100%": { opacity: 1 },
                "50%": { opacity: 0.5 },
              },
            }}
          />
        </Tooltip>
      );
    default:
      return null;
  }
}

/**
 * Enhanced conversation item with metadata display.
 *
 * @example
 * ```tsx
 * <ConversationItemEnhanced
 *   conversation={conv}
 *   isActive={conv.id === activeId}
 * />
 * ```
 */
export function ConversationItemEnhanced({
  conversation,
  isActive,
}: ConversationItemEnhancedProps) {
  const theme = useTheme();
  const isDark = theme.palette.mode === "dark";
  const router = useRouter();
  const queryClient = useQueryClient();
  const [isHovered, setIsHovered] = useState(false);
  const { confirm, dialogProps } = useConfirmation();

  const setActiveConversation = useConversationStore((s) => s.setActiveConversation);
  const removeConversation = useConversationStore((s) => s.removeConversation);
  const addConversation = useConversationStore((s) => s.addConversation);
  const addNotification = useUIStore((s) => s.addNotification);
  const clearMessages = useMessageStore((s) => s.clearMessages);
  const messagesByConversation = useMessageStore((s) => s.messagesByConversation);

  // Store snapshots for potential rollback
  const snapshotRef = useRef<{
    conversation: Conversation;
    messages: Message[];
  } | null>(null);

  // Extract metadata
  const metadata = (conversation.metadata || {}) as ConversationMetadata;
  const timeAgo = formatRelativeTime(new Date(conversation.updated_at || conversation.created_at));

  // Delete mutation with optimistic update
  const deleteMutation = useMutation({
    mutationFn: async () => {
      try {
        await api.deleteConversation(conversation.conversation_id);
      } catch (error) {
        if (error instanceof Error && error.message.includes("not found")) {
          return;
        }
        throw error;
      }
    },
    
    // Optimistic update: Remove from UI immediately
    onMutate: async () => {
      const conversationId = conversation.conversation_id;
      
      // Cancel any outgoing refetches to prevent overwriting optimistic update
      await queryClient.cancelQueries({ queryKey: ["conversations"] });
      
      // Snapshot current state for potential rollback
      snapshotRef.current = {
        conversation: conversation,
        messages: messagesByConversation[conversationId] || [],
      };
      
      // Optimistically remove from store (instant UI update)
      clearMessages(conversationId);
      removeConversation(conversationId);
      
      // Optimistically update React Query cache
      queryClient.setQueryData<Conversation[]>(
        ["conversations"],
        (old) => old?.filter((c) => c.conversation_id !== conversationId) ?? []
      );
      
      // If this was the active conversation, navigate away to home
      if (isActive) {
        router.push("/");
      }
    },
    
    onSuccess: () => {
      // API confirmed deletion - show success toast
      snapshotRef.current = null; // Clear snapshot, no rollback needed
      addNotification({
        message: "Conversation deleted",
        type: "success",
        duration: 3000,
      });
    },
    
    onError: (error) => {
      console.error("Failed to delete conversation:", error);
      
      // Rollback optimistic update
      if (snapshotRef.current) {
        const { conversation: deletedConv, messages } = snapshotRef.current;
        
        // Restore to Zustand store
        addConversation(deletedConv);
        
        // Restore messages if any
        if (messages.length > 0) {
          useMessageStore.getState().setMessages(
            deletedConv.conversation_id,
            messages
          );
        }
        
        // Restore React Query cache
        queryClient.setQueryData<Conversation[]>(
          ["conversations"],
          (old) => {
            if (!old) return [deletedConv];
            // Add back in correct position (by created_at)
            const updated = [...old, deletedConv];
            return updated.sort(
              (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
            );
          }
        );
        
        snapshotRef.current = null;
      }
      
      addNotification({
        message:
          error instanceof Error
            ? `Delete failed: ${error.message}`
            : "Failed to delete conversation. Please try again.",
        type: "error",
        duration: 5000,
      });
    },
    
    onSettled: () => {
      // Always refetch after error or success to ensure sync with server
      queryClient.invalidateQueries({ queryKey: ["conversations"] });
    },
  });

  const handleClick = () => {
    setActiveConversation(conversation.conversation_id);
    // Using query params for static export compatibility
    router.push(`/chat?id=${conversation.conversation_id}`);
  };

  const handleDelete = async (e: React.MouseEvent) => {
    e.stopPropagation();
    const confirmed = await confirm({
      title: "Delete conversation?",
      message: "Delete this conversation?",
      severity: "warning",
    });
    if (confirmed) {
      deleteMutation.mutate();
    }
  };

  const displayName =
    conversation.friendly_name ||
    `Conversation ${conversation.conversation_id.slice(-8)}`;

  return (
    <Paper
      elevation={isActive ? 2 : isHovered ? 1 : 0}
      onClick={handleClick}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
      sx={{
        p: 1.5,
        cursor: "pointer",
        border: 2,
        borderColor: isActive
          ? "primary.main"
          : isHovered
            ? "divider"
            : "transparent",
        borderRadius: 2,
        transition: "all 0.2s ease",
        bgcolor: isActive
          ? isDark
            ? "rgba(33, 150, 243, 0.08)"
            : "rgba(33, 150, 243, 0.04)"
          : "background.paper",
        "&:hover": {
          bgcolor: isActive
            ? undefined
            : isDark
              ? "rgba(255,255,255,0.02)"
              : "rgba(0,0,0,0.01)",
        },
      }}
      role="button"
      tabIndex={0}
      aria-current={isActive ? "page" : undefined}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          handleClick();
        }
      }}
    >
      {/* Header Row */}
      <Box
        sx={{
          display: "flex",
          alignItems: "flex-start",
          justifyContent: "space-between",
          gap: 1,
          mb: 0.5,
        }}
      >
        <Box sx={{ display: "flex", alignItems: "center", gap: 1, flex: 1, minWidth: 0 }}>
          {/* Agent Icon */}
          {getAgentIcon(metadata.agent_type)}

          {/* Title */}
          <Typography
            variant="body2"
            sx={{
              fontWeight: 500,
              flex: 1,
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
            }}
          >
            {displayName}
          </Typography>
        </Box>

        {/* Status + Delete */}
        <Box sx={{ display: "flex", alignItems: "center", gap: 0.5 }}>
          {getStatusIcon(metadata.status)}

          {isHovered && (
            <IconButton
              size="small"
              onClick={handleDelete}
              disabled={deleteMutation.isPending}
              sx={{ ml: 0.5, opacity: 0.6, "&:hover": { opacity: 1 } }}
              aria-label="Delete conversation"
            >
              <DeleteIcon sx={{ fontSize: 16 }} />
            </IconButton>
          )}
        </Box>
      </Box>

      {/* Query ID */}
      {metadata.query_id && (
        <Typography
          variant="caption"
          sx={{
            display: "block",
            fontFamily: "monospace",
            color: "text.secondary",
            mb: 0.5,
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          {metadata.query_id}
        </Typography>
      )}

      {/* Progress Bar (if active) */}
      {metadata.status === "active" && (
        <Box sx={{ mb: 1 }}>
          <LinearProgress
            sx={{
              height: 4,
              borderRadius: 2,
              bgcolor: isDark ? "rgba(255,255,255,0.1)" : "rgba(0,0,0,0.05)",
            }}
          />
        </Box>
      )}

      {/* Metadata Pills (if completed) */}
      {metadata.status === "completed" && (
        <Box sx={{ display: "flex", flexWrap: "wrap", gap: 0.5, mb: 1 }}>
          {metadata.recommendations_count !== undefined && (
            <Chip
              size="small"
              label={`🎯 ${metadata.recommendations_count} recs`}
              sx={{ height: 20, fontSize: "0.6875rem" }}
            />
          )}
          {metadata.estimated_improvement && (
            <Chip
              size="small"
              label={`⚡ ${metadata.estimated_improvement}`}
              sx={{ height: 20, fontSize: "0.6875rem" }}
            />
          )}
          {metadata.cost_reduction && (
            <Chip
              size="small"
              label={`💰 ${metadata.cost_reduction}`}
              sx={{ height: 20, fontSize: "0.6875rem" }}
            />
          )}
        </Box>
      )}

      {/* Timestamp */}
      <Box sx={{ display: "flex", alignItems: "center", gap: 0.5 }}>
        <AccessTimeIcon sx={{ fontSize: 12, color: "text.disabled" }} />
        <Typography variant="caption" sx={{ color: "text.secondary" }}>
          {timeAgo}
        </Typography>
      </Box>
      <ConfirmationDialog {...dialogProps} />
    </Paper>
  );
}

export default ConversationItemEnhanced;

