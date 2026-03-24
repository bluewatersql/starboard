"use client";

import React, { useState } from "react";
import {
  IconButton,
  Menu,
  MenuItem,
  ListItemIcon,
  ListItemText,
  Tooltip,
} from "@mui/material";
import FileDownloadIcon from "@mui/icons-material/FileDownload";
import DescriptionIcon from "@mui/icons-material/Description";
import DataObjectIcon from "@mui/icons-material/DataObject";
import { api } from "@/lib/api/client";
import { useUIStore } from "@/lib/store/uiStore";

interface ExportMenuProps {
  conversationId: string;
}

/**
 * Trigger a browser file download from text content.
 */
function downloadFile(content: string, filename: string, mimeType: string) {
  const blob = new Blob([content], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

export function ExportMenu({ conversationId }: ExportMenuProps) {
  const [anchorEl, setAnchorEl] = useState<null | HTMLElement>(null);
  const { addNotification } = useUIStore();
  const open = Boolean(anchorEl);

  const handleExport = async (format: "markdown" | "json") => {
    setAnchorEl(null);
    try {
      const content = await api.exportConversation(conversationId, format);
      const ext = format === "json" ? "json" : "md";
      const mime = format === "json" ? "application/json" : "text/markdown";
      downloadFile(content, `conversation_${conversationId}.${ext}`, mime);
      addNotification({
        message: `Conversation exported as ${format.toUpperCase()}`,
        type: "success",
        duration: 3000,
      });
    } catch (error) {
      console.error("Export failed:", error);
      addNotification({
        message: "Failed to export conversation",
        type: "error",
        duration: 5000,
      });
    }
  };

  return (
    <>
      <Tooltip title="Export conversation">
        <IconButton
          size="small"
          onClick={(e) => setAnchorEl(e.currentTarget)}
          aria-label="Export conversation"
        >
          <FileDownloadIcon fontSize="small" />
        </IconButton>
      </Tooltip>
      <Menu
        anchorEl={anchorEl}
        open={open}
        onClose={() => setAnchorEl(null)}
      >
        <MenuItem onClick={() => handleExport("markdown")}>
          <ListItemIcon>
            <DescriptionIcon fontSize="small" />
          </ListItemIcon>
          <ListItemText>Export as Markdown</ListItemText>
        </MenuItem>
        <MenuItem onClick={() => handleExport("json")}>
          <ListItemIcon>
            <DataObjectIcon fontSize="small" />
          </ListItemIcon>
          <ListItemText>Export as JSON</ListItemText>
        </MenuItem>
      </Menu>
    </>
  );
}
