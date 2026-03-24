/**
 * ChatLayout - Main application shell for chat interface.
 *
 * Provides:
 * - Conversation sidebar
 * - Header with menu toggle and logo
 * - Theme toggle (in sidebar)
 * - Config panel (in sidebar)
 * - Responsive layout
 *
 * UX vNext: Extracted from old page.tsx to be reusable across routes
 */

"use client";

import React from "react";
import { Box } from "@mui/material";
import { ConversationSidebar } from "@/components/conversations/ConversationSidebar";
import { Footer } from "@/components/layout";
import { KeyboardShortcutProvider } from "@/components/common/KeyboardShortcutProvider";

interface ChatLayoutProps {
  children: React.ReactNode;
}

export function ChatLayout({ children }: ChatLayoutProps) {

  return (
    <KeyboardShortcutProvider>
    <Box
      sx={{
        display: "flex",
        height: "100vh",
        overflow: "hidden",
        flexDirection: { xs: "column", md: "row" },
      }}
    >
      {/* Sidebar - Contains conversation history, config, theme toggle */}
      <ConversationSidebar />

      {/* Main chat area */}
      <Box
        sx={{
          flex: 1,
          display: "flex",
          flexDirection: "column",
          minWidth: 0,
          overflow: "hidden",
        }}
      >
        {/* Main content - flex: 1 with minHeight: 0 to allow proper flex shrinking */}
        <Box sx={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
          {children}
        </Box>
        
        {/* Footer */}
        <Footer />
      </Box>
    </Box>
    </KeyboardShortcutProvider>
  );
}

