/**
 * ConversationSidebar component.
 *
 * Sidebar containing conversation list and new conversation button.
 */

"use client";

import React from "react";
import {
  Box,
  Drawer,
  IconButton,
  Typography,
  Button,
  Toolbar,
} from "@mui/material";
import MenuIcon from "@mui/icons-material/Menu";
import AddIcon from "@mui/icons-material/Add";
import DeleteSweepIcon from "@mui/icons-material/DeleteSweep";
import SettingsIcon from "@mui/icons-material/Settings";
import Brightness4Icon from "@mui/icons-material/Brightness4";
import Brightness7Icon from "@mui/icons-material/Brightness7";
import Image from "next/image";
import Link from "next/link";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api/client";
import { useConversationStore } from "@/lib/store/conversationStore";
import { useMessageStore } from "@/lib/store/messageStore";
import { useUIStore } from "@/lib/store/uiStore";
import { useThemeMode } from "@/lib/theme/ThemeProvider";
import { ConversationSearch } from "./ConversationSearch";
import { GroupedConversations } from "./GroupedConversations";
import { UserMenu } from "../common/UserMenu";
import { ErrorBoundary } from "../common/ErrorBoundary";
import type { Conversation } from "@/lib/types/api";
import { useConfirmation } from "@/lib/hooks/useConfirmation";
import { ConfirmationDialog } from "@/components/common/ConfirmationDialog";

/**
 * Conversation sidebar component.
 *
 * Contains conversation list, new conversation button, theme toggle, and user menu.
 * User authentication is now handled automatically by the backend.
 *
 * @returns Conversation sidebar component
 *
 * @example
 * ```tsx
 * <ConversationSidebar />
 * ```
 */
