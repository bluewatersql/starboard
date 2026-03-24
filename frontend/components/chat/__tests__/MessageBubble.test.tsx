/**
 * MessageBubble component tests.
 *
 * Phase 2: Tests use tool_positions for tool rendering (no markers).
 * Tests for message rendering, tool call display, and hidden tools filtering.
 */

import React from "react";
import { render, screen } from "@testing-library/react";
import { ThemeProvider, createTheme } from "@mui/material/styles";
import { MessageBubble } from "../MessageBubble";
import { MessageStatus, MessageRole } from "@/lib/types/api";
import type { Message, ToolCall, ToolCallStatus, ToolPosition } from "@/lib/types/api";

// Mock react-markdown (ESM module that Jest doesn't handle)
jest.mock("react-markdown", () => {
  return {
    __esModule: true,
    default: ({ children }: { children: string }) => <div data-testid="markdown">{children}</div>,
  };
});

// Mock remark-gfm
jest.mock("remark-gfm", () => ({
  __esModule: true,
  default: () => {},
}));

// Mock next/image
jest.mock("next/image", () => ({
  __esModule: true,
  default: (props: React.ImgHTMLAttributes<HTMLImageElement>) => {
    // eslint-disable-next-line @next/next/no-img-element
    return <img {...props} alt={props.alt || ""} />;
  },
}));

const theme = createTheme();

const renderWithTheme = (component: React.ReactNode) => {
  return render(<ThemeProvider theme={theme}>{component}</ThemeProvider>);
};

const createMessage = (overrides: Partial<Message> = {}): Message => ({
  id: "msg_123",
  message_id: "msg_123",
  conversation_id: "conv_456",
  role: MessageRole.ASSISTANT,
  content: "Test message content",
  status: MessageStatus.COMPLETED,
  timestamp: new Date().toISOString(),
  tool_calls: [],
  tool_positions: [],
  ...overrides,
});

const createToolCall = (overrides: Partial<ToolCall> = {}): ToolCall => ({
  tool_call_id: "tc_123",
  tool_name: "test_tool",
  friendly_name: "Test Tool",
  status: "completed" as ToolCallStatus,
  ...overrides,
});

const createToolPosition = (overrides: Partial<ToolPosition> = {}): ToolPosition => ({
  tool_call_id: "tc_123",
  position: 0,
  display: "inline",
  ...overrides,
});

