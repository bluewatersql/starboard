/**
 * TypingIndicator component.
 *
 * Animated indicator showing that the assistant is typing/thinking.
 */

"use client";

import React from "react";
import { Box, Paper, Fade } from "@mui/material";

/**
 * Typing indicator component.
 *
 * Shows animated dots to indicate the assistant is processing.
 *
 * @returns Typing indicator component
 *
 * @example
 * ```tsx
 * {isTyping && <TypingIndicator />}
 * ```
 */
export function TypingIndicator() {
  return (
    <Fade in={true} timeout={300}>
      <Box
        sx={{
          display: "flex",
          justifyContent: "flex-start",
          mb: 2,
          px: 2,
        }}
      >
      <Paper
        elevation={1}
        sx={{
          p: 1.5,
          borderRadius: 2,
          borderTopLeftRadius: 0,
        }}
      >
        <Box sx={{ display: "flex", gap: 0.5, alignItems: "center" }}>
          {[0, 1, 2].map((i) => (
            <Box
              key={i}
              sx={{
                width: 8,
                height: 8,
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
                    transform: "translateY(-4px)",
                  },
                },
              }}
            />
          ))}
        </Box>
      </Paper>
    </Box>
    </Fade>
  );
}

