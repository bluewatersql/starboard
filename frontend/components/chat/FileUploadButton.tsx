/**
 * FileUploadButton component.
 *
 * Allows users to upload files (logs, code, etc.) for diagnostic analysis.
 * Supports large files (>10KB) with preview and size display.
 */

"use client";

import React, { useRef, useState } from "react";
import {
  Box,
  IconButton,
  Tooltip,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  Typography,
  Paper,
  Chip,
  LinearProgress,
  Alert,
} from "@mui/material";
import AttachFileIcon from "@mui/icons-material/AttachFile";
import InsertDriveFileIcon from "@mui/icons-material/InsertDriveFile";
import CloseIcon from "@mui/icons-material/Close";
import { useTheme } from "@mui/material/styles";

/**
 * Threshold for treating files as "large" and sending as attachments.
 * Large files are processed by the diagnostic agent for incremental discovery.
 */
const LARGE_FILE_THRESHOLD = 50 * 1024; // 50KB

/**
 * File attachment data for large files.
 */
export interface FileAttachment {
  /** Original filename */
  filename: string;
  /** File size in bytes */
  size: number;
  /** Full file content */
  content: string;
  /** First 500 chars for display */
  contentPreview: string;
  /** True if file exceeds large file threshold */
  isLargeFile: boolean;
}

interface FileUploadButtonProps {
  /** Called when a small file is selected and confirmed (content embedded in message) */
  onFileContent: (content: string, filename: string) => void;
  /** Called when a large file is selected and confirmed (sent as attachment) */
  onFileAttachment?: (attachment: FileAttachment) => void;
  /** Whether the button is disabled */
  disabled?: boolean;
  /** Maximum file size in bytes (default: 15MB) */
  maxSizeBytes?: number;
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
 * Detect file type from content.
 */
function detectFileType(content: string, filename: string): string {
  const ext = filename.split(".").pop()?.toLowerCase() || "";
  
  // By extension
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
 * File upload button component.
 */
export function FileUploadButton({
  onFileContent,
  onFileAttachment,
  disabled = false,
  maxSizeBytes = 15 * 1024 * 1024, // 15MB default
}: FileUploadButtonProps) {
  const theme = useTheme();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [fileContent, setFileContent] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleClick = () => {
    fileInputRef.current?.click();
  };

  const handleFileChange = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;

    // Reset state
    setError(null);
    setSelectedFile(file);
    setLoading(true);

    // Check file size
    if (file.size > maxSizeBytes) {
      setError(`File too large. Maximum size is ${formatBytes(maxSizeBytes)}.`);
      setFileContent(""); // Clear content since we won't read the file
      setDialogOpen(true); // Open dialog to show the error
      setLoading(false);
      // Reset input to allow re-selecting a different file
      event.target.value = "";
      return;
    }

    // Read file content
    try {
      const content = await file.text();
      setFileContent(content);
      setDialogOpen(true);
    } catch (err) {
      setError("Failed to read file. Please try a different file.");
      setDialogOpen(true); // Open dialog to show the error
      console.error("File read error:", err);
    } finally {
      setLoading(false);
      // Reset input to allow re-selecting the same file
      event.target.value = "";
    }
  };

  const handleConfirm = () => {
    if (selectedFile && fileContent) {
      const isLargeFile = selectedFile.size >= LARGE_FILE_THRESHOLD;

      if (isLargeFile && onFileAttachment) {
        // Large files are sent as attachments for diagnostic processing
        onFileAttachment({
          filename: selectedFile.name,
          size: selectedFile.size,
          content: fileContent,
          contentPreview: fileContent.slice(0, 500),
          isLargeFile: true,
        });
      } else {
        // Small files are embedded directly in the message
        onFileContent(fileContent, selectedFile.name);
      }
      handleClose();
    }
  };

  const handleClose = () => {
    setDialogOpen(false);
    setSelectedFile(null);
    setFileContent("");
    setError(null);
  };

  const fileType = selectedFile ? detectFileType(fileContent, selectedFile.name) : "";
  const previewLines = fileContent.split("\n").slice(0, 20);
  const hasMore = fileContent.split("\n").length > 20;

  return (
    <>
      <input
        ref={fileInputRef}
        type="file"
        accept=".txt,.log,.sql,.py,.scala,.json,.xml,.yaml,.yml,.csv,.md,text/*"
        style={{ display: "none" }}
        onChange={handleFileChange}
      />
      
      <Tooltip title="Upload file (logs, code, errors)">
        <IconButton
          onClick={handleClick}
          disabled={disabled || loading}
          color="default"
          size="small"
        >
          <AttachFileIcon />
        </IconButton>
      </Tooltip>

      {/* Preview Dialog */}
      <Dialog
        open={dialogOpen}
        onClose={handleClose}
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
              {selectedFile?.name}
            </Typography>
          </Box>
          <IconButton onClick={handleClose} size="small">
            <CloseIcon />
          </IconButton>
        </DialogTitle>

        <DialogContent dividers>
          {error && (
            <Alert severity="error" sx={{ mb: 2 }}>
              {error}
            </Alert>
          )}

          {selectedFile && (
            <>
              {/* File info chips */}
              <Box sx={{ display: "flex", gap: 1, mb: 2, flexWrap: "wrap" }}>
                {fileContent && (
                  <Chip
                    label={fileType}
                    size="small"
                    color="primary"
                    variant="outlined"
                  />
                )}
                <Chip
                  label={formatBytes(selectedFile.size)}
                  size="small"
                  variant="outlined"
                  color={error ? "error" : "default"}
                />
                {fileContent && (
                  <Chip
                    label={`${fileContent.split("\n").length} lines`}
                    size="small"
                    variant="outlined"
                  />
                )}
              </Box>

              {/* Preview - only show if we have content */}
              {fileContent && (
                <>
                  <Typography variant="subtitle2" sx={{ mb: 1, fontWeight: 600 }}>
                    Preview (first 20 lines)
                  </Typography>
                  <Paper
                    variant="outlined"
                    sx={{
                      p: 1.5,
                      bgcolor: theme.palette.mode === "dark"
                        ? "rgba(0, 0, 0, 0.3)"
                        : "rgba(0, 0, 0, 0.03)",
                      maxHeight: 300,
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
                          {"\n... and {fileContent.split('\\n').length - 20} more lines"}
                        </Typography>
                      )}
                    </Typography>
                  </Paper>

                  {/* Size notice for large files */}
                  {selectedFile.size >= LARGE_FILE_THRESHOLD && (
                    <Alert severity="info" sx={{ mt: 2 }}>
                      Large file detected ({formatBytes(selectedFile.size)}). 
                      {onFileAttachment 
                        ? " The file will be processed by the diagnostic agent for efficient analysis."
                        : " The file will be added to your message for analysis."}
                    </Alert>
                  )}
                </>
              )}

              {/* Help text when file is too large */}
              {error && !fileContent && (
                <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
                  Please select a smaller file or split the content into multiple parts.
                </Typography>
              )}
            </>
          )}
        </DialogContent>

        <DialogActions>
          <Button onClick={handleClose}>Cancel</Button>
          <Button
            onClick={handleConfirm}
            variant="contained"
            disabled={!fileContent || !!error}
          >
            Add to Message
          </Button>
        </DialogActions>
      </Dialog>

      {/* Loading indicator */}
      {loading && (
        <Box sx={{ position: "absolute", bottom: 0, left: 0, right: 0 }}>
          <LinearProgress />
        </Box>
      )}
    </>
  );
}

