/**
 * Conversation search and filter component.
 *
 * Provides search input and filter tabs for conversation list.
 */

"use client";

import React, { useState, useMemo, useCallback } from "react";
import {
  Box,
  TextField,
  InputAdornment,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from "@mui/material";
import SearchIcon from "@mui/icons-material/Search";
import type { Conversation } from "@/lib/types/api";

export type ConversationFilter = "all" | "advisor" | "analytics";

interface ConversationSearchProps {
  /** All conversations to filter */
  conversations: Conversation[];
  /** Callback with filtered results */
  onFilteredChange: (filtered: Conversation[]) => void;
  /** Placeholder text for search input */
  placeholder?: string;
}

/**
 * Search and filter component for conversations.
 *
 * @example
 * ```tsx
 * <ConversationSearch
 *   conversations={allConversations}
 *   onFilteredChange={setFilteredConversations}
 * />
 * ```
 */
export function ConversationSearch({
  conversations,
  onFilteredChange,
  placeholder = "Search conversations...",
}: ConversationSearchProps) {
  const [searchQuery, setSearchQuery] = useState("");
  const [filterType, setFilterType] = useState<ConversationFilter>("all");

  // Filter conversations based on search and filter type
  const filtered = useMemo(() => {
    let result = conversations;

    // Filter by search query
    if (searchQuery.trim()) {
      const query = searchQuery.toLowerCase();
      result = result.filter((conv) => {
        const name = conv.friendly_name || conv.conversation_id;
        const matchesName = name.toLowerCase().includes(query);
        const matchesId = conv.conversation_id.toLowerCase().includes(query);
        // Also search in metadata if available
        const metadata = conv.metadata as Record<string, unknown> | undefined;
        const matchesQueryId =
          metadata?.query_id &&
          String(metadata.query_id).toLowerCase().includes(query);

        return matchesName || matchesId || matchesQueryId;
      });
    }

    // Filter by agent type
    if (filterType !== "all") {
      result = result.filter((conv) => {
        const metadata = conv.metadata as Record<string, unknown> | undefined;
        return metadata?.agent_type === filterType;
      });
    }

    return result;
  }, [conversations, searchQuery, filterType]);

  // Notify parent of filtered results
  const notifyChange = useCallback(() => {
    onFilteredChange(filtered);
  }, [filtered, onFilteredChange]);

  // Trigger callback when filtered changes
  React.useEffect(() => {
    notifyChange();
  }, [notifyChange]);

  const handleSearchChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    setSearchQuery(event.target.value);
  };

  const handleFilterChange = (
    _event: React.MouseEvent<HTMLElement>,
    newFilter: ConversationFilter | null
  ) => {
    if (newFilter !== null) {
      setFilterType(newFilter);
    }
  };

  const hasResults = filtered.length > 0;
  const hasSearch = searchQuery.trim().length > 0;

  return (
    <Box sx={{ px: 2, pb: 2, pt: 1 }}>
      {/* Search Input */}
      <TextField
        fullWidth
        size="small"
        value={searchQuery}
        onChange={handleSearchChange}
        placeholder={placeholder}
        InputProps={{
          startAdornment: (
            <InputAdornment position="start">
              <SearchIcon sx={{ fontSize: 20, color: "text.secondary" }} />
            </InputAdornment>
          ),
        }}
        sx={{
          mb: 1.5,
          "& .MuiOutlinedInput-root": {
            borderRadius: 2,
            bgcolor: "background.paper",
          },
        }}
        aria-label="Search conversations"
      />

      {/* Filter Tabs */}
      <ToggleButtonGroup
        value={filterType}
        exclusive
        onChange={handleFilterChange}
        size="small"
        fullWidth
        aria-label="Filter conversations by type"
        sx={{
          "& .MuiToggleButton-root": {
            flex: 1,
            py: 0.5,
            fontSize: "0.75rem",
            fontWeight: 500,
            textTransform: "none",
            borderRadius: 1.5,
            "&.Mui-selected": {
              bgcolor: "primary.main",
              color: "primary.contrastText",
              "&:hover": {
                bgcolor: "primary.dark",
              },
            },
          },
        }}
      >
        <ToggleButton value="all">All</ToggleButton>
        <ToggleButton value="advisor">Advisor</ToggleButton>
        <ToggleButton value="analytics">Analytics</ToggleButton>
      </ToggleButtonGroup>

      {/* Results Count */}
      {hasSearch && (
        <Typography
          variant="caption"
          sx={{ display: "block", mt: 1, color: "text.secondary" }}
        >
          {filtered.length} result{filtered.length !== 1 ? "s" : ""}
          {!hasResults && " found"}
        </Typography>
      )}
    </Box>
  );
}

export default ConversationSearch;

