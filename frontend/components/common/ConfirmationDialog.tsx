/**
 * ConfirmationDialog component.
 *
 * A reusable MUI Dialog for confirming destructive or irreversible actions.
 * Supports severity levels (warning, error, info) to visually communicate risk.
 */

"use client";

import React from "react";
import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogContentText,
  DialogActions,
  Button,
} from "@mui/material";

export interface ConfirmationDialogProps {
  /** Whether the dialog is open */
  open: boolean;
  /** Dialog title */
  title: string;
  /** Dialog body message */
  message: string;
  /** Label for the confirm button (default: "Confirm") */
  confirmLabel?: string;
  /** Label for the cancel button (default: "Cancel") */
  cancelLabel?: string;
  /** Severity controls the confirm button color (default: "warning") */
  severity?: "warning" | "error" | "info";
  /** Called when the user clicks the confirm button */
  onConfirm: () => void;
  /** Called when the user clicks the cancel button or closes the dialog */
  onCancel: () => void;
}

/**
 * Modal confirmation dialog.
 *
 * @example
 * \`\`\`tsx
 * <ConfirmationDialog
 *   open={open}
 *   title="Delete message?"
 *   message="This action cannot be undone."
 *   severity="warning"
 *   onConfirm={handleConfirm}
 *   onCancel={handleCancel}
 * />
 * \`\`\`
 */
export function ConfirmationDialog({
  open,
  title,
  message,
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  severity = "warning",
  onConfirm,
  onCancel,
}: ConfirmationDialogProps) {
  return (
    <Dialog
      open={open}
      onClose={onCancel}
      aria-labelledby="confirmation-dialog-title"
      aria-describedby="confirmation-dialog-description"
    >
      <DialogTitle id="confirmation-dialog-title">{title}</DialogTitle>
      <DialogContent>
        <DialogContentText id="confirmation-dialog-description">
          {message}
        </DialogContentText>
      </DialogContent>
      <DialogActions>
        <Button onClick={onCancel}>{cancelLabel}</Button>
        <Button
          onClick={onConfirm}
          color={severity}
          variant="contained"
          autoFocus
        >
          {confirmLabel}
        </Button>
      </DialogActions>
    </Dialog>
  );
}

export default ConfirmationDialog;
