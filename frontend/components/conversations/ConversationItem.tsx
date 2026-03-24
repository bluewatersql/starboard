/**
 * ConversationItem component.
 *
 * Displays a single conversation in the sidebar list.
 * Uses optimistic delete for immediate UI feedback.
 */

"use client";

import React, { useRef } from "react";
import {
  ListItemButton,
  ListItemText,
  IconButton,
  Box,
  Typography,
} from "@mui/material";
import DeleteIcon from "@mui/icons-material/Delete";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api/client";
import { useConversationStore } from "@/lib/store/conversationStore";
import { useMessageStore } from "@/lib/store/messageStore";
import { useUIStore } from "@/lib/store/uiStore";
import type { Conversation, Message } from "@/lib/types/api";
import { useConfirmation } from "@/lib/hooks/useConfirmation";
import { ConfirmationDialog } from "@/components/common/ConfirmationDialog";

interface ConversationItemProps {
  conversation: Conversation;
  isActive: boolean;
}

/**
 * Conversation item component.
 *
 * Renders a single conversation with selection and delete actions.
 * Uses optimistic updates for instant delete feedback.
 *
 * @param props - Component props
 * @returns Conversation item component
 *
 * @example
 * ```tsx
 * <ConversationItem conversation={conv} isActive={false} />
 * ```
 */
export function ConversationItem({
  conversation,
  isActive,
}: ConversationItemProps) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const setActiveConversation = useConversationStore((s) => s.setActiveConversation);
  const removeConversation = useConversationStore((s) => s.removeConversation);
  const addConversation = useConversationStore((s) => s.addConversation);
  const addNotification = useUIStore((s) => s.addNotification);
  const clearMessages = useMessageStore((s) => s.clearMessages);
  const messagesByConversation = useMessageStore((s) => s.messagesByConversation);
  
  const { confirm, dialogProps } = useConfirmation();

  // Store snapshots for potential rollback
  const snapshotRef = useRef<{
    conversation: Conversation;
    messages: Message[];
  } | null>(null);

  // Delete mutation with optimistic update
  const deleteMutation = useMutation({
    mutationFn: async () => {
      try {
        await api.deleteConversation(conversation.conversation_id);
      } catch (error) {
        // If conversation is already deleted (404), treat as success
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
    // Set as active conversation
    setActiveConversation(conversation.conversation_id);
    
    // Navigate to conversation page (using query params for static export)
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

  // Format timestamp
  const formattedDate = new Date(conversation.created_at).toLocaleDateString(
    [],
    {
      month: "short",
      day: "numeric",
      year:
        new Date(conversation.created_at).getFullYear() !==
        new Date().getFullYear()
          ? "numeric"
          : undefined,
    }
  );

  return (
    <>
      <ListItemButton
        selected={isActive}
        onClick={handleClick}
        sx={{
          borderRadius: 1,
          mx: 1,
          mb: 0.5,
          "&.Mui-selected": {
            bgcolor: "action.selected",
            "&:hover": {
              bgcolor: "action.selected",
            },
          },
        }}
      >
        <ListItemText
          primary={
            <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
              <Typography
                variant="body2"
                sx={{
                  flex: 1,
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                }}
              >
                {conversation.friendly_name ||
                  `Conversation ${conversation.conversation_id.slice(-8)}`}
              </Typography>
              <IconButton
                size="small"
                onClick={handleDelete}
                disabled={deleteMutation.isPending}
                sx={{ opacity: 0.6, "&:hover": { opacity: 1 } }}
              >
                <DeleteIcon fontSize="small" />
              </IconButton>
            </Box>
          }
          secondary={
            <Typography variant="caption" color="text.secondary">
              {formattedDate}
            </Typography>
          }
        />
      </ListItemButton>
      <ConfirmationDialog {...dialogProps} />
    </>
  );
}

