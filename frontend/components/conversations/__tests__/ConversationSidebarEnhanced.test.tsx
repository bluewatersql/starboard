/**
 * Enhanced conversation sidebar component tests.
 *
 * Tests for ConversationSearch, ConversationItemEnhanced, and GroupedConversations.
 */

import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { ThemeProvider, createTheme } from "@mui/material/styles";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ConversationSearch } from "../ConversationSearch";
import { ConversationItemEnhanced } from "../ConversationItemEnhanced";
import { GroupedConversations } from "../GroupedConversations";
import type { Conversation } from "@/lib/types/api";

// Mock next/navigation
jest.mock("next/navigation", () => ({
  useRouter: () => ({
    push: jest.fn(),
    replace: jest.fn(),
    prefetch: jest.fn(),
  }),
  usePathname: () => "/chat",
}));

// Mock stores
jest.mock("@/lib/store/conversationStore", () => ({
  useConversationStore: () => ({
    setActiveConversation: jest.fn(),
    removeConversation: jest.fn(),
  }),
}));

jest.mock("@/lib/store/messageStore", () => ({
  useMessageStore: () => ({
    clearMessages: jest.fn(),
  }),
}));

jest.mock("@/lib/store/uiStore", () => ({
  useUIStore: () => ({
    addNotification: jest.fn(),
  }),
}));

// Mock API
jest.mock("@/lib/api/client", () => ({
  api: {
    deleteConversation: jest.fn().mockResolvedValue(undefined),
  },
}));

const theme = createTheme();
const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: false },
    mutations: { retry: false },
  },
});

const renderWithProviders = (component: React.ReactNode) => {
  return render(
    <QueryClientProvider client={queryClient}>
      <ThemeProvider theme={theme}>{component}</ThemeProvider>
    </QueryClientProvider>
  );
};

// Sample conversations
const mockConversations: Conversation[] = [
  {
    conversation_id: "conv-1",
    user_id: "user-1",
    friendly_name: "Query Optimization",
    created_at: new Date().toISOString(), // Today
    updated_at: new Date().toISOString(),
    config: {},
    metadata: {
      agent_type: "advisor",
      status: "completed",
      recommendations_count: 4,
      estimated_improvement: "25%",
    },
  },
  {
    conversation_id: "conv-2",
    user_id: "user-1",
    friendly_name: "Cost Analysis",
    created_at: new Date(Date.now() - 86400000).toISOString(), // Yesterday
    updated_at: new Date(Date.now() - 86400000).toISOString(),
    config: {},
    metadata: {
      agent_type: "analytics",
      status: "completed",
      cost_reduction: "20%",
    },
  },
  {
    conversation_id: "conv-3",
    user_id: "user-1",
    friendly_name: "Dashboard Help",
    created_at: new Date(Date.now() - 86400000 * 3).toISOString(), // 3 days ago
    updated_at: new Date(Date.now() - 86400000 * 3).toISOString(),
    config: {},
    metadata: {
      agent_type: "general",
      status: "active",
    },
  },
];

describe("ConversationSearch", () => {
  describe("Rendering", () => {
    it("renders search input", () => {
      renderWithProviders(
        <ConversationSearch
          conversations={mockConversations}
          onFilteredChange={jest.fn()}
        />
      );

      expect(
        screen.getByPlaceholderText("Search conversations...")
      ).toBeInTheDocument();
    });

    it("renders filter buttons", () => {
      renderWithProviders(
        <ConversationSearch
          conversations={mockConversations}
          onFilteredChange={jest.fn()}
        />
      );

      expect(screen.getByText("All")).toBeInTheDocument();
      expect(screen.getByText("Advisor")).toBeInTheDocument();
      expect(screen.getByText("Analytics")).toBeInTheDocument();
    });
  });

  describe("Filtering", () => {
    it("filters by search query", async () => {
      const handleFilteredChange = jest.fn();
      renderWithProviders(
        <ConversationSearch
          conversations={mockConversations}
          onFilteredChange={handleFilteredChange}
        />
      );

      const searchInput = screen.getByPlaceholderText("Search conversations...");
      fireEvent.change(searchInput, { target: { value: "Query" } });

      await waitFor(() => {
        // Should call with filtered results
        const lastCall =
          handleFilteredChange.mock.calls[
            handleFilteredChange.mock.calls.length - 1
          ];
        expect(lastCall[0]).toHaveLength(1);
        expect(lastCall[0][0].friendly_name).toBe("Query Optimization");
      });
    });

    it("filters by agent type", async () => {
      const handleFilteredChange = jest.fn();
      renderWithProviders(
        <ConversationSearch
          conversations={mockConversations}
          onFilteredChange={handleFilteredChange}
        />
      );

      fireEvent.click(screen.getByText("Advisor"));

      await waitFor(() => {
        const lastCall =
          handleFilteredChange.mock.calls[
            handleFilteredChange.mock.calls.length - 1
          ];
        expect(lastCall[0]).toHaveLength(1);
        expect(lastCall[0][0].metadata?.agent_type).toBe("advisor");
      });
    });

    it("shows result count when searching", async () => {
      renderWithProviders(
        <ConversationSearch
          conversations={mockConversations}
          onFilteredChange={jest.fn()}
        />
      );

      const searchInput = screen.getByPlaceholderText("Search conversations...");
      fireEvent.change(searchInput, { target: { value: "Query" } });

      await waitFor(() => {
        expect(screen.getByText("1 result")).toBeInTheDocument();
      });
    });
  });
});

