/**
 * ConversationList component.
 *
 * Displays a list of conversations with search and filter capabilities.
 */

"use client";

import React, { useState, useEffect } from "react";
import {
  Box,
  List,
  TextField,
  InputAdornment,
  Typography,
} from "@mui/material";
import SearchIcon from "@mui/icons-material/Search";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api/client";
import { useConversationStore } from "@/lib/store/conversationStore";
import { ConversationItem } from "./ConversationItem";
import { ConversationListSkeleton } from "./ConversationListSkeleton";

/**
 * Conversation list component.
 *
 * Shows all conversations for the authenticated user with search functionality.
 * Fetches conversations from the backend API on mount.
 * User filtering is now done automatically by the backend based on authentication.
 *
 * @returns Conversation list component
 *
 * @example
 * ```tsx
 * <ConversationList />
 * ```
 */
export function ConversationList() {
  const [searchQuery, setSearchQuery] = useState("");
  const conversations = useConversationStore((s) => s.conversations);
  const activeConversationId = useConversationStore((s) => s.activeConversationId);
  const setConversations = useConversationStore((s) => s.setConversations);

  // Fetch conversations from backend API
  // Note: Backend automatically filters by authenticated user
  // UX vNext: Use cached conversations as initialData for instant render
  const { data: serverConversations, isLoading } = useQuery({
    queryKey: ["conversations"],  // Removed userId - backend filters automatically
    queryFn: () => api.listConversations(),  // No userId parameter needed
    staleTime: 1000 * 60, // 1 minute
    refetchOnMount: true,
    // ✅ Use Zustand cache as initial data for instant perceived performance
    initialData: conversations.length > 0 ? conversations : undefined,
    // This ensures:
    // 1. Returning users see cached data instantly (no loading state)
    // 2. Data refreshes in background
    // 3. New users see skeleton (no cached data)
  });

  // Sync server conversations to local store (merge with existing)
  // Only runs when server data changes, not when local state changes
  useEffect(() => {
    if (serverConversations) {
      // Create a map of server conversations by ID for efficient lookup
      const serverMap = new Map(
        serverConversations.map(c => [c.conversation_id, c])
      );
      
      // Merge: use server version if it exists, otherwise keep local version
      const merged: typeof conversations = [];
      
      // Add all server conversations (these are authoritative)
      // ConversationResponse now includes user_id from backend
      serverConversations.forEach(conv => merged.push({
        ...conv,
        user_id: conv.user_id || "unknown", // Backend provides user_id
      }));
      
      // Add local-only conversations (newly created, not yet on server)
      conversations.forEach(conv => {
        // Keep if it's newly created (skip validation)
        if (useConversationStore.getState().isNewlyCreated(conv.conversation_id)) {
          // Avoid duplicates if somehow it's in both
          if (!serverMap.has(conv.conversation_id)) {
            merged.push(conv);
          }
        }
        // If it's NOT newly created and NOT in server map, it was deleted on server.
        // So we drop it (don't push to merged).
      });
      
      setConversations(merged);
    }
    // Note: Deliberately excluding 'conversations' from deps to avoid infinite loop
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [serverConversations, setConversations]);

  // Filter conversations by search query
  const filteredConversations = conversations
    .filter((conv) => {
      const query = searchQuery.toLowerCase();
      // For now, just filter by conversation ID
      // In a real app, you'd search by message content or metadata
      return conv.conversation_id.toLowerCase().includes(query);
    })
    .sort((a, b) => {
      const dateA = new Date(a.updated_at || a.created_at).getTime();
      const dateB = new Date(b.updated_at || b.created_at).getTime();
      return dateB - dateA;
    });

  return (
    <Box sx={{ display: "flex", flexDirection: "column", height: "100%" }}>
      {/* Search bar */}
      <Box sx={{ p: 2 }}>
        <TextField
          fullWidth
          size="small"
          placeholder="Search conversations..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          InputProps={{
            startAdornment: (
              <InputAdornment position="start">
                <SearchIcon />
              </InputAdornment>
            ),
          }}
        />
      </Box>

      {/* Conversation list */}
      <Box sx={{ flex: 1, overflowY: "auto" }}>
        {/* Show skeleton ONLY if loading AND no cached data exists */}
        {isLoading && !serverConversations ? (
          <ConversationListSkeleton />
        ) : filteredConversations.length === 0 ? (
          <Box
            sx={{
              p: 3,
              textAlign: "center",
              color: "text.secondary",
            }}
          >
            <Typography variant="body2">
              {searchQuery
                ? "No conversations found"
                : "No conversations yet"}
            </Typography>
          </Box>
        ) : (
          <List sx={{ py: 0 }}>
            {filteredConversations.map((conversation) => (
              <ConversationItem
                key={conversation.conversation_id}
                conversation={conversation}
                isActive={
                  conversation.conversation_id === activeConversationId
                }
              />
            ))}
          </List>
        )}
      </Box>
    </Box>
  );
}

