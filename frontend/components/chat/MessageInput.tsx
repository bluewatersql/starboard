/**
 * MessageInput component.
 *
 * Text input field for composing and sending messages,
 * with support for multi-line input and keyboard shortcuts.
 */

"use client";

import React, { useState, useRef, KeyboardEvent } from "react";
import { Box, TextField, IconButton, CircularProgress, Paper, List, ListItemButton, ListItemText } from "@mui/material";
import SendIcon from "@mui/icons-material/Send";
import { useMutation } from "@tanstack/react-query";
import { api, RateLimitError } from "@/lib/api/client";
import { useMessageStore } from "@/lib/store/messageStore";
import { useUIStore } from "@/lib/store/uiStore";
import { useSlashCommands } from "@/lib/hooks/useSlashCommands";
import { MessageRole, MessageStatus } from "@/lib/types/api";
import type { Message } from "@/lib/types/api";
import type { FileAttachment as ApiFileAttachment } from "@/lib/types/generated-api";
import { FileUploadButton, FileAttachment } from "./FileUploadButton";
import { FileAttachmentChip } from "./FileAttachmentChip";

interface MessageInputProps {
  conversationId: string;
  disabled?: boolean;
  pendingMessage?: string | null;
  pendingAttachment?: FileAttachment | null;
  onPendingMessageSent?: () => void;
  onSendMessage?: (content: string, attachments?: FileAttachment[]) => Promise<void>;
}

/**
 * Message input component.
 *
 * Allows users to compose and send messages with keyboard shortcuts.
 * Supports Enter to send and Shift+Enter for newlines.
 *
 * @param props - Component props
 * @returns Message input component
 *
 * @example
 * ```tsx
 * <MessageInput conversationId="conv_123" />
 * ```
 */
