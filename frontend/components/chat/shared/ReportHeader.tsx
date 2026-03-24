/**
 * Shared report header component.
 *
 * Provides consistent header UI across all report types with download controls,
 * share functionality, and re-run option.
 * 
 * Phase 2: Enhanced with share and re-run buttons.
 */

"use client";

import React, { useState } from "react";
import { 
  Box, 
  Typography, 
  IconButton, 
  Tooltip, 
  Divider,
  Snackbar,
  Menu,
  MenuItem,
  ListItemIcon,
  ListItemText,
} from "@mui/material";
import DownloadIcon from "@mui/icons-material/Download";
import CodeIcon from "@mui/icons-material/Code";
import ShareIcon from "@mui/icons-material/Share";
import RefreshIcon from "@mui/icons-material/Refresh";
import DescriptionIcon from "@mui/icons-material/Description";
import CheckIcon from "@mui/icons-material/Check";

interface ReportHeaderProps {
  /** Report title with icon */
  title: string;
  /** Report icon/emoji */
  icon?: string;
  /** Download markdown handler */
  onDownloadMarkdown?: () => void;
  /** Download JSON handler (if complete_report available) */
  onDownloadJSON?: () => void;
  /** Whether JSON download is available */
  hasCompleteReport?: boolean;
  /** Re-run analysis handler */
  onRerun?: () => void;
  /** Whether re-run is available */
  canRerun?: boolean;
  /** Conversation ID for share link */
  conversationId?: string;
  /** Make header sticky */
  sticky?: boolean;
}

/**
 * Header component for all report types.
 *
 * Provides consistent download controls, share, and re-run functionality
 * across analytics and advisor reports.
 *
 * @param props - Component props
 * @returns Report header component
 *
 * @example
 * ```tsx
 * <ReportHeader
 *   title="Cost Analysis Report"
 *   icon="💰"
 *   onDownloadMarkdown={handleDownload}
 *   onDownloadJSON={handleDownloadJSON}
 *   hasCompleteReport={true}
 *   onRerun={handleRerun}
 *   conversationId="conv_123"
 * />
 * ```
 */
export function ReportHeader({
  title,
  icon = "📊",
  onDownloadMarkdown,
  onDownloadJSON,
  hasCompleteReport = false,
  onRerun,
  canRerun = true,
  conversationId,
  sticky = false,
}: ReportHeaderProps) {
  const [snackbarOpen, setSnackbarOpen] = useState(false);
  const [snackbarMessage, setSnackbarMessage] = useState("");
  const [downloadMenuAnchor, setDownloadMenuAnchor] = useState<null | HTMLElement>(null);

  const handleShareLink = async () => {
    if (!conversationId) return;
    
    // Using query params for static export compatibility
    const shareUrl = `${window.location.origin}/chat?id=${conversationId}`;
    
    try {
      await navigator.clipboard.writeText(shareUrl);
      setSnackbarMessage("Link copied to clipboard!");
      setSnackbarOpen(true);
    } catch {
      // Fallback for older browsers
      const textArea = document.createElement("textarea");
      textArea.value = shareUrl;
      document.body.appendChild(textArea);
      textArea.select();
      document.execCommand("copy");
      document.body.removeChild(textArea);
      setSnackbarMessage("Link copied to clipboard!");
      setSnackbarOpen(true);
    }
  };

  const handleDownloadClick = (event: React.MouseEvent<HTMLElement>) => {
    // If only one download option, execute directly
    if (onDownloadMarkdown && !hasCompleteReport) {
      onDownloadMarkdown();
      return;
    }
    if (!onDownloadMarkdown && hasCompleteReport && onDownloadJSON) {
      onDownloadJSON();
      return;
    }
    // Show menu if multiple options
    setDownloadMenuAnchor(event.currentTarget);
  };

  const handleDownloadMenuClose = () => {
    setDownloadMenuAnchor(null);
  };

  const handleDownloadMarkdown = () => {
    onDownloadMarkdown?.();
    handleDownloadMenuClose();
  };

  const handleDownloadJSON = () => {
    onDownloadJSON?.();
    handleDownloadMenuClose();
  };

  return (
    <>
      <Box
        sx={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          mb: 1.5,
          ...(sticky && {
            position: "sticky",
            top: 0,
            bgcolor: "background.paper",
            zIndex: 1,
            py: 1,
            mx: -2,
            px: 2,
            borderBottom: 1,
            borderColor: "divider",
          }),
        }}
      >
        <Typography
          variant="h6"
          sx={{
            fontWeight: 600,
            color: "primary.main",
            fontSize: "1.1rem",
            display: "flex",
            alignItems: "center",
            gap: 0.5,
          }}
        >
          {icon} {title}
        </Typography>

        <Box sx={{ display: "flex", gap: 0.5 }}>
          {/* Download button(s) */}
          {(onDownloadMarkdown || (hasCompleteReport && onDownloadJSON)) && (
            <>
              <Tooltip title="Download report">
                <IconButton
                  size="small"
                  onClick={handleDownloadClick}
                  sx={{
                    "&:hover": {
                      bgcolor: "action.hover",
                    },
                  }}
                >
                  <DownloadIcon fontSize="small" />
                </IconButton>
              </Tooltip>
              <Menu
                anchorEl={downloadMenuAnchor}
                open={Boolean(downloadMenuAnchor)}
                onClose={handleDownloadMenuClose}
                anchorOrigin={{
                  vertical: "bottom",
                  horizontal: "right",
                }}
                transformOrigin={{
                  vertical: "top",
                  horizontal: "right",
                }}
              >
                {onDownloadMarkdown && (
                  <MenuItem onClick={handleDownloadMarkdown}>
                    <ListItemIcon>
                      <DescriptionIcon fontSize="small" />
                    </ListItemIcon>
                    <ListItemText>Download as Markdown</ListItemText>
                  </MenuItem>
                )}
                {hasCompleteReport && onDownloadJSON && (
                  <MenuItem onClick={handleDownloadJSON}>
                    <ListItemIcon>
                      <CodeIcon fontSize="small" />
                    </ListItemIcon>
                    <ListItemText>Download as JSON</ListItemText>
                  </MenuItem>
                )}
              </Menu>
            </>
          )}

          {/* Share button */}
          {conversationId && (
            <Tooltip title="Copy share link">
              <IconButton
                size="small"
                onClick={handleShareLink}
                sx={{
                  "&:hover": {
                    bgcolor: "action.hover",
                  },
                }}
              >
                <ShareIcon fontSize="small" />
              </IconButton>
            </Tooltip>
          )}

          {/* Re-run button */}
          {onRerun && canRerun && (
            <Tooltip title="Re-run analysis">
              <IconButton
                size="small"
                onClick={onRerun}
                sx={{
                  "&:hover": {
                    bgcolor: "action.hover",
                    color: "primary.main",
                  },
                }}
              >
                <RefreshIcon fontSize="small" />
              </IconButton>
            </Tooltip>
          )}
        </Box>
      </Box>

      {!sticky && <Divider sx={{ mb: 2 }} />}

      {/* Snackbar for copy confirmation */}
      <Snackbar
        open={snackbarOpen}
        autoHideDuration={2000}
        onClose={() => setSnackbarOpen(false)}
        message={
          <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
            <CheckIcon fontSize="small" />
            {snackbarMessage}
          </Box>
        }
        anchorOrigin={{ vertical: "bottom", horizontal: "center" }}
      />
    </>
  );
}

