/**
 * useKeyboardShortcuts - Global keyboard shortcut registration.
 *
 * Thin wrapper around react-hotkeys-hook that binds application-level
 * keyboard shortcuts to caller-provided callbacks.
 */

import { useHotkeys } from "react-hotkeys-hook";

export interface KeyboardShortcutCallbacks {
  onSearch?: () => void;
  onNewChat?: () => void;
  onSendMessage?: () => void;
  onCancel?: () => void;
  onShowHelp?: () => void;
}

export function useKeyboardShortcuts(callbacks: KeyboardShortcutCallbacks) {
  useHotkeys("mod+k", (e) => {
    e.preventDefault();
    callbacks.onSearch?.();
  }, { enableOnFormTags: false });

  useHotkeys("mod+n", (e) => {
    e.preventDefault();
    callbacks.onNewChat?.();
  }, { enableOnFormTags: false });

  useHotkeys("mod+enter", (e) => {
    e.preventDefault();
    callbacks.onSendMessage?.();
  }, { enableOnFormTags: true }); // Allow in textarea for sending

  useHotkeys("escape", () => {
    callbacks.onCancel?.();
  });

  useHotkeys("shift+/", () => {
    callbacks.onShowHelp?.();
  }, { enableOnFormTags: false }); // ? key = shift+/
}
