/**
 * Footer component for the application.
 * 
 * Displays disclaimer, model info, and copyright.
 */

"use client";

import React from "react";
import { Box, Typography, Link as MuiLink } from "@mui/material";
import { useConfigStore } from "@/lib/store/configStore";

export function Footer() {
  const model = useConfigStore((s) => s.model);
  const temperature = useConfigStore((s) => s.temperature);

  return (
    <Box
      component="footer"
      sx={{
        py: 2,
        px: 3,
        mt: "auto",
        borderTop: 1,
        borderColor: "divider",
        bgcolor: "background.paper",
      }}
    >
      <Box
        sx={{
          display: "flex",
          flexDirection: { xs: "column", sm: "row" },
          gap: 2,
          alignItems: { xs: "flex-start", sm: "center" },
          justifyContent: "space-between",
        }}
      >
        {/* Disclaimer */}
        <Typography variant="caption" color="text.secondary">
          ⚠️ AI can make mistakes. Verify important information.
        </Typography>

        {/* Model info and copyright */}
        <Box
          sx={{
            display: "flex",
            flexDirection: { xs: "column", sm: "row" },
            gap: { xs: 0.5, sm: 2 },
            alignItems: { xs: "flex-start", sm: "center" },
          }}
        >
          <Typography variant="caption" color="text.secondary">
            Model: {model} (temp: {temperature})
          </Typography>
          <Typography variant="caption" color="text.secondary">
            © {new Date().getFullYear()}{" "}
            <MuiLink
              href="https://github.com/yourusername/starboard"
              target="_blank"
              rel="noopener noreferrer"
              color="inherit"
              sx={{ textDecoration: "none", "&:hover": { textDecoration: "underline" } }}
            >
              Starboard AI
            </MuiLink>
          </Typography>
        </Box>
      </Box>
    </Box>
  );
}

