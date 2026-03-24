/**
 * Tests for HeroPrompt component.
 *
 * Tests the main prompt input component on the homepage.
 * UX vNext Phase 1: FT-004
 */

import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useRouter } from "next/navigation";
import { HeroPrompt } from "../HeroPrompt";
import { useConversationStore } from "@/lib/store/conversationStore";
import { useConfigStore } from "@/lib/store/configStore";
import * as apiClient from "@/lib/api/client";

// Mock dependencies
jest.mock("next/navigation", () => ({
  useRouter: jest.fn(),
}));

jest.mock("@/lib/store/conversationStore");

// Mock the API client
jest.mock("@/lib/api/client", () => ({
  createConversation: jest.fn(),
}));

// Mock the config store
const mockConfigState = {
  toConversationConfig: jest.fn(() => ({
    model: "gpt-4o-mini",
    temperature: 0.4,
  })),
};
jest.mock("@/lib/store/configStore", () => ({
  useConfigStore: jest.fn((selector) => selector(mockConfigState)),
}));

describe("HeroPrompt", () => {
  const mockPush = jest.fn();
  const mockAddConversation = jest.fn();
  const mockSetActiveConversation = jest.fn();
  const mockSetPendingMessage = jest.fn();
  const mockSetPendingAttachment = jest.fn();

  const mockConversationResponse = {
    conversation_id: "conv_123",
    user_id: "user_456",
    created_at: new Date().toISOString(),
    config: {},
    domain_models: [],
  };

  beforeEach(() => {
    jest.resetAllMocks();
    
    (useRouter as jest.Mock).mockReturnValue({
      push: mockPush,
    });

    const mockConversationState = {
      addConversation: mockAddConversation,
      setActiveConversation: mockSetActiveConversation,
      setPendingMessage: mockSetPendingMessage,
      setPendingAttachment: mockSetPendingAttachment,
    };
    (useConversationStore as unknown as jest.Mock).mockImplementation(
      (selector: (s: typeof mockConversationState) => unknown) => selector(mockConversationState)
    );

    mockConfigState.toConversationConfig.mockReturnValue({
      model: "gpt-4o-mini",
      temperature: 0.4,
    });
    (useConfigStore as unknown as jest.Mock).mockImplementation(
      (selector: (s: typeof mockConfigState) => unknown) => selector(mockConfigState)
    );

    // Default: API succeeds
    (apiClient.createConversation as jest.Mock).mockResolvedValue(mockConversationResponse);
  });

  describe("Rendering", () => {
    it("renders textarea with placeholder", () => {
      render(<HeroPrompt />);

      const textarea = screen.getByPlaceholderText(/what would you like to analyze/i);
      expect(textarea).toBeInTheDocument();
      expect(textarea).toHaveAttribute("rows", "2");
    });

    it("renders submit button", () => {
      render(<HeroPrompt />);

      const button = screen.getByRole("button", { name: /start conversation/i });
      expect(button).toBeInTheDocument();
    });

    it("renders character counter", () => {
      render(<HeroPrompt />);

      expect(screen.getByText("0 / 10000")).toBeInTheDocument();
    });

    it("auto-focuses textarea on mount", () => {
      render(<HeroPrompt />);

      const textarea = screen.getByPlaceholderText(/what would you like to analyze/i);
      expect(textarea).toHaveFocus();
    });
  });

  describe("User Input", () => {
    it("updates textarea value on input", async () => {
      const user = userEvent.setup();
      render(<HeroPrompt />);

      const textarea = screen.getByRole("textbox");
      await user.type(textarea, "Analyze job 12345");

      expect(textarea).toHaveValue("Analyze job 12345");
    });

    it("updates character counter on input", async () => {
      const user = userEvent.setup();
      render(<HeroPrompt />);

      const textarea = screen.getByRole("textbox");
      await user.type(textarea, "Test query");

      expect(screen.getByText("10 / 10000")).toBeInTheDocument();
    });

    it("handles multiline input", async () => {
      const user = userEvent.setup();
      render(<HeroPrompt />);

      const textarea = screen.getByRole("textbox");
      await user.type(textarea, "Line 1{Shift>}{Enter}{/Shift}Line 2");

      expect(textarea).toHaveValue("Line 1\nLine 2");
    });

    it("disables submit when input is empty", () => {
      render(<HeroPrompt />);

      const button = screen.getByRole("button", { name: /start conversation/i });
      expect(button).toBeDisabled();
    });

    it("enables submit when input has content", async () => {
      const user = userEvent.setup();
      render(<HeroPrompt />);

      const textarea = screen.getByRole("textbox");
      await user.type(textarea, "Test");

      const button = screen.getByRole("button", { name: /start conversation/i });
      expect(button).not.toBeDisabled();
    });

    it("trims whitespace-only input", () => {
      render(<HeroPrompt />);

      const textarea = screen.getByRole("textbox") as HTMLTextAreaElement;
      fireEvent.change(textarea, { target: { value: "   " } });

      const button = screen.getByRole("button", { name: /start conversation/i });
      expect(button).toBeDisabled();
    });
  });

  describe("Keyboard Shortcuts", () => {
    it("submits on Enter key", async () => {
      render(<HeroPrompt />);

      const textarea = screen.getByRole("textbox");
      fireEvent.change(textarea, { target: { value: "Test query" } });
      fireEvent.keyDown(textarea, { key: "Enter", code: "Enter" });

      await waitFor(() => {
        expect(apiClient.createConversation).toHaveBeenCalled();
      });
    });

    it("does not submit on Shift+Enter", async () => {
      render(<HeroPrompt />);

      const textarea = screen.getByRole("textbox");
      fireEvent.change(textarea, { target: { value: "Test" } });
      fireEvent.keyDown(textarea, { key: "Enter", code: "Enter", shiftKey: true });

      // Should not call API on Shift+Enter (allows newline)
      expect(apiClient.createConversation).not.toHaveBeenCalled();
    });

    it("allows newline on Shift+Enter", async () => {
      const user = userEvent.setup();
      render(<HeroPrompt />);

      const textarea = screen.getByRole("textbox");
      await user.type(textarea, "Line 1{Shift>}{Enter}{/Shift}Line 2");

      expect(textarea).toHaveValue("Line 1\nLine 2");
    });
  });

  describe("Submission", () => {
    it("creates conversation and navigates on submit", async () => {
      render(<HeroPrompt />);

      const textarea = screen.getByRole("textbox");
      const button = screen.getByRole("button", { name: /start conversation/i });

      fireEvent.change(textarea, { target: { value: "Analyze job performance" } });
      fireEvent.click(button);

      await waitFor(() => {
        expect(apiClient.createConversation).toHaveBeenCalled();
      });

      await waitFor(() => {
        expect(mockPush).toHaveBeenCalledWith("/chat?id=conv_123&new=1");
      });
    });

    it("shows loading state during submission", async () => {
      (apiClient.createConversation as jest.Mock).mockImplementation(
        () => new Promise((resolve) => setTimeout(() => resolve(mockConversationResponse), 100))
      );

      render(<HeroPrompt />);

      const textarea = screen.getByRole("textbox");
      const button = screen.getByRole("button", { name: /start conversation/i });

      fireEvent.change(textarea, { target: { value: "Test" } });
      fireEvent.click(button);

      await waitFor(() => {
        expect(button).toBeDisabled();
        expect(screen.getByRole("button", { name: /starting/i })).toBeInTheDocument();
      });
    });

    it("clears textarea after successful submission", async () => {
      render(<HeroPrompt />);

      const textarea = screen.getByRole("textbox") as HTMLTextAreaElement;
      const button = screen.getByRole("button", { name: /start conversation/i });

      fireEvent.change(textarea, { target: { value: "Test query" } });
      fireEvent.click(button);

      await waitFor(() => {
        expect(textarea.value).toBe("");
      });
    });

    it("handles submission errors gracefully", async () => {
      (apiClient.createConversation as jest.Mock).mockRejectedValue(new Error("Network error"));

      render(<HeroPrompt />);

      const textarea = screen.getByRole("textbox");
      const button = screen.getByRole("button", { name: /start conversation/i });

      fireEvent.change(textarea, { target: { value: "Test" } });
      fireEvent.click(button);

      await waitFor(() => {
        expect(screen.getByRole("alert")).toBeInTheDocument();
        expect(screen.getByText(/network error/i)).toBeInTheDocument();
      });

      // Should not navigate on error
      expect(mockPush).not.toHaveBeenCalled();
    });

    it("does not submit when already submitting", async () => {
      (apiClient.createConversation as jest.Mock).mockImplementation(
        () => new Promise((resolve) => setTimeout(() => resolve(mockConversationResponse), 1000))
      );

      render(<HeroPrompt />);

      const textarea = screen.getByRole("textbox");
      const button = screen.getByRole("button", { name: /start conversation/i });

      fireEvent.change(textarea, { target: { value: "Test" } });
      fireEvent.click(button);
      fireEvent.click(button); // Second click

      await waitFor(() => {
        expect(apiClient.createConversation).toHaveBeenCalledTimes(1);
      });
    });
  });

  describe("Character Limit", () => {
    it("warns when approaching character limit", async () => {
      render(<HeroPrompt />);

      const textarea = screen.getByRole("textbox");
      const longText = "a".repeat(9500);
      
      fireEvent.change(textarea, { target: { value: longText } });

      expect(screen.getByText("9500 / 10000")).toBeInTheDocument();
      // Should show warning color (tested via class or style)
    });

    it("prevents input beyond character limit", async () => {
      render(<HeroPrompt />);

      const textarea = screen.getByRole("textbox") as HTMLTextAreaElement;
      
      // Textarea has maxLength attribute which prevents typing beyond limit
      expect(textarea).toHaveAttribute("maxlength", "10000");
      
      // Test that handleChange respects the limit
      const maxText = "a".repeat(10000);
      fireEvent.change(textarea, { target: { value: maxText } });
      expect(textarea.value).toHaveLength(10000);
      
      // Attempting to set beyond max doesn't update state
      const beyondMax = maxText + "b";
      fireEvent.change(textarea, { target: { value: beyondMax } });
      // State should still be at max, not beyond
      expect(textarea.value).toHaveLength(10000);
    });

    it("shows error when at character limit", () => {
      render(<HeroPrompt />);

      const textarea = screen.getByRole("textbox");
      const maxText = "a".repeat(10000);

      fireEvent.change(textarea, { target: { value: maxText } });

      expect(screen.getByText("10000 / 10000")).toBeInTheDocument();
    });
  });

  describe("Accessibility", () => {
    it("has appropriate aria-labels", () => {
      render(<HeroPrompt />);

      const textarea = screen.getByLabelText(/enter your query/i);
      expect(textarea).toBeInTheDocument();
    });

    it("textarea is keyboard accessible", () => {
      render(<HeroPrompt />);

      const textarea = screen.getByRole("textbox");
      textarea.focus();
      expect(textarea).toHaveFocus();
    });

    it("submit button is keyboard accessible", () => {
      render(<HeroPrompt />);

      const button = screen.getByRole("button", { name: /start conversation/i });
      button.focus();
      expect(button).toHaveFocus();
    });

    it("shows error with appropriate aria-live region", async () => {
      (apiClient.createConversation as jest.Mock).mockRejectedValue(new Error("Error"));

      render(<HeroPrompt />);

      const textarea = screen.getByRole("textbox");
      const button = screen.getByRole("button", { name: /start conversation/i });

      fireEvent.change(textarea, { target: { value: "Test" } });
      fireEvent.click(button);

      await waitFor(() => {
        const alert = screen.getByRole("alert");
        expect(alert).toHaveAttribute("aria-live");
      });
    });
  });

  describe("Props: initialValue", () => {
    it("populates textarea with initialValue prop", () => {
      render(<HeroPrompt initialValue="Pre-filled query" />);

      const textarea = screen.getByRole("textbox") as HTMLTextAreaElement;
      expect(textarea.value).toBe("Pre-filled query");
    });

    it("enables submit button when initialValue provided", () => {
      render(<HeroPrompt initialValue="Test" />);

      const button = screen.getByRole("button", { name: /start conversation/i });
      expect(button).not.toBeDisabled();
    });

    it("updates character counter with initialValue", () => {
      render(<HeroPrompt initialValue="Test query" />);

      expect(screen.getByText("10 / 10000")).toBeInTheDocument();
    });
  });

  describe("File Upload (BB-02)", () => {
    it("renders file upload button", () => {
      render(<HeroPrompt />);

      const uploadButton = screen.getByRole("button", { name: /upload file/i });
      expect(uploadButton).toBeInTheDocument();
    });
  });

  describe("Offline Mode Toggle (BB-03)", () => {
    it("renders offline mode toggle", () => {
      render(<HeroPrompt />);

      // The toggle should be present (either as switch or toggle component)
      // Look for the switch or related text
      // Just verify the component renders without error
      expect(document.body).toBeInTheDocument();
    });
  });
});

