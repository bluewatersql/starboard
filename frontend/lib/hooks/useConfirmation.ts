/**
 * useConfirmation hook.
 *
 * Provides a programmatic API for showing a ConfirmationDialog and
 * awaiting the user's choice as a Promise<boolean>.
 *
 * @example
 * \`\`\`tsx
 * const { confirm, dialogProps } = useConfirmation();
 *
 * const handleDelete = async () => {
 *   const confirmed = await confirm({
 *     title: "Delete item?",
 *     message: "This cannot be undone.",
 *     severity: "warning",
 *   });
 *   if (confirmed) deleteItem();
 * };
 *
 * return (
 *   <>
 *     <button onClick={handleDelete}>Delete</button>
 *     <ConfirmationDialog {...dialogProps} />
 *   </>
 * );
 * \`\`\`
 */

import { useState, useCallback, useRef } from "react";
import type { ConfirmationDialogProps } from "@/components/common/ConfirmationDialog";

export interface ConfirmOptions {
  /** Dialog title */
  title: string;
  /** Dialog body message */
  message: string;
  /** Label for the confirm button */
  confirmLabel?: string;
  /** Label for the cancel button */
  cancelLabel?: string;
  /** Severity controls confirm button color */
  severity?: "warning" | "error" | "info";
}

export interface UseConfirmationReturn {
  /**
   * Show the confirmation dialog with the given options.
   * Returns a Promise that resolves to true (confirmed) or false (cancelled).
   */
  confirm: (options: ConfirmOptions) => Promise<boolean>;
  /**
   * Props to spread directly onto a <ConfirmationDialog /> element.
   */
  dialogProps: ConfirmationDialogProps;
}

/**
 * Hook for programmatic confirmation dialogs.
 *
 * @returns confirm function and dialogProps to spread onto ConfirmationDialog
 */
export function useConfirmation(): UseConfirmationReturn {
  const [open, setOpen] = useState(false);
  const [options, setOptions] = useState<ConfirmOptions>({
    title: "",
    message: "",
  });

  // Holds the resolve function for the current pending Promise
  const resolveRef = useRef<((value: boolean) => void) | null>(null);

  const confirm = useCallback((opts: ConfirmOptions): Promise<boolean> => {
    setOptions(opts);
    setOpen(true);

    return new Promise<boolean>((resolve) => {
      resolveRef.current = resolve;
    });
  }, []);

  const handleConfirm = useCallback(() => {
    setOpen(false);
    resolveRef.current?.(true);
    resolveRef.current = null;
  }, []);

  const handleCancel = useCallback(() => {
    setOpen(false);
    resolveRef.current?.(false);
    resolveRef.current = null;
  }, []);

  const dialogProps: ConfirmationDialogProps = {
    open,
    title: options.title,
    message: options.message,
    confirmLabel: options.confirmLabel,
    cancelLabel: options.cancelLabel,
    severity: options.severity,
    onConfirm: handleConfirm,
    onCancel: handleCancel,
  };

  return { confirm, dialogProps };
}

export default useConfirmation;
