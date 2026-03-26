/**
 * NotificationSnackbar component.
 *
 * Displays toast notifications from the UI store.
 */

"use client";

import React, { useEffect, useCallback } from "react";
import { Snackbar, Alert } from "@mui/material";
import { useUIStore } from "@/lib/store/uiStore";
import type { Notification } from "@/lib/store/uiStore";

/**
 * Notification snackbar component.
 *
 * Renders toast notifications with auto-dismiss.
 *
 * @returns Notification snackbar component
 *
 * @example
 * ```tsx
 * // Add to layout
 * <NotificationSnackbar />
 *
 * // Use in components
 * const { addNotification } = useUIStore();
 * addNotification({
 *   message: "Success!",
 *   type: "success",
 *   duration: 3000
 * });
 * ```
 */
export function NotificationSnackbar() {
  const notifications = useUIStore((s) => s.notifications);
  const removeNotification = useUIStore((s) => s.removeNotification);
  const [currentNotification, setCurrentNotification] =
    React.useState<Notification | null>(null);

  // Define handleClose with useCallback to prevent re-renders
  const handleClose = useCallback(() => {
    if (currentNotification) {
      removeNotification(currentNotification.id);
      setCurrentNotification(null);
    }
  }, [currentNotification, removeNotification]);

  // Show next notification in queue (using setTimeout to avoid setState in effect warning)
  useEffect(() => {
    if (notifications.length > 0 && !currentNotification) {
      // Use setTimeout to defer state update and avoid cascading renders
      const timer = setTimeout(() => {
        setCurrentNotification(notifications[0] ?? null);
      }, 0);
      return () => clearTimeout(timer);
    }
  }, [notifications, currentNotification]);

  // Auto-dismiss notification
  useEffect(() => {
    if (currentNotification) {
      const duration = currentNotification.duration || 5000;
      const timer = setTimeout(() => {
        handleClose();
      }, duration);
      return () => clearTimeout(timer);
    }
  }, [currentNotification, handleClose]);

  return (
    <Snackbar
      open={!!currentNotification}
      onClose={handleClose}
      anchorOrigin={{ vertical: "bottom", horizontal: "right" }}
    >
      {currentNotification ? (
        <Alert
          onClose={handleClose}
          severity={currentNotification.type}
          variant="filled"
          sx={{ width: "100%" }}
        >
          {currentNotification.message}
        </Alert>
      ) : undefined}
    </Snackbar>
  );
}

