/**
 * Copyright (c) 2025 Starboard AI
 * Licensed under the MIT License (see LICENSE file in the root directory)
 * 
 * Homepage - Welcome page with prompt entry.
 *
 * UX vNext Phase 1: FT-003
 * 
 * Replaces the old page.tsx that showed either welcome screen or chat interface.
 * New flow: Homepage → /chat (auto-create) → /chat/{id} (display)
 */

"use client";

import React from "react";
import { Box, Typography } from "@mui/material";
import { HeroPrompt, ExampleQueries } from "@/components/home";
import { ChatLayout } from "@/components/chat";
import { useUIStore } from "@/lib/store/uiStore";
import { useConversationStore } from "@/lib/store/conversationStore";

export default function HomePage() {
  const [selectedQuery, setSelectedQuery] = React.useState<string | undefined>();
  const setPendingMessage = useConversationStore((s) => s.setPendingMessage);
  const setPendingAttachment = useConversationStore((s) => s.setPendingAttachment);

  const handleExampleSelect = (queryText: string) => {
    setSelectedQuery(queryText);
  };

  // Default sidebar to collapsed on homepage for clean look
  const setSidebarOpen = useUIStore((s) => s.setSidebarOpen);
  React.useEffect(() => {
    setSidebarOpen(false);
    return () => {
      // Restore to open when navigating away
      setSidebarOpen(true);
    };
  }, [setSidebarOpen]);

  // Clear any stale pending state when landing page loads
  // This ensures a clean state for the hero prompt flow
  React.useEffect(() => {
    setPendingMessage(null);
    setPendingAttachment(null);
  }, [setPendingMessage, setPendingAttachment]);

  return (
    <ChatLayout>
      <main
        style={{
          flex: 1,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "flex-start",
          padding: "2rem 1rem",
          paddingTop: "4rem",
          overflow: "auto",
        }}
      >
        <Box
          sx={{
            maxWidth: 1200,
            width: "100%",
            display: "flex",
            flexDirection: "column",
            gap: 4,
          }}
        >
          {/* Logo */}
          <Box sx={{ display: "flex", justifyContent: "center", mb: 2 }}>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img 
              src="/logo_wheel_light_small.png"
              alt="Starboard Logo" 
              width={128} 
              height={128} 
            />
          </Box>
          {/* Heading */}
          <Typography
            variant="h2"
            component="h1"
            sx={{
              fontSize: { xs: "2rem", sm: "2.5rem", md: "3rem" },
              fontWeight: 700,
              textAlign: "center",
              mb: 1,
            }}
          >
            Welcome to Starboard AI Chat
          </Typography>

          {/* Tagline */}
          <Typography
            variant="h5"
            sx={{
              fontSize: { xs: "1.125rem", sm: "1.25rem", md: "1.5rem" },
              fontStyle: "italic",
              fontWeight: 500,
              textAlign: "center",
              color: "text.secondary",
              mb: 1,
            }}
          >
            Navigating deep Databricks insights for efficiency at scale.
          </Typography>

          {/* Description */}
          <Typography
            variant="body1"
            sx={{
              textAlign: "center",
              color: "text.secondary",
              maxWidth: 600,
              mx: "auto",
              mb: 4,
            }}
          >
            AI-powered assistant for Databricks workload analysis and optimization.
            Ask questions about your jobs, queries, tables, and costs.
          </Typography>

          {/* HeroPrompt */}
          <HeroPrompt initialValue={selectedQuery} />

          {/* Example Queries */}
          <ExampleQueries onSelect={handleExampleSelect} />
        </Box>
      </main>
    </ChatLayout>
  );
}
