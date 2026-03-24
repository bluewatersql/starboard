"use client";

import React, { useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { useKeyboardShortcuts } from "@/lib/hooks/useKeyboardShortcuts";
import { ShortcutHelpModal } from "./ShortcutHelpModal";

interface KeyboardShortcutProviderProps {
  children: React.ReactNode;
  onSearch?: () => void;
  onSendMessage?: () => void;
  onCancel?: () => void;
}

export function KeyboardShortcutProvider({
  children,
  onSearch,
  onSendMessage,
  onCancel,
}: KeyboardShortcutProviderProps) {
  const router = useRouter();
  const [helpOpen, setHelpOpen] = useState(false);

  const handleNewChat = useCallback(() => {
    router.push("/chat");
  }, [router]);

  const handleShowHelp = useCallback(() => {
    setHelpOpen(true);
  }, []);

  const handleCancel = useCallback(() => {
    if (helpOpen) {
      setHelpOpen(false);
    } else {
      onCancel?.();
    }
  }, [helpOpen, onCancel]);

  useKeyboardShortcuts({
    onSearch,
    onNewChat: handleNewChat,
    onSendMessage,
    onCancel: handleCancel,
    onShowHelp: handleShowHelp,
  });

  return (
    <>
      {children}
      <ShortcutHelpModal open={helpOpen} onClose={() => setHelpOpen(false)} />
    </>
  );
}
