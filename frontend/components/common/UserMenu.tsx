/**
 * UserMenu component.
 *
 * Displays current user information and authentication status.
 */

"use client";

import React from "react";
import { Box, Avatar, Typography, Tooltip, CircularProgress } from "@mui/material";
import PersonIcon from "@mui/icons-material/Person";
import { useAuth } from "@/lib/hooks/useAuth";

/**
 * User menu component.
 *
 * Shows authenticated user info in the sidebar/header.
 * Fetches user data from /me endpoint which includes display_name from Databricks.
 *
 * @returns User menu component
 *
 * @example
 * ```tsx
 * <UserMenu />
 * ```
 */
export function UserMenu() {
  const { user, isLoading, isAuthenticated } = useAuth();

  if (isLoading) {
    return (
      <Box
        sx={{
          display: "flex",
          alignItems: "center",
          gap: 1,
          px: 2,
          py: 1,
        }}
      >
        <CircularProgress size={24} />
        <Typography variant="body2" color="text.secondary">
          Loading...
        </Typography>
      </Box>
    );
  }

  if (!isAuthenticated || !user) {
    return (
      <Box
        sx={{
          display: "flex",
          alignItems: "center",
          gap: 1,
          px: 2,
          py: 1,
        }}
      >
        <Avatar sx={{ width: 32, height: 32, bgcolor: "action.disabled" }}>
          <PersonIcon fontSize="small" />
        </Avatar>
        <Typography variant="body2" color="text.secondary">
          Not authenticated
        </Typography>
      </Box>
    );
  }

  // Use display_name from /me endpoint, fallback to username, then user_id
  const displayName = user.display_name || user.username || user.user_id.split("@")[0] || "User";
  const initials = displayName
    .split(/[\s@.]/)
    .map((n) => n[0])
    .filter(Boolean)
    .slice(0, 2)
    .join("")
    .toUpperCase();

  return (
    <Tooltip title={`User ID: ${user.user_id}`} placement="right">
      <Box
        sx={{
          display: "flex",
          alignItems: "center",
          gap: 1.5,
          px: 2,
          py: 1,
          cursor: "pointer",
          "&:hover": {
            bgcolor: "action.hover",
          },
          borderRadius: 1,
        }}
      >
        <Avatar
          sx={{
            width: 32,
            height: 32,
            bgcolor: "primary.main",
            fontSize: "0.875rem",
            fontWeight: 600,
          }}
        >
          {initials}
        </Avatar>
        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Typography
            variant="body2"
            fontWeight={500}
            noWrap
            sx={{ lineHeight: 1.2 }}
          >
            {displayName}
          </Typography>
          <Typography
            variant="caption"
            color="text.secondary"
            noWrap
            sx={{ lineHeight: 1.2 }}
          >
            Authenticated
          </Typography>
        </Box>
      </Box>
    </Tooltip>
  );
}

