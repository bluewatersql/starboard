/**
 * FileAttachmentChip component.
 *
 * Displays an attached file as a chip that can be clicked to preview.
 * Used in MessageInput to show pending attachments and in messages to show attached files.
 *
 * BB-05: Use a chip to display the user's uploaded file within the conversation/chat window.
 * Click the chip should allow the user to preview the file using the same experience as the file upload.
 */

"use client";

import React, { useState } from "react";
import { Box, Chip, Tooltip } from "@mui/material";
import InsertDriveFileIcon from "@mui/icons-material/InsertDriveFile";
import CloseIcon from "@mui/icons-material/Close";
import { FilePreviewDialog } from "./FilePreviewDialog";
import type { FileAttachment } from "./FileUploadButton";

interface FileAttachmentChipProps {
  /** File attachment data */
  attachment: FileAttachment;
  /** Whether to show the delete button */
  showDelete?: boolean;
  /** Callback when delete is clicked */
  onDelete?: () => void;
  /** Chip size */
  size?: "small" | "medium";
  /** Chip color */
  color?: "primary" | "secondary" | "default";
}

/**
 * Format bytes to human-readable size.
 */
function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`;
}

/**
 * FileAttachmentChip - Displays an attached file as a clickable chip.
 *
 * Clicking the chip opens a preview dialog with the file contents.
 *
 * @example
 * ```tsx
 * <FileAttachmentChip
 *   attachment={fileAttachment}
 *   showDelete
 *   onDelete={() => handleRemove()}
 * />
 * ```
 */
export function FileAttachmentChip({
  attachment,
  showDelete = false,
  onDelete,
  size = "small",
  color = "primary",
}: FileAttachmentChipProps) {
  const [previewOpen, setPreviewOpen] = useState(false);

  const handleClick = () => {
    setPreviewOpen(true);
  };

  const handleClose = () => {
    setPreviewOpen(false);
  };

  const sizeLabel = formatBytes(attachment.size);

  return (
    <>
      <Box sx={{ display: "inline-flex", alignItems: "center", gap: 0.5 }}>
        <Tooltip title="Click to preview file">
          <Chip
            icon={<InsertDriveFileIcon />}
            label={`${attachment.filename} (${sizeLabel})`}
            onClick={handleClick}
            onDelete={showDelete ? onDelete : undefined}
            deleteIcon={
              showDelete ? (
                <Tooltip title="Remove attachment">
                  <CloseIcon fontSize="small" />
                </Tooltip>
              ) : undefined
            }
            variant="outlined"
            color={attachment.isLargeFile ? "secondary" : color}
            size={size}
            sx={{
              maxWidth: 300,
              cursor: "pointer",
              "& .MuiChip-label": {
                overflow: "hidden",
                textOverflow: "ellipsis",
              },
            }}
          />
        </Tooltip>
        {attachment.isLargeFile && (
          <Chip
            label="Large file"
            size="small"
            color="info"
            sx={{ height: 20, fontSize: "0.7rem" }}
          />
        )}
      </Box>

      {/* Preview Dialog */}
      <FilePreviewDialog
        open={previewOpen}
        onClose={handleClose}
        filename={attachment.filename}
        content={attachment.content}
        size={attachment.size}
      />
    </>
  );
}

export default FileAttachmentChip;