export function MessageInput({
  conversationId,
  disabled = false,
  pendingMessage,
  pendingAttachment,
  onPendingMessageSent,
  onSendMessage,
}: MessageInputProps) {
  const [message, setMessage] = useState("");
  const [showCommands, setShowCommands] = useState(false);
  const [attachedFile, setAttachedFile] = useState<{ content: string; filename: string } | null>(null);
  const [largeFileAttachment, setLargeFileAttachment] = useState<FileAttachment | null>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const addMessage = useMessageStore((s) => s.addMessage);
  const setStreamingMessage = useMessageStore((s) => s.setStreamingMessage);
  const addNotification = useUIStore((s) => s.addNotification);
  const { executeCommand, getCommandSuggestions } = useSlashCommands(conversationId);
  const pendingMessageSentRef = useRef(false);
  const pendingAttachmentUsedRef = useRef(false);

  // Send message mutation (must be defined before useEffect that uses it)
  const sendMutation = useMutation({
    mutationFn: async (content: string) => {
      if (onSendMessage) {
        return onSendMessage(content);
      }
      return api.sendMessage(conversationId, { content });
    },
    onMutate: async (content) => {
      // Optimistic update: add user message immediately
      const tempId = `temp_${Date.now()}`;
      const userMessage: Message = {
        id: tempId,
        message_id: tempId,
        conversation_id: conversationId,
        trace_id: `trace_temp_${Date.now()}`,
        timestamp: new Date().toISOString(),
        role: MessageRole.USER,
        content,
        status: MessageStatus.PENDING,
      };
      addMessage(conversationId, userMessage);
      
      // Set streaming message ID to show typing indicator
      // Use a temporary ID that will be replaced when real response comes
      setStreamingMessage(`thinking_${Date.now()}`);
    },
    onSuccess: () => {
      // Message accepted by backend
      setMessage("");
      inputRef.current?.focus();
    },
    onError: (error) => {
      console.error("Failed to send message:", error);
      
      // Handle rate limit errors with retry information
      if (error instanceof RateLimitError) {
        const retryMessage = error.retryAfter 
          ? `Too many requests. Please wait ${error.retryAfter} seconds and try again.`
          : "Too many requests. Please wait a moment and try again.";
        addNotification({
          message: retryMessage,
          type: "warning",
          duration: error.retryAfter ? error.retryAfter * 1000 : 10000,
        });
        return;
      }
      
      addNotification({
        message:
          error instanceof Error ? error.message : "Failed to send message",
        type: "error",
        duration: 5000,
      });
    },
  });

  // Send pending message once (fixes race condition from homepage)
  // Must be AFTER sendMutation is defined
  React.useEffect(() => {
    // Reset the refs when conversation ID changes to allow sending pending message for new conversation
    pendingMessageSentRef.current = false;
    pendingAttachmentUsedRef.current = false;
  }, [conversationId]);

  // Handle pending attachment from hero prompt (BB-02 fix)
  React.useEffect(() => {
    if (pendingAttachment && !pendingAttachmentUsedRef.current) {
      pendingAttachmentUsedRef.current = true;
      // Set the attachment to show in the UI
      setLargeFileAttachment(pendingAttachment);
    }
  }, [pendingAttachment]);

  React.useEffect(() => {
    // Check if we have a pending message and it hasn't been sent yet
    if (pendingMessage && !pendingMessageSentRef.current && !sendMutation.isPending) {
      pendingMessageSentRef.current = true;
      
      // Build attachments array if we have a pending attachment
      const attachments: FileAttachment[] = [];
      if (pendingAttachment) {
        attachments.push(pendingAttachment);
      }

      // Add optimistic user message with attachment for chip display (BB-05)
      const tempId = `temp_${Date.now()}`;
      const userMessage: Message = {
        id: tempId,
        message_id: tempId,
        conversation_id: conversationId,
        trace_id: `trace_temp_${Date.now()}`,
        timestamp: new Date().toISOString(),
        role: MessageRole.USER,
        content: pendingMessage,
        status: MessageStatus.PENDING,
        // Include attachments for FileAttachmentChip display
        attachments: pendingAttachment ? [{
          filename: pendingAttachment.filename,
          size: pendingAttachment.size,
          content_preview: pendingAttachment.contentPreview,
          is_large_file: pendingAttachment.isLargeFile || false,
        }] : undefined,
      };
      addMessage(conversationId, userMessage);
      setStreamingMessage(`thinking_${Date.now()}`);
      
      // Send the message with attachments
      const sendPromise = onSendMessage && attachments.length > 0
        ? onSendMessage(pendingMessage, attachments)
        : api.sendMessage(conversationId, { 
            content: pendingMessage, 
            attachments: attachments.length > 0 ? (attachments as unknown as ApiFileAttachment[]) : undefined
          });
      
      sendPromise
        .then(() => {
          onPendingMessageSent?.();
          setLargeFileAttachment(null);
        })
        .catch((error) => {
          console.error("Failed to send pending message:", error);
          pendingMessageSentRef.current = false;
          addNotification({
            message: error instanceof Error ? error.message : "Failed to send message",
            type: "error",
            duration: 5000,
          });
        });
    }
  }, [pendingMessage, pendingAttachment, sendMutation.isPending, onPendingMessageSent, onSendMessage, conversationId, addNotification, addMessage, setStreamingMessage]);

  const handleSend = async () => {
    const trimmed = message.trim();
    if (!trimmed && !attachedFile && !largeFileAttachment) return;
    if (sendMutation.isPending) return;

    // Check if it's a slash command
    if (trimmed.startsWith("/") && !attachedFile && !largeFileAttachment) {
      const executed = await executeCommand(trimmed);
      if (executed) {
        setMessage("");
        setShowCommands(false);
        inputRef.current?.focus();
        return;
      }
    }

    // Handle large file attachments (sent separately from message content)
    if (largeFileAttachment) {
      const displayContent = trimmed || `Please analyze this file: ${largeFileAttachment.filename}`;
      const attachments: FileAttachment[] = [{
        filename: largeFileAttachment.filename,
        size: largeFileAttachment.size,
        content: largeFileAttachment.content,
        contentPreview: largeFileAttachment.contentPreview,
        isLargeFile: true,
      }];
      
      // Send with attachment metadata
      if (onSendMessage) {
        await onSendMessage(displayContent, attachments);
      } else {
        await api.sendMessage(conversationId, {
          content: displayContent,
          attachments: attachments as unknown as ApiFileAttachment[],
        });
      }
      
      // Add optimistic user message with attachment data for chip display
      const tempId = `temp_${Date.now()}`;
      const userMessage: Message = {
        id: tempId,
        message_id: tempId,
        conversation_id: conversationId,
        trace_id: `trace_temp_${Date.now()}`,
        timestamp: new Date().toISOString(),
        role: MessageRole.USER,
        content: displayContent,
        status: MessageStatus.PENDING,
        // Include attachments for FileAttachmentChip display (BB-05)
        attachments: [{
          filename: largeFileAttachment.filename,
          size: largeFileAttachment.size,
          content_preview: largeFileAttachment.contentPreview,
          is_large_file: true,
        }],
      };
      addMessage(conversationId, userMessage);
      setStreamingMessage(`thinking_${Date.now()}`);
      
      setMessage("");
      setLargeFileAttachment(null);
      inputRef.current?.focus();
      return;
    }

    // Build message content with small attached file (embedded)
    let fullContent = trimmed;
    if (attachedFile) {
      const fileHeader = `\n\n--- Attached File: ${attachedFile.filename} ---\n`;
      fullContent = trimmed 
        ? `${trimmed}${fileHeader}\n${attachedFile.content}`
        : `Please analyze this file:\n${fileHeader}\n${attachedFile.content}`;
    }

    sendMutation.mutate(fullContent, {
      onSuccess: () => {
        setAttachedFile(null);
      },
    });
  };

  const handleFileAttach = (content: string, filename: string) => {
    setAttachedFile({ content, filename });
    inputRef.current?.focus();
  };

  const handleLargeFileAttach = (attachment: FileAttachment) => {
    setLargeFileAttachment(attachment);
    inputRef.current?.focus();
  };

  const handleRemoveAttachment = () => {
    setAttachedFile(null);
    setLargeFileAttachment(null);
  };

  const handleInputChange = (value: string) => {
    setMessage(value);
    
    // Show command suggestions when typing "/"
    if (value.startsWith("/")) {
      const suggestions = getCommandSuggestions(value);
      setShowCommands(suggestions.length > 0);
    } else {
      setShowCommands(false);
    }
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    // Enter without Shift sends message
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const isDisabled = disabled || sendMutation.isPending;
  const commandSuggestions = getCommandSuggestions(message);

  return (
    <Box sx={{ position: "relative" }}>
      {/* Command Suggestions Popup */}
      {showCommands && commandSuggestions.length > 0 && (
        <Paper
          role="listbox"
          aria-label="Slash command suggestions"
          sx={{
            position: "absolute",
            bottom: "100%",
            left: 0,
            right: 0,
            mb: 1,
            maxHeight: 200,
            overflow: "auto",
            zIndex: 1000,
          }}
        >
          <List dense>
            {commandSuggestions.map((cmd) => (
              <ListItemButton
                key={cmd.name}
                role="option"
                aria-selected={message === cmd.name}
                onClick={() => {
                  setMessage(cmd.name);
                  setShowCommands(false);
                  inputRef.current?.focus();
                }}
              >
                <ListItemText
                  primary={cmd.name}
                  secondary={cmd.description}
                  primaryTypographyProps={{ fontWeight: 600 }}
                />
              </ListItemButton>
            ))}
          </List>
        </Paper>
      )}

      {/* Attached File Indicator (BB-05: Click to preview) */}
      {(attachedFile || largeFileAttachment) && (
        <Box sx={{ mb: 1, display: "flex", alignItems: "center", gap: 1 }}>
          <FileAttachmentChip
            attachment={
              largeFileAttachment || {
                filename: attachedFile!.filename,
                size: attachedFile!.content.length,
                content: attachedFile!.content,
                contentPreview: attachedFile!.content.slice(0, 500),
                isLargeFile: false,
              }
            }
            showDelete
            onDelete={handleRemoveAttachment}
          />
        </Box>
      )}

      <Box sx={{ display: "flex", gap: 1, alignItems: "flex-end" }}>
        {/* File Upload Button */}
        <FileUploadButton
          onFileContent={handleFileAttach}
          onFileAttachment={handleLargeFileAttach}
          disabled={isDisabled}
        />
        
        <TextField
          inputRef={inputRef}
          multiline
          maxRows={6}
          fullWidth
          placeholder={
            (attachedFile || largeFileAttachment)
              ? "Add a message (optional)..."
              : "Type a message... (Enter to send, / for commands)"
          }
          value={message}
          onChange={(e) => handleInputChange(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={isDisabled}
          variant="outlined"
          size="small"
          sx={{
            "& .MuiOutlinedInput-root": {
              paddingRight: 0,
            },
          }}
        />
        <IconButton
          color="primary"
          onClick={handleSend}
          disabled={isDisabled || (!message.trim() && !attachedFile && !largeFileAttachment)}
          aria-label="Send message"
          sx={{ mb: 0.5 }}
        >
          {sendMutation.isPending ? (
            <CircularProgress size={24} />
          ) : (
            <SendIcon />
          )}
        </IconButton>
      </Box>
    </Box>
  );
}