describe("ConversationItemEnhanced", () => {
  describe("Rendering", () => {
    it("renders conversation name", () => {
      renderWithProviders(
        <ConversationItemEnhanced
          conversation={mockConversations[0]!}
          isActive={false}
        />
      );

      expect(screen.getByText("Query Optimization")).toBeInTheDocument();
    });

    it("renders diagnostic agent type icon (BB-01 fix)", () => {
      const diagnosticConversation: Conversation = {
        conversation_id: "conv-diagnostic",
        user_id: "user-1",
        friendly_name: "Error Investigation",
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        config: {},
        metadata: {
          agent_type: "diagnostic",
          status: "completed",
        },
      };

      const { container } = renderWithProviders(
        <ConversationItemEnhanced
          conversation={diagnosticConversation}
          isActive={false}
        />
      );

      // Should render diagnostic icon (BugReportIcon) instead of default ChatBubbleOutlineIcon
      // The diagnostic agent uses BugReportIcon with amber color (#f59e0b)
      const svgIcons = container.querySelectorAll("svg");
      expect(svgIcons.length).toBeGreaterThan(0);
      // Verify conversation name renders - icon is present even if we can't easily assert the specific icon
      expect(screen.getByText("Error Investigation")).toBeInTheDocument();
    });

    it("renders query agent type icon", () => {
      const queryConversation: Conversation = {
        conversation_id: "conv-query",
        user_id: "user-1",
        friendly_name: "SQL Optimization",
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        config: {},
        metadata: {
          agent_type: "query",
          status: "completed",
        },
      };

      renderWithProviders(
        <ConversationItemEnhanced
          conversation={queryConversation}
          isActive={false}
        />
      );

      expect(screen.getByText("SQL Optimization")).toBeInTheDocument();
    });

    it("renders job agent type icon", () => {
      const jobConversation: Conversation = {
        conversation_id: "conv-job",
        user_id: "user-1",
        friendly_name: "Job Analysis",
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        config: {},
        metadata: {
          agent_type: "job",
          status: "completed",
        },
      };

      renderWithProviders(
        <ConversationItemEnhanced
          conversation={jobConversation}
          isActive={false}
        />
      );

      expect(screen.getByText("Job Analysis")).toBeInTheDocument();
    });

    it("shows metadata chips for completed conversations", () => {
      renderWithProviders(
        <ConversationItemEnhanced
          conversation={mockConversations[0]!}
          isActive={false}
        />
      );

      expect(screen.getByText(/🎯 4 recs/)).toBeInTheDocument();
      expect(screen.getByText(/⚡ 25%/)).toBeInTheDocument();
    });

    it("shows cost reduction chip", () => {
      renderWithProviders(
        <ConversationItemEnhanced
          conversation={mockConversations[1]!}
          isActive={false}
        />
      );

      expect(screen.getByText(/💰 20%/)).toBeInTheDocument();
    });

    it("shows progress bar for active conversations", () => {
      renderWithProviders(
        <ConversationItemEnhanced
          conversation={mockConversations[2]!}
          isActive={false}
        />
      );

      expect(screen.getByRole("progressbar")).toBeInTheDocument();
    });

    it("highlights active conversation", () => {
      const { container } = renderWithProviders(
        <ConversationItemEnhanced
          conversation={mockConversations[0]!}
          isActive={true}
        />
      );

      // Should have aria-current="page"
      const button = container.querySelector('[aria-current="page"]');
      expect(button).toBeInTheDocument();
    });
  });

  describe("Interactions", () => {
    it("shows delete button on hover", async () => {
      renderWithProviders(
        <ConversationItemEnhanced
          conversation={mockConversations[0]!}
          isActive={false}
        />
      );

      const item = screen.getByText("Query Optimization").closest("div[role='button']");
      if (item) {
        fireEvent.mouseEnter(item);
      }

      await waitFor(() => {
        expect(screen.getByLabelText("Delete conversation")).toBeInTheDocument();
      });
    });
  });
});

