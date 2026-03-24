/**
import { debug } from "../utils/debug";
 * useSlashCommands hook.
 *
 * Handles detection and execution of slash commands in chat input.
 */

import { useCallback, useMemo } from "react";
import { useMessageStore } from "../store/messageStore";
import { useUIStore } from "../store/uiStore";

export interface SlashCommand {
  name: string;
  description: string;
  execute: () => void | Promise<void>;
}

export function useSlashCommands(conversationId: string) {
  const getMessages = useMessageStore((s) => s.getMessages);
  const clearMessages = useMessageStore((s) => s.clearMessages);
  const addNotification = useUIStore((s) => s.addNotification);

  const commands: SlashCommand[] = useMemo(() => [
    {
      name: "/help",
      description: "Show available commands",
      execute: () => {
        addNotification({
          message: `Available commands:
/help - Show this help
/clear - Clear conversation
/export - Export conversation to JSON
/retry - Retry last message`,
          type: "info",
          duration: 8000,
        });
      },
    },
    {
      name: "/clear",
      description: "Clear current conversation",
      execute: async () => {
        if (confirm("Clear this conversation? This cannot be undone.")) {
          clearMessages(conversationId);
          addNotification({
            message: "Conversation cleared",
            type: "success",
            duration: 3000,
          });
        }
      },
    },
    {
      name: "/export",
      description: "Export conversation to JSON",
      execute: async () => {
        const messages = getMessages(conversationId);
        const data = {
          conversation_id: conversationId,
          exported_at: new Date().toISOString(),
          messages,
        };
        
        const blob = new Blob([JSON.stringify(data, null, 2)], {
          type: "application/json",
        });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `conversation-${conversationId}-${Date.now()}.json`;
        a.click();
        URL.revokeObjectURL(url);
        
        addNotification({
          message: "Conversation exported",
          type: "success",
          duration: 3000,
        });
      },
    },
    {
      name: "/retry",
      description: "Retry last message",
      execute: () => {
        // This would need to be handled by parent component
        addNotification({
          message: "Use the retry button on failed messages",
          type: "info",
          duration: 3000,
        });
      },
    },
  ], [conversationId, getMessages, clearMessages, addNotification]);

  const parseCommand = useCallback(
    (input: string): SlashCommand | null => {
      const trimmed = input.trim();
      if (!trimmed.startsWith("/")) return null;

      const commandName = trimmed.split(" ")[0].toLowerCase();
      return commands.find((cmd) => cmd.name === commandName) || null;
    },
    [commands]
  );

  const executeCommand = useCallback(
    async (input: string): Promise<boolean> => {
      const command = parseCommand(input);
      if (!command) return false;

      try {
        await command.execute();
        return true;
      } catch (error) {
        console.error("Command execution failed:", error);
        addNotification({
          message: "Command failed to execute",
          type: "error",
          duration: 3000,
        });
        return false;
      }
    },
    [parseCommand, addNotification]
  );

  const getCommandSuggestions = useCallback(
    (input: string): SlashCommand[] => {
      if (!input.startsWith("/")) return [];
      const query = input.slice(1).toLowerCase();
      return commands.filter((cmd) =>
        cmd.name.slice(1).startsWith(query)
      );
    },
    [commands]
  );

  return {
    commands,
    parseCommand,
    executeCommand,
    getCommandSuggestions,
  };
}

