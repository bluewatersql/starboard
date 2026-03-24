/**
 * ConversationCostSummary component.
 *
 * Displays aggregated token usage and cost for the entire conversation.
 * Aggregates metadata from all assistant messages that carry token/cost data.
 *
 * Rendered as a subtle caption in the conversation header area.
 */

"use client";

import React from "react";
import { Typography } from "@mui/material";
import type { Message } from "@/lib/types/api";
import { MessageRole } from "@/lib/types/api";

interface MessageMetadata {
  tokens_used?: number;
  cost_usd?: number;
  [key: string]: unknown;
}

export interface ConversationCostSummaryProps {
  /** All messages in the current conversation */
  messages: Message[];
}

/**
 * Aggregate token usage and cost from all assistant messages.
 */
function aggregateUsage(messages: Message[]): {
  totalTokens: number;
  totalCostUsd: number;
} {
  let totalTokens = 0;
  let totalCostUsd = 0;

  for (const msg of messages) {
    if (msg.role !== MessageRole.ASSISTANT) continue;

    const meta = msg.metadata as MessageMetadata | undefined;
    if (!meta) continue;

    if (typeof meta.tokens_used === "number") {
      totalTokens += meta.tokens_used;
    }
    if (typeof meta.cost_usd === "number") {
      totalCostUsd += meta.cost_usd;
    }
  }

  return { totalTokens, totalCostUsd };
}

/**
 * ConversationCostSummary component.
 *
 * Shows total tokens and estimated cost for the whole conversation.
 * Returns null when no usage data is available yet.
 *
 * @param props - Component props
 * @returns Caption text showing aggregated usage, or null
 *
 * @example
 * ```tsx
 * <ConversationCostSummary messages={messages} />
 * ```
 */
export function ConversationCostSummary({
  messages,
}: ConversationCostSummaryProps) {
  const { totalTokens, totalCostUsd } = aggregateUsage(messages);

  if (totalTokens === 0 && totalCostUsd === 0) {
    return null;
  }

  const parts: string[] = [];
  if (totalTokens > 0) {
    parts.push(`${totalTokens.toLocaleString()} tokens`);
  }
  if (totalCostUsd > 0) {
    parts.push(`$${totalCostUsd.toFixed(4)}`);
  }

  return (
    <Typography
      variant="caption"
      color="text.secondary"
      sx={{ fontSize: "0.7rem" }}
    >
      {parts.join(" · ")}
    </Typography>
  );
}