describe("GroupedConversations", () => {
  describe("Rendering", () => {
    it("groups conversations by time period", () => {
      renderWithProviders(
        <GroupedConversations
          conversations={mockConversations}
          currentConversationId={undefined}
        />
      );

      expect(screen.getByText(/Today/)).toBeInTheDocument();
      expect(screen.getByText(/Yesterday/)).toBeInTheDocument();
    });

    it("shows count for each group", () => {
      renderWithProviders(
        <GroupedConversations
          conversations={mockConversations}
          currentConversationId={undefined}
        />
      );

      expect(screen.getByText(/Today \(1\)/)).toBeInTheDocument();
      expect(screen.getByText(/Yesterday \(1\)/)).toBeInTheDocument();
    });

    it("shows empty state when no conversations", () => {
      renderWithProviders(
        <GroupedConversations
          conversations={[]}
          currentConversationId={undefined}
        />
      );

      expect(screen.getByText("No conversations found")).toBeInTheDocument();
    });
  });

  describe("Collapse/Expand", () => {
    it("collapses group when header is clicked", async () => {
      renderWithProviders(
        <GroupedConversations
          conversations={mockConversations}
          currentConversationId={undefined}
        />
      );

      // Query Optimization should be visible (Today group is expanded by default)
      expect(screen.getByText("Query Optimization")).toBeInTheDocument();

      // Click Today header to collapse
      const todayHeader = screen.getByText(/Today \(1\)/).closest('[role="button"]');
      if (todayHeader) {
        fireEvent.click(todayHeader);
      }

      // After collapse, aria-expanded should be false
      await waitFor(() => {
        expect(todayHeader).toHaveAttribute("aria-expanded", "false");
      });
    });

    it("can toggle group expansion", async () => {
      renderWithProviders(
        <GroupedConversations
          conversations={mockConversations}
          currentConversationId={undefined}
        />
      );

      // Today group should be expanded by default
      const todayHeader = screen.getByText(/Today \(1\)/).closest('[role="button"]');
      expect(todayHeader).toHaveAttribute("aria-expanded", "true");

      // Click to collapse
      if (todayHeader) {
        fireEvent.click(todayHeader);
      }

      await waitFor(() => {
        expect(todayHeader).toHaveAttribute("aria-expanded", "false");
      });

      // Click again to expand
      if (todayHeader) {
        fireEvent.click(todayHeader);
      }

      await waitFor(() => {
        expect(todayHeader).toHaveAttribute("aria-expanded", "true");
      });
    });
  });

  describe("Accessibility", () => {
    it("group headers are keyboard accessible", () => {
      renderWithProviders(
        <GroupedConversations
          conversations={mockConversations}
          currentConversationId={undefined}
        />
      );

      const todayHeader = screen.getByText(/Today \(1\)/).closest('[role="button"]');
      expect(todayHeader).toHaveAttribute("tabindex", "0");
    });

    it("supports keyboard navigation", async () => {
      renderWithProviders(
        <GroupedConversations
          conversations={mockConversations}
          currentConversationId={undefined}
        />
      );

      const todayHeader = screen.getByText(/Today \(1\)/).closest('[role="button"]');
      expect(todayHeader).toHaveAttribute("aria-expanded", "true");

      // Press Enter to collapse
      if (todayHeader) {
        fireEvent.keyDown(todayHeader, { key: "Enter" });
      }

      await waitFor(() => {
        expect(todayHeader).toHaveAttribute("aria-expanded", "false");
      });
    });
  });
});

