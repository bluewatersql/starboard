/**
 * Inline typing indicator shown when assistant is processing.
 */

"use client";

import React from "react";
import { Box } from "@mui/material";

export function TypingIndicatorInline() {
  return (
    <Box
      sx={{
        display: "flex",
        gap: 0.5,
        alignItems: "center",
        mt: 1,
        pl: 0.5,
      }}
    >
      {[0, 1, 2].map((i) => (
        <Box
          key={i}
          sx={{
            width: 6,
            height: 6,
            borderRadius: "50%",
            bgcolor: "text.secondary",
            animation: "typingAnimation 1.4s infinite",
            animationDelay: `${i * 0.2}s`,
            "@keyframes typingAnimation": {
              "0%, 60%, 100%": {
                opacity: 0.3,
                transform: "translateY(0)",
              },
              "30%": {
                opacity: 1,
                transform: "translateY(-3px)",
              },
            },
          }}
        />
      ))}
    </Box>
  );
}

