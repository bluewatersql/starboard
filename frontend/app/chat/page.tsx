/**
 * Chat page - Handles both new and existing conversations.
 *
 * UX vNext Phase 1: FT-001
 * 
 * URL patterns:
 * - /chat           → New conversation (conversationId="new")
 * - /chat?id=xyz    → Existing conversation (static export compatible)
 * 
 * This uses query params instead of path params for Databricks Apps
 * static export compatibility.
 */

"use client";

import React, { Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { ChatContainer, ChatLayout } from "@/components/chat";
import { CircularProgress, Box } from "@mui/material";

/**
 * Inner component that uses useSearchParams.
 * Must be wrapped in Suspense for static export.
 */
function ChatPageContent() {
  const searchParams = useSearchParams();
  const conversationId = searchParams.get("id") || "new";
  // Check if this is a newly created conversation (from HeroPrompt navigation)
  const isNewlyCreated = searchParams.get("new") === "1";

  return (
    <ChatLayout>
      <ChatContainer conversationId={conversationId} skipSSEValidation={isNewlyCreated} />
    </ChatLayout>
  );
}

/**
 * Loading fallback for Suspense boundary.
 */
function ChatLoadingFallback() {
  return (
    <ChatLayout>
      <Box
        sx={{
          display: "flex",
          justifyContent: "center",
          alignItems: "center",
          height: "100%",
          minHeight: "400px",
        }}
      >
        <CircularProgress />
      </Box>
    </ChatLayout>
  );
}

export default function ChatPage() {
  return (
    <Suspense fallback={<ChatLoadingFallback />}>
      <ChatPageContent />
    </Suspense>
  );
}
