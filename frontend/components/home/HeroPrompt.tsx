/**
 * HeroPrompt - Main prompt input component for homepage.
 *
 * Large, centered textarea for entering queries with:
 * - Auto-focus on mount
 * - Enter to submit, Shift+Enter for newline
 * - Character counter (0/10000)
 * - Submit button with loading state
 * - Integration with createAndNavigate
 * - File upload support (BB-02)
 * - Offline mode toggle (BB-03)
 *
 * UX vNext Phase 1: FT-004
 */

"use client";

import React from "react";
import { useRouter } from "next/navigation";
import {
  Box,
  TextField,
  Button,
  Typography,
  Alert,
  CircularProgress,
} from "@mui/material";
import SendIcon from "@mui/icons-material/Send";
import { useConversationStore } from "@/lib/store/conversationStore";
import { createConversation } from "@/lib/api/client";
import { useConfigStore } from "@/lib/store/configStore";
import { FileUploadButton, type FileAttachment } from "@/components/chat/FileUploadButton";
import { FileAttachmentChip } from "@/components/chat/FileAttachmentChip";
import { OfflineModeToggle } from "@/components/chat/OfflineModeToggle";

interface HeroPromptProps {
  /**
   * Optional initial value to populate the textarea.
   * Used when clicking example queries.
   */
  initialValue?: string;
}

const MAX_CHARS = 10000;
const WARNING_THRESHOLD = 9000;

