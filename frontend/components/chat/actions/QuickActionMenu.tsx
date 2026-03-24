/**
 * Quick action menu component.
 *
 * Dropdown menu for message-level actions like share, retry, delete.
 */

"use client";

import React, { useState } from "react";
import {
  IconButton,
  Menu,
  MenuItem,
  ListItemIcon,
  ListItemText,
  Divider,
  Tooltip,
} from "@mui/material";
import MoreVertIcon from "@mui/icons-material/MoreVert";
import ShareIcon from "@mui/icons-material/Share";
import RefreshIcon from "@mui/icons-material/Refresh";
import ContentCopyIcon from "@mui/icons-material/ContentCopy";
import DeleteIcon from "@mui/icons-material/Delete";
import CheckIcon from "@mui/icons-material/Check";
import { useConfirmation } from "@/lib/hooks/useConfirmation";
import { ConfirmationDialog } from "@/components/common/ConfirmationDialog";

interface QuickActionMenuProps {
  /** Message ID for action context */
  messageId: string;
  /** Message content for copy action */
  content?: string;
  /** Callback when share is clicked */
  onShare?: () => void;
  /** Callback when retry is clicked */
  onRetry?: () => void;
  /** Callback when delete is clicked */
  onDelete?: () => void;
  /** Callback when copy is clicked (optional - defaults to copying content) */
  onCopy?: () => void;
}

/**
 * Quick action dropdown menu for messages.
 *
 * @example
 * ```tsx
 * <QuickActionMenu
 *   messageId="msg-123"
 *   content="Message text..."
 *   onShare={() => shareMessage("msg-123")}
 *   onRetry={() => retryMessage("msg-123")}
 *   onDelete={() => deleteMessage("msg-123")}
 * />
 * ```
 */
export function QuickActionMenu({
  content,
  onShare,
  onRetry,
  onDelete,
  onCopy,
}: Omit<QuickActionMenuProps, 'messageId'>) {
  const [anchorEl, setAnchorEl] = useState<null | HTMLElement>(null);
  const [copied, setCopied] = useState(false);
  const open = Boolean(anchorEl);
  const { confirm, dialogProps } = useConfirmation();

  const handleClick = (event: React.MouseEvent<HTMLElement>) => {
    setAnchorEl(event.currentTarget);
  };

  const handleClose = () => {
    setAnchorEl(null);
  };

  const handleCopy = async () => {
    if (onCopy) {
      onCopy();
    } else if (content) {
      try {
        await navigator.clipboard.writeText(content);
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
      } catch (err) {
        console.error("Failed to copy:", err);
      }
    }
    handleClose();
  };

  const handleShare = () => {
    onShare?.();
    handleClose();
  };

  const handleRetry = () => {
    onRetry?.();
    handleClose();
  };

  const handleDelete = async () => {
    handleClose();
    const confirmed = await confirm({
      title: "Delete message?",
      message: "Are you sure you want to delete this message?",
      severity: "warning",
    });
    if (confirmed) {
      onDelete?.();
    }
  };

  // Check if any actions are available
  const hasActions = onShare || onRetry || onDelete || content;

  if (!hasActions) {
    return null;
  }

  return (
    <>
      <Tooltip title="More actions">
        <IconButton
          size="small"
          onClick={handleClick}
          aria-label="Open actions menu"
          aria-controls={open ? "quick-action-menu" : undefined}
          aria-haspopup="true"
          aria-expanded={open ? "true" : undefined}
          sx={{
            opacity: 0,
            transition: "opacity 0.2s",
            ".message-container:hover &": {
              opacity: 1,
            },
            "&:focus": {
              opacity: 1,
            },
          }}
        >
          <MoreVertIcon fontSize="small" />
        </IconButton>
      </Tooltip>

      <Menu
        id="quick-action-menu"
        anchorEl={anchorEl}
        open={open}
        onClose={handleClose}
        anchorOrigin={{
          vertical: "bottom",
          horizontal: "right",
        }}
        transformOrigin={{
          vertical: "top",
          horizontal: "right",
        }}
        slotProps={{
          paper: {
            elevation: 3,
            sx: {
              minWidth: 180,
              borderRadius: 2,
            },
          },
        }}
      >
        {/* Copy action */}
        {content && (
          <MenuItem onClick={handleCopy}>
            <ListItemIcon>
              {copied ? (
                <CheckIcon fontSize="small" color="success" />
              ) : (
                <ContentCopyIcon fontSize="small" />
              )}
            </ListItemIcon>
            <ListItemText>{copied ? "Copied!" : "Copy message"}</ListItemText>
          </MenuItem>
        )}

        {/* Share action */}
        {onShare && (
          <MenuItem onClick={handleShare}>
            <ListItemIcon>
              <ShareIcon fontSize="small" />
            </ListItemIcon>
            <ListItemText>Share message</ListItemText>
          </MenuItem>
        )}

        {/* Retry action */}
        {onRetry && (
          <MenuItem onClick={handleRetry}>
            <ListItemIcon>
              <RefreshIcon fontSize="small" />
            </ListItemIcon>
            <ListItemText>Retry analysis</ListItemText>
          </MenuItem>
        )}

        {/* Delete action (with divider) */}
        {onDelete && (
          <>
            <Divider />
            <MenuItem onClick={handleDelete} sx={{ color: "error.main" }}>
              <ListItemIcon>
                <DeleteIcon fontSize="small" color="error" />
              </ListItemIcon>
              <ListItemText>Delete message</ListItemText>
            </MenuItem>
          </>
        )}
      </Menu>
      <ConfirmationDialog {...dialogProps} />
    </>
  );
}

export default QuickActionMenu;