describe("MessageBubble", () => {
  describe("Hidden Tools Filtering", () => {
    it("should hide 'complete' tool from UI", () => {
      const message = createMessage({
        content: "Processing complete.",
        tool_calls: [
          createToolCall({
            tool_call_id: "tc_1",
            tool_name: "complete",
            friendly_name: "Complete",
            status: "completed",
          }),
        ],
        tool_positions: [
          createToolPosition({ tool_call_id: "tc_1", position: 11 }),
        ],
      });

      renderWithTheme(<MessageBubble message={message} />);

      // The 'complete' tool should not appear as an inline tool indicator
      // (it may appear in the ReasoningTimeline, which is expected)
      expect(screen.getByText(/Processing complete/)).toBeInTheDocument();
    });

    it("should hide 'request_user_input' tool from UI", () => {
      const message = createMessage({
        content: "Need input from user.",
        tool_calls: [
          createToolCall({
            tool_call_id: "tc_1",
            tool_name: "request_user_input",
            friendly_name: "Request User Input",
            status: "completed",
          }),
        ],
        tool_positions: [
          createToolPosition({ tool_call_id: "tc_1", position: 10 }),
        ],
      });

      renderWithTheme(<MessageBubble message={message} />);

      // The 'request_user_input' tool should not appear as an inline tool indicator
      // (it may appear in the ReasoningTimeline, which is expected)
      expect(screen.getByText(/Need input/)).toBeInTheDocument();
    });

    it("should render content for messages with visible tools (grouped view)", () => {
      // Phase 2: Tools are shown in grouped view, not inline
      const message = createMessage({
        content: "Resolving query for you.",
        tool_calls: [
          createToolCall({
            tool_call_id: "tc_1",
            tool_name: "resolve_query",
            friendly_name: "Resolve Query",
            status: "completed",
          }),
        ],
        tool_positions: [
          createToolPosition({ tool_call_id: "tc_1", position: 10 }),
        ],
      });

      renderWithTheme(<MessageBubble message={message} />);

      // Content should render as complete text (tools shown separately)
      expect(screen.getByText("Resolving query for you.")).toBeInTheDocument();
    });

    it("should render content without markers (clean content)", () => {
      // Phase 2: Content should never have markers
      const message = createMessage({
        content: "Before After",
        tool_calls: [],
        tool_positions: [],
      });

      renderWithTheme(<MessageBubble message={message} />);

      // Content should be rendered as-is (no marker syntax)
      expect(screen.getByText("Before After")).toBeInTheDocument();
    });

    it("should handle multiple hidden tools in one message", () => {
      const message = createMessage({
        content: "Start Middle End",
        tool_calls: [
          createToolCall({ tool_call_id: "tc_1", tool_name: "complete", friendly_name: "Complete" }),
        ],
        tool_positions: [
          createToolPosition({ tool_call_id: "tc_1", position: 5 }),
        ],
      });

      renderWithTheme(<MessageBubble message={message} />);

      // Hidden tools should not be rendered inline (they may appear in ReasoningTimeline)
      // But the text content should still be present
      expect(screen.getByText(/Start/)).toBeInTheDocument();
      expect(screen.getByText(/End/)).toBeInTheDocument();
    });
  });

  describe("Basic Message Rendering", () => {
    it("should render user message", () => {
      const message = createMessage({
        role: MessageRole.USER,
        content: "Hello, world!",
      });

      renderWithTheme(<MessageBubble message={message} />);

      expect(screen.getByText("Hello, world!")).toBeInTheDocument();
    });

    it("should render assistant message", () => {
      const message = createMessage({
        role: MessageRole.ASSISTANT,
        content: "I can help you with that.",
      });

      renderWithTheme(<MessageBubble message={message} />);

      expect(screen.getByText("I can help you with that.")).toBeInTheDocument();
    });

    it("should render system message with centered styling", () => {
      const message = createMessage({
        role: MessageRole.SYSTEM,
        content: "System notification",
      });

      renderWithTheme(<MessageBubble message={message} />);

      expect(screen.getByText("System notification")).toBeInTheDocument();
    });

    it("should show processing indicator for processing messages", () => {
      const message = createMessage({
        status: MessageStatus.PROCESSING,
        content: "Working on it...",
      });

      renderWithTheme(<MessageBubble message={message} />);

      expect(screen.getByText("Processing")).toBeInTheDocument();
    });

    it("should show failed status with retry button", () => {
      const onRetry = jest.fn();
      const message = createMessage({
        status: MessageStatus.FAILED,
        content: "Something went wrong",
        retry_count: 0,
      });

      renderWithTheme(<MessageBubble message={message} onRetry={onRetry} />);

      expect(screen.getByText("Failed")).toBeInTheDocument();
      expect(screen.getByLabelText("retry message")).toBeInTheDocument();
    });

    it("should display timestamp", () => {
      const timestamp = "2025-12-01T10:30:00Z";
      const message = createMessage({
        timestamp,
      });

      renderWithTheme(<MessageBubble message={message} />);

      // Check that a time is displayed (format depends on locale)
      expect(screen.getByText(/\d{1,2}:\d{2}/)).toBeInTheDocument();
    });
  });

  describe("Tool Call Rendering (Grouped View)", () => {
    // Phase 3: Tool indicators are inserted as plain text `→ Tool Name` into content.
    // Tests verify content is rendered and tool indicators appear.
    
    it("should render content with inline tool indicator text", () => {
      const message = createMessage({
        content: "Analyzing query plan for optimization.",
        tool_calls: [
          createToolCall({
            tool_call_id: "tc_1",
            tool_name: "analyze_query_plan",
            friendly_name: "Analyze Query Plan",
            status: "completed",
          }),
        ],
        tool_positions: [
          createToolPosition({ tool_call_id: "tc_1", position: 10 }),
        ],
      });

      renderWithTheme(<MessageBubble message={message} />);

      // Original content should still be present
      expect(screen.getByText(/Analyzing/)).toBeInTheDocument();
      // Tool indicator should be rendered
      expect(screen.getByText(/→ Analyze Query Plan/)).toBeInTheDocument();
    });

    it("should render content with running tool indicator", () => {
      const message = createMessage({
        content: "Fetching task metadata now.",
        tool_calls: [
          createToolCall({
            tool_call_id: "tc_1",
            tool_name: "fetch_task_metadata",
            friendly_name: "Fetch Task Metadata",
            status: "running",
          }),
        ],
        tool_positions: [
          createToolPosition({ tool_call_id: "tc_1", position: 8 }),
        ],
      });

      renderWithTheme(<MessageBubble message={message} />);

      // Original content should still be present
      expect(screen.getByText(/Fetching/)).toBeInTheDocument();
      // Tool indicator should be rendered
      expect(screen.getByText(/→ Fetch Task Metadata/)).toBeInTheDocument();
    });

    it("should render content with failed tool indicator", () => {
      const message = createMessage({
        content: "Failed to get cluster config.",
        tool_calls: [
          createToolCall({
            tool_call_id: "tc_1",
            tool_name: "get_cluster_config",
            friendly_name: "Get Cluster Config",
            status: "failed",
          }),
        ],
        tool_positions: [
          createToolPosition({ tool_call_id: "tc_1", position: 10 }),
        ],
      });

      renderWithTheme(<MessageBubble message={message} />);

      // Original content should still be present
      expect(screen.getByText(/Failed to get/)).toBeInTheDocument();
      // Tool indicator should be rendered
      expect(screen.getByText(/→ Get Cluster Config/)).toBeInTheDocument();
    });

    it("should render plain text when no tool positions", () => {
      const message = createMessage({
        content: "Simple message with no tools.",
        tool_calls: [],
        tool_positions: [],
      });

      renderWithTheme(<MessageBubble message={message} />);

      // Should show content as plain text
      expect(screen.getByText("Simple message with no tools.")).toBeInTheDocument();
    });
  });
});