export function HeroPrompt({ initialValue = "" }: HeroPromptProps) {
  const router = useRouter();
  const setPendingMessage = useConversationStore((s) => s.setPendingMessage);
  const setPendingAttachment = useConversationStore((s) => s.setPendingAttachment);
  const addConversation = useConversationStore((s) => s.addConversation);
  const removeNewlyCreated = useConversationStore((s) => s.removeNewlyCreated);
  const setActiveConversation = useConversationStore((s) => s.setActiveConversation);
  const toConversationConfig = useConfigStore((s) => s.toConversationConfig);
  
  const [value, setValue] = React.useState(initialValue);
  const [isSubmitting, setIsSubmitting] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [attachedFile, setAttachedFile] = React.useState<FileAttachment | null>(null);
  const textareaRef = React.useRef<HTMLTextAreaElement>(null);

  // Auto-focus on mount
  React.useEffect(() => {
    textareaRef.current?.focus();
  }, []);

  // Update value when initialValue prop changes (e.g., from example query click)
  React.useEffect(() => {
    if (initialValue) {
      setValue(initialValue);
    }
  }, [initialValue]);

  const charCount = value.length;
  const isOverWarningThreshold = charCount > WARNING_THRESHOLD;
  const isAtLimit = charCount >= MAX_CHARS;
  // Allow submit if text is entered OR file is attached
  const canSubmit = (value.trim().length > 0 || attachedFile !== null) && !isSubmitting;

  // File attachment handlers
  const handleFileContent = (content: string, filename: string) => {
    setAttachedFile({
      filename,
      size: content.length,
      content,
      contentPreview: content.slice(0, 500),
      isLargeFile: false,
    });
  };

  const handleLargeFileAttach = (attachment: FileAttachment) => {
    setAttachedFile(attachment);
  };

  const handleRemoveFile = () => {
    setAttachedFile(null);
  };

  const handleChange = (event: React.ChangeEvent<HTMLTextAreaElement>) => {
    const newValue = event.target.value;
    
    // Enforce character limit
    if (newValue.length <= MAX_CHARS) {
      setValue(newValue);
      setError(null); // Clear errors on new input
    }
  };

  const handleKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    // Submit on Enter (without Shift)
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault(); // Prevent newline
      handleSubmit();
    }
    // Allow newline on Shift+Enter (default behavior)
  };

  const handleSubmit = async () => {
    const trimmedValue = value.trim();
    
    // Allow submit if text or file is present
    if ((!trimmedValue && !attachedFile) || isSubmitting) {
      return;
    }

    try {
      setIsSubmitting(true);
      setError(null);

      // 1. Create conversation immediately
      const config = toConversationConfig();
      const conversation = await createConversation({ 
        config,
        context: { source: "web-ui" }
      });

      // 2. Add to store (ensure user_id is set)
      addConversation({
        ...conversation,
        user_id: conversation.user_id || "anonymous",
      });
      // Schedule cleanup of newly-created tracking after 30 seconds
      setTimeout(() => removeNewlyCreated(conversation.conversation_id), 30000);
      setActiveConversation(conversation.conversation_id);

      // 3. Set pending message to be sent by ChatContainer
      // If we have an attachment, include a reference to it in the message
      const messageText = attachedFile 
        ? (trimmedValue || `Analyze the attached file: ${attachedFile.filename}`)
        : trimmedValue;
      setPendingMessage(messageText);

      // 4. Set pending attachment if present
      if (attachedFile) {
        setPendingAttachment(attachedFile);
      }

      // 5. Clear textarea and attachment
      setValue("");
      setAttachedFile(null);

      // 6. Navigate to the new conversation page (using query params for static export)
      // ChatContainer will pick up the pending message and attachment
      // Add 'new=1' param to signal SSE should skip validation (conversation was just created)
      router.push(`/chat?id=${conversation.conversation_id}&new=1`);
    } catch (err) {
      const errorMessage =
        err instanceof Error ? err.message : "Failed to start conversation";
      setError(errorMessage);
      setIsSubmitting(false);
    }
  };

  return (
    <Box
      sx={{
        width: "100%",
        maxWidth: 800,
        mx: "auto",
      }}
    >
      {/* Error Alert */}
      {error && (
        <Alert
          severity="error"
          onClose={() => setError(null)}
          sx={{ mb: 2 }}
          role="alert"
          aria-live="assertive"
        >
          {error}
        </Alert>
      )}

      {/* Attached File Display (BB-05: Click to preview) */}
      {attachedFile && (
        <Box sx={{ mb: 2 }}>
          <FileAttachmentChip
            attachment={attachedFile}
            showDelete
            onDelete={handleRemoveFile}
          />
        </Box>
      )}

      {/* Main Input Area with File Upload */}
      <Box sx={{ display: "flex", gap: 1, alignItems: "flex-start", mb: 2 }}>
        {/* File Upload Button */}
        <FileUploadButton
          onFileContent={handleFileContent}
          onFileAttachment={handleLargeFileAttach}
          disabled={isSubmitting}
        />

        {/* Main Textarea */}
        <TextField
          inputRef={textareaRef}
          multiline
          rows={2}
          fullWidth
          value={value}
          onChange={handleChange}
          onKeyDown={handleKeyDown}
          placeholder={
            attachedFile
              ? "Add a message about the file (optional)..."
              : "What would you like to analyze? (e.g., 'Analyze job performance for job 12345')"
          }
          disabled={isSubmitting}
          label="Enter your query"
          sx={{
            "& .MuiOutlinedInput-root": {
              fontSize: "1.125rem",
              lineHeight: 1.6,
            },
          }}
          InputProps={{
            sx: {
              backgroundColor: "background.paper",
            },
          }}
          inputProps={{
            "aria-label": "Enter your query or question",
            maxLength: MAX_CHARS,
          }}
        />
      </Box>

      {/* Controls Row: Character Counter, Offline Toggle, Submit Button */}
      <Box
        sx={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          gap: 2,
        }}
      >
        {/* Character Counter */}
        <Typography
          variant="body2"
          color={isAtLimit ? "error" : isOverWarningThreshold ? "warning.main" : "text.secondary"}
          sx={{ fontVariantNumeric: "tabular-nums" }}
        >
          {charCount} / {MAX_CHARS}
        </Typography>

        {/* Offline Mode Toggle (BB-03) */}
        <Box sx={{ flex: 1, display: "flex", justifyContent: "center" }}>
          <OfflineModeToggle compact />
        </Box>

        {/* Submit Button */}
        <Button
          variant="contained"
          size="large"
          onClick={handleSubmit}
          disabled={!canSubmit}
          startIcon={isSubmitting ? <CircularProgress size={20} /> : <SendIcon />}
          sx={{
            minWidth: 200,
            textTransform: "none",
            fontSize: "1rem",
          }}
        >
          {isSubmitting ? "Starting..." : "Start Conversation"}
        </Button>
      </Box>

      {/* Hint Text */}
      <Typography
        variant="caption"
        color="text.secondary"
        sx={{ display: "block", mt: 1, textAlign: "center" }}
      >
        Press Enter to submit, Shift+Enter for new line
      </Typography>
    </Box>
  );
}

