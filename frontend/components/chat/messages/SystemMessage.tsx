/**
 * SystemMessage component.
 * Renders system messages with centered, informational styling.
 */

"use client";

import React from "react";
import { Box, Paper, Fade } from "@mui/material";
import { useTheme } from "@mui/material/styles";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { MarkdownCodeRenderer } from "../message-parts";

/** Stable reference for ReactMarkdown components to prevent re-renders */
const MARKDOWN_COMPONENTS = { code: MarkdownCodeRenderer };

export interface SystemMessageProps {
  content: string;
}

export function SystemMessage({ content }: SystemMessageProps) {
  const theme = useTheme();

  return (
    <Fade in={true} timeout={500}>
      <Box
        sx={{
          display: "flex",
          justifyContent: "center",
          mb: 3,
          px: 2,
        }}
      >
        <Paper
          elevation={0}
          sx={{
            maxWidth: "85%",
            p: 2.5,
            bgcolor:
              theme.palette.mode === "dark"
                ? "rgba(144, 202, 249, 0.08)" // Light blue tint in dark mode
                : "rgba(25, 118, 210, 0.04)", // Light blue tint in light mode
            border: `1px solid ${
              theme.palette.mode === "dark"
                ? "rgba(144, 202, 249, 0.2)"
                : "rgba(25, 118, 210, 0.1)"
            }`,
            borderRadius: 2,
          }}
        >
          <Box
            sx={{
              "& p": {
                m: 0,
                mb: 1,
                "&:last-child": { mb: 0 },
              },
              "& ul, & ol": {
                ml: 2,
                mb: 1,
              },
              "& h1, & h2, & h3": {
                mt: 1.5,
                mb: 1,
                "&:first-of-type": { mt: 0 },
              },
              "& code": {
                bgcolor:
                  theme.palette.mode === "dark"
                    ? "rgba(255, 255, 255, 0.1)"
                    : "rgba(0, 0, 0, 0.05)",
                p: 0.5,
                borderRadius: 0.5,
                fontSize: "0.9em",
              },
              fontSize: "0.95rem",
              lineHeight: 1.6,
            }}
          >
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={MARKDOWN_COMPONENTS}
            >
              {content}
            </ReactMarkdown>
          </Box>
        </Paper>
      </Box>
    </Fade>
  );
}

