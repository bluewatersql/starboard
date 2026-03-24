/**
 * FilePreviewDialog component.
 *
 * Reusable dialog for previewing file contents.
 * Used by FileUploadButton (during upload) and FileAttachmentChip (for viewing attached files).
 *
 * BB-05: Enables file preview from attachment chips in chat.
 */

"use client";

import React from "react";
import {
  Box,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  Typography,
  Paper,
  Chip,
  IconButton,
} from "@mui/material";
import InsertDriveFileIcon from "@mui/icons-material/InsertDriveFile";
import CloseIcon from "@mui/icons-material/Close";
import ContentCopyIcon from "@mui/icons-material/ContentCopy";
import { useTheme } from "@mui/material/styles";

interface FilePreviewDialogProps {
  /** Whether the dialog is open */
  open: boolean;
  /** Callback to close the dialog */
  onClose: () => void;
  /** Filename to display */
  filename: string;
  /** File content to preview */
  content: string;
  /** File size in bytes */
  size: number;
  /** Whether to show a confirm action (for upload flow) */
  showConfirmAction?: boolean;
  /** Callback when confirm is clicked (only used with showConfirmAction) */
  onConfirm?: () => void;
  /** Text for confirm button */
  confirmText?: string;
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
 * Detect file type from content and filename.
 */
function detectFileType(content: string, filename: string): string {
  const ext = filename.split(".").pop()?.toLowerCase() || "";

  const extMap: Record<string, string> = {
    log: "Log File",
    txt: "Text File",
    sql: "SQL",
    py: "Python",
    scala: "Scala",
    json: "JSON",
    xml: "XML",
    yaml: "YAML",
    yml: "YAML",
    csv: "CSV",
    md: "Markdown",
  };

  if (extMap[ext]) return extMap[ext];

  // By content patterns
  if (content.includes("java.lang.") || content.includes("Caused by:")) {
    return "Stack Trace";
  }
  if (content.match(/^\d{4}-\d{2}-\d{2}/m)) {
    return "Log File";
  }
  if (content.includes("SELECT") || content.includes("FROM")) {
    return "SQL";
  }
  if (content.includes("def ") || content.includes("import ")) {
    return "Python";
  }

  return "Text File";
}

/**
 * FilePreviewDialog - Reusable file preview dialog.
 *
 * @example
 * ```tsx
 * <FilePreviewDialog
 *   open={previewOpen}
 *   onClose={() => setPreviewOpen(false)}
 *   filename="error.log"
 *   content={fileContent}
 *   size={fileSize}
 * />
 * ```
 */
export function FilePreviewDialog({
  open,
  onClose,
  filename,
  content,
  size,
  showConfirmAction = false,
  onConfirm,
  confirmText = "Add to Message",
}: FilePreviewDialogProps) {
  const theme = useTheme();
  const [copied, setCopied] = React.useState(false);

  const fileType = detectFileType(content, filename);
  const lines = content.split("\n");
  const previewLines = lines.slice(0, 50);
  const totalLines = lines.length;
  const hasMore = totalLines > 50;

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(content);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (err) {
      console.error("Failed to copy:", err);
    }
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      maxWidth="md"
      fullWidth
      PaperProps={{
        sx: { maxHeight: "80vh" },
      }}
    >
      <DialogTitle sx={{ display: "flex", alignItems: "center", gap: 1 }}>
        <InsertDriveFileIcon color="primary" />
        <Box sx={{ flex: 1 }}>
          <Typography variant="h6" component="span">
            {filename}
          </Typography>
        </Box>
        <IconButton
          onClick={handleCopy}
          size="small"
          title={copied ? "Copied!" : "Copy to clipboard"}
          color={copied ? "success" : "default"}
        >
          <ContentCopyIcon fontSize="small" />
        </IconButton>
        <IconButton onClick={onClose} size="small">
          <CloseIcon />
        </IconButton>
      </DialogTitle>

      <DialogContent dividers>
        {/* File info chips */}
        <Box sx={{ display: "flex", gap: 1, mb: 2, flexWrap: "wrap" }}>
          <Chip label={fileType} size="small" color="primary" variant="outlined" />
          <Chip label={formatBytes(size)} size="small" variant="outlined" />
          <Chip label={`${totalLines} lines`} size="small" variant="outlined" />
        </Box>

        {/* Preview content */}
        <Typography variant="subtitle2" sx={{ mb: 1, fontWeight: 600 }}>
          {hasMore ? `Preview (first 50 of ${totalLines} lines)` : "Content"}
        </Typography>
        <Paper
          variant="outlined"
          sx={{
            p: 1.5,
            bgcolor:
              theme.palette.mode === "dark"
                ? "rgba(0, 0, 0, 0.3)"
                : "rgba(0, 0, 0, 0.03)",
            maxHeight: 400,
            overflow: "auto",
          }}
        >
          <Typography
            component="pre"
            sx={{
              m: 0,
              fontFamily: "monospace",
              fontSize: "0.8rem",
              lineHeight: 1.4,
              whiteSpace: "pre-wrap",
              wordBreak: "break-word",
            }}
          >
            {previewLines.join("\n")}
            {hasMore && (
              <Typography
                component="span"
                sx={{ color: "text.secondary", fontStyle: "italic" }}
              >
                {`\n... and ${totalLines - 50} more lines`}
              </Typography>
            )}
          </Typography>
        </Paper>
      </DialogContent>

      <DialogActions>
        <Button onClick={onClose}>{showConfirmAction ? "Cancel" : "Close"}</Button>
        {showConfirmAction && onConfirm && (
          <Button onClick={onConfirm} variant="contained">
            {confirmText}
          </Button>
        )}
      </DialogActions>
    </Dialog>
  );
}

export default FilePreviewDialog;