export function ConversationSidebar() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const sidebarOpen = useUIStore((s) => s.sidebarOpen);
  const toggleSidebar = useUIStore((s) => s.toggleSidebar);
  const sidebarWidth = useUIStore((s) => s.sidebarWidth);
  const addNotification = useUIStore((s) => s.addNotification);
  const conversations = useConversationStore((s) => s.conversations);
  const activeConversationId = useConversationStore((s) => s.activeConversationId);
  const setActiveConversation = useConversationStore((s) => s.setActiveConversation);
  const resetConversations = useConversationStore((s) => s.reset);
  const resetMessages = useMessageStore((s) => s.reset);
  const { mode, toggleTheme } = useThemeMode();
  const { confirm, dialogProps } = useConfirmation();
  
  // State for filtered conversations (used by ConversationSearch)
  const [filteredConversations, setFilteredConversations] = React.useState<Conversation[]>(conversations);
  
  // Keep filtered in sync when conversations change
  React.useEffect(() => {
    setFilteredConversations(conversations);
  }, [conversations]);

  // Clear all conversations mutation - uses batch delete API for efficiency
  const clearAllMutation = useMutation({
    mutationFn: async () => {
      // Delete all conversations with a single API call (batch operation)
      // This is much more efficient than deleting one-by-one
      await api.deleteAllConversations();
    },
    // ✅ Optimistic update: Clear UI immediately (before API call completes)
    onMutate: async () => {
      // Clear all state immediately for instant UI response
      resetConversations();
      resetMessages();
      
      // Cancel any outgoing refetches (so they don't overwrite our optimistic update)
      await queryClient.cancelQueries({ queryKey: ["conversations"] });

      // Optimistically update React Query cache to empty list
      queryClient.setQueryData(["conversations"], []);
      
      // Remove history queries to prevent stale messages from reappearing
      queryClient.removeQueries({ queryKey: ["conversation-history"] });
      
      // Show success notification immediately (optimistic)
      addNotification({
        message: "All conversations cleared",
        type: "success",
        duration: 3000,
      });
    },
    onSuccess: () => {
      // API call completed successfully
      // Now we can safely invalidate to ensure backend sync
      queryClient.invalidateQueries({ queryKey: ["conversations"] });
    },
    onError: (error) => {
      // Rollback: Refetch conversations to restore state
      console.error("Failed to clear conversations:", error);
      
      // Refetch to restore state (rollback optimistic update)
      queryClient.invalidateQueries({ queryKey: ["conversations"] });
      
      addNotification({
        message:
          error instanceof Error
            ? error.message
            : "Failed to clear conversations. Please try again.",
        type: "error",
        duration: 5000,
      });
    },
  });

  const handleNewConversation = () => {
    // Navigate to new conversation page (client-side only until first message)
    setActiveConversation(null);
    // Use router.push for client-side navigation instead of full reload
    router.push("/chat");
  };

  const handleClearAll = async () => {
    if (conversations.length === 0) {
      addNotification({
        message: "No conversations to clear",
        type: "info",
        duration: 3000,
      });
      return;
    }

    const confirmed = await confirm({
      title: "Delete all conversations?",
      message: `Delete all ${conversations.length} conversation(s)? This cannot be undone.`,
      confirmLabel: "Delete all",
      severity: "error",
    });
    if (confirmed) {
      // Use batch delete API - no need to pass IDs, backend handles it
      clearAllMutation.mutate();
      // Always navigate to new conversation page to clear current view
      router.push("/chat");
    }
  };

  return (
    <Drawer
      variant="permanent"
      anchor="left"
      sx={{
        width: sidebarWidth,
        flexShrink: 0,
        transition: "width 0.2s ease",
        "& .MuiDrawer-paper": {
          width: sidebarWidth,
          boxSizing: "border-box",
          overflowX: "hidden",
          transition: "width 0.2s ease",
        },
      }}
    >
      <Box sx={{ display: "flex", flexDirection: "column", height: "100%" }}>
        {/* Header */}
        <Toolbar
          sx={{
            display: "flex",
            alignItems: "center",
            justifyContent: sidebarOpen ? "space-between" : "center",
            px: sidebarOpen ? 2 : 1,
            minHeight: 64,
          }}
        >
          {sidebarOpen ? (
            <>
              <Link href="/" style={{ textDecoration: "none", color: "inherit", display: "flex", alignItems: "center", gap: 8 }}>
                <Image
                  src={mode === "dark" ? "/logo_wheel_dark_small.png" : "/logo_wheel_light_small.png"}
                  alt="Starboard Logo"
                  width={48}
                  height={48}
                  style={{ objectFit: "contain" }}
                />
                <Typography variant="h6" noWrap component="div">
                  Starboard
                </Typography>
              </Link>
              <Box>
                <IconButton onClick={toggleTheme} size="small">
                  {mode === "dark" ? <Brightness7Icon /> : <Brightness4Icon />}
                </IconButton>
                <IconButton onClick={toggleSidebar} size="small">
                  <MenuIcon />
                </IconButton>
              </Box>
            </>
          ) : (
            <Box sx={{ display: "flex", flexDirection: "column", gap: 1, alignItems: "center" }}>
              <IconButton onClick={toggleSidebar} size="small">
                <MenuIcon />
              </IconButton>
              <Link href="/" style={{ textDecoration: "none", color: "inherit", display: "flex" }}>
                <Image
                  src={mode === "dark" ? "/logo_wheel_dark_small.png" : "/logo_wheel_light_small.png"}
                  alt="Starboard Logo"
                  width={32}
                  height={32}
                  style={{ objectFit: "contain" }}
                />
              </Link>
              <IconButton onClick={toggleTheme} size="small">
                {mode === "dark" ? <Brightness7Icon /> : <Brightness4Icon />}
              </IconButton>
            </Box>
          )}
        </Toolbar>

        {/* New conversation button */}
        <Box sx={{ px: sidebarOpen ? 2 : 1, pb: 2 }}>
          {sidebarOpen ? (
            <Button
              fullWidth
              variant="contained"
              startIcon={<AddIcon />}
              onClick={handleNewConversation}
            >
              New Conversation
            </Button>
          ) : (
            <IconButton
              onClick={handleNewConversation}
              color="primary"
              sx={{ width: "100%" }}
            >
              <AddIcon />
            </IconButton>
          )}
        </Box>

        {/* Conversation list - only show when expanded */}
        {sidebarOpen && (
          <Box sx={{ flex: 1, overflow: "hidden", display: "flex", flexDirection: "column" }}>
            {/* Search and filter */}
            <ConversationSearch
              conversations={conversations}
              onFilteredChange={setFilteredConversations}
            />
            
            {/* Grouped conversation list */}
            <Box sx={{ flex: 1, overflowY: "auto", overflowX: "hidden" }}>
              <ErrorBoundary
                fallback={
                  <Box sx={{ p: 2, textAlign: "center" }}>
                    <Typography variant="body2" color="error">
                      Failed to load conversations
                    </Typography>
                    <Button
                      size="small"
                      onClick={() => window.location.reload()}
                      sx={{ mt: 1 }}
                    >
                      Reload
                    </Button>
                  </Box>
                }
              >
                <GroupedConversations
                  conversations={filteredConversations}
                  currentConversationId={activeConversationId ?? undefined}
                />
              </ErrorBoundary>
            </Box>
          </Box>
        )}

        {/* Spacer when collapsed */}
        {!sidebarOpen && <Box sx={{ flex: 1 }} />}

        {/* User menu - only show when expanded */}
        {sidebarOpen && (
          <Box sx={{ px: 2, pb: 2, borderTop: 1, borderColor: "divider" }}>
            <UserMenu />
          </Box>
        )}

        {/* Config and Clear buttons */}
        <Box
          sx={{
            px: sidebarOpen ? 2 : 1,
            pb: 2,
            display: "flex",
            flexDirection: "column",
            gap: 1,
            borderTop: sidebarOpen ? 0 : 1,
            borderColor: "divider",
            pt: sidebarOpen ? 0 : 2,
          }}
        >
          {sidebarOpen ? (
            <>
              <Button
                fullWidth
                variant="outlined"
                startIcon={<SettingsIcon />}
                onClick={() => router.push("/config")}
                size="small"
              >
                Configuration
              </Button>
              <Button
                fullWidth
                variant="outlined"
                color="error"
                startIcon={<DeleteSweepIcon />}
                onClick={handleClearAll}
                disabled={clearAllMutation.isPending || conversations.length === 0}
                size="small"
              >
                {clearAllMutation.isPending ? "Clearing..." : "Clear All"}
              </Button>
            </>
          ) : (
            <>
              <IconButton onClick={() => router.push("/config")} size="small" sx={{ width: "100%" }}>
                <SettingsIcon />
              </IconButton>
              <IconButton
                onClick={handleClearAll}
                disabled={clearAllMutation.isPending || conversations.length === 0}
                size="small"
                color="error"
                sx={{ width: "100%" }}
              >
                <DeleteSweepIcon />
              </IconButton>
            </>
          )}
        </Box>
      </Box>
      <ConfirmationDialog {...dialogProps} />
    </Drawer>
  );
}
