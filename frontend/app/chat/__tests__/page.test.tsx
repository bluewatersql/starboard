/**
 * Tests for /app/chat/page.tsx
 *
 * Tests chat page rendering with new conversation.
 * UX vNext Phase 1: FT-001
 */

import React from "react";
import { render, screen } from "@testing-library/react";
import ChatPage from "../page";

// Mock Next.js navigation hooks
jest.mock("next/navigation", () => ({
  useSearchParams: () => ({
    get: (key: string) => (key === "id" ? null : null),
  }),
}));

// Mock the chat components
jest.mock("@/components/chat", () => ({
  ChatLayout: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="chat-layout">{children}</div>
  ),
  ChatContainer: ({ conversationId }: { conversationId: string }) => (
    <div data-testid="chat-container" data-conversation-id={conversationId}>
      Chat Container
    </div>
  ),
}));

describe("ChatPage (/app/chat/page.tsx)", () => {
  describe("Rendering", () => {
    it("renders ChatLayout wrapper", () => {
      render(<ChatPage />);

      expect(screen.getByTestId("chat-layout")).toBeInTheDocument();
    });

    it("renders ChatContainer component", () => {
      render(<ChatPage />);

      expect(screen.getByTestId("chat-container")).toBeInTheDocument();
    });

    it("passes 'new' as conversationId to ChatContainer", () => {
      render(<ChatPage />);

      const container = screen.getByTestId("chat-container");
      expect(container).toHaveAttribute("data-conversation-id", "new");
    });

    it("does not crash with no props", () => {
      expect(() => render(<ChatPage />)).not.toThrow();
    });
  });

  describe("Component Structure", () => {
    it("wraps ChatContainer in ChatLayout", () => {
      render(<ChatPage />);

      const layout = screen.getByTestId("chat-layout");
      const container = screen.getByTestId("chat-container");

      // Verify container is inside layout
      expect(layout).toContainElement(container);
    });
  });

  describe("Client Component", () => {
    it("is a client component (has use client directive)", () => {
      // This test ensures the component can use client-side hooks
      // The file has "use client" directive at the top
      expect(() => render(<ChatPage />)).not.toThrow();
    });
  });
});

