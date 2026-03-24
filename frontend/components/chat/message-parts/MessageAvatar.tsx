/**
 * Avatar component for message bubbles.
 * Renders user or assistant avatar with optional agent badge.
 */

"use client";

import React from "react";
import { Box } from "@mui/material";
import { useTheme } from "@mui/material/styles";
import Image from "next/image";
import { AgentBadge } from "../AgentBadge";
import type { AgentType } from "@/lib/types/api";

export interface MessageAvatarProps {
  isUser: boolean;
  agentType?: AgentType;
}

export function MessageAvatar({ isUser, agentType }: MessageAvatarProps) {
  const theme = useTheme();

  return (
    <Box
      sx={{
        position: "relative",
        width: 48,
        height: 48,
        borderRadius: "50%",
        overflow: "visible",
        flexShrink: 0,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        bgcolor: "transparent",
      }}
    >
      <Box
        sx={{
          width: 32,
          height: 32,
          borderRadius: "50%",
          overflow: "hidden",
        }}
      >
        <Image
          src={
            isUser
              ? theme.palette.mode === "dark"
                ? "/user_icon_dark.png"
                : "/user_icon_light.png"
              : theme.palette.mode === "dark"
                ? "/system_icon_dark.png"
                : "/system_icon_light.png"
          }
          alt={isUser ? "User" : "Assistant"}
          width={48}
          height={48}
          style={{ objectFit: "cover" }}
        />
      </Box>

      {/* Agent badge for assistant messages */}
      {!isUser && agentType && <AgentBadge agentType={agentType} />}
    </Box>
  );
}

