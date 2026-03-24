/**
 * Tests for ConversationList component.
 */

import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ConversationList } from "../ConversationList";
import { useConversationStore } from "@/lib/store/conversationStore";
import { api } from "@/lib/api/client";

// Mock dependencies
jest.mock("@/lib/store/conversationStore");
jest.mock("@/lib/api/client");

// Setup mock for getState
const mockIsNewlyCreated = jest.fn().mockReturnValue(false);
(useConversationStore as unknown as { getState: () => { isNewlyCreated: jest.Mock } }).getState = () => ({
  isNewlyCreated: mockIsNewlyCreated,
});

// Mock ConversationItem
jest.mock("../ConversationItem", () => ({
  ConversationItem: ({ conversation }: { conversation: { conversation_id: string } }) => (
    <div data-testid={`conversation-${conversation.conversation_id}`}>
      {conversation.conversation_id}
    </div>
  ),
}));

// Mock ConversationListSkeleton
jest.mock("../ConversationListSkeleton", () => ({
  ConversationListSkeleton: () => <div data-testid="skeleton">Loading...</div>,
}));

/** Helper: make useConversationStore behave as a selector-based hook */
function mockConversationStoreWith(state: {
  conversations: unknown[];
  activeConversationId: string | null;
  setConversations: jest.Mock;
}) {
  (useConversationStore as unknown as jest.Mock).mockImplementation(
    (selector: (s: typeof state) => unknown) => selector(state)
  );
}

describe("ConversationList", () => {
  let queryClient: QueryClient;

  const mockConversations = [
    {
      conversation_id: "conv1",
      user_id: "user1",
      created_at: "2024-01-01T00:00:00Z",
      friendly_name: "Test Conversation 1",
    },
    {
      conversation_id: "conv2",
      user_id: "user1",
      created_at: "2024-01-02T00:00:00Z",
      friendly_name: "Test Conversation 2",
    },
  ];

  beforeEach(() => {
    jest.clearAllMocks();
    mockIsNewlyCreated.mockReturnValue(false);

    queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    });

    // Default mock implementations
    mockConversationStoreWith({
      conversations: [],
      activeConversationId: null,
      setConversations: jest.fn(),
    });

    (api.listConversations as jest.Mock).mockResolvedValue(mockConversations);
  });

  afterEach(() => {
    queryClient.clear();
  });

  const renderWithProvider = (component: React.ReactElement) => {
    return render(
      <QueryClientProvider client={queryClient}>
        {component}
      </QueryClientProvider>
    );
  };

  describe("Loading States", () => {
    it("shows skeleton when loading with no cached data", async () => {
      mockConversationStoreWith({
        conversations: [], // No cached data
        activeConversationId: null,
        setConversations: jest.fn(),
      });

      (api.listConversations as jest.Mock).mockImplementation(
        () => new Promise(() => {}) // Never resolves
      );

      renderWithProvider(<ConversationList />);

      expect(screen.getByTestId("skeleton")).toBeInTheDocument();
    });

    it("shows cached data immediately without skeleton", async () => {
      mockConversationStoreWith({
        conversations: mockConversations, // Cached data exists
        activeConversationId: null,
        setConversations: jest.fn(),
      });

      renderWithProvider(<ConversationList />);

      // Should NOT show skeleton (cached data renders instantly)
      expect(screen.queryByTestId("skeleton")).not.toBeInTheDocument();

      // Should show conversations from cache
      expect(screen.getByTestId("conversation-conv1")).toBeInTheDocument();
      expect(screen.getByTestId("conversation-conv2")).toBeInTheDocument();
    });
  });

  describe("Data Fetching", () => {
    it("fetches and displays conversations from API", async () => {
      const setConversations = jest.fn();

      mockConversationStoreWith({
        conversations: [], // No cache - should fetch from API
        activeConversationId: null,
        setConversations,
      });

      renderWithProvider(<ConversationList />);

      // Should show skeleton while loading (no cached data)
      expect(screen.getByTestId("skeleton")).toBeInTheDocument();

      // Wait for store to be updated with server data
      await waitFor(() => {
        expect(setConversations).toHaveBeenCalled();
      });

      // Verify API was called
      expect(api.listConversations).toHaveBeenCalled();
    });

    it("uses cached data as initialData for instant render", async () => {
      const cachedData = [mockConversations[0]];

      mockConversationStoreWith({
        conversations: cachedData,
        activeConversationId: null,
        setConversations: jest.fn(),
      });

      renderWithProvider(<ConversationList />);

      // Should show cached data immediately (no skeleton)
      expect(screen.queryByTestId("skeleton")).not.toBeInTheDocument();
      expect(screen.getByTestId("conversation-conv1")).toBeInTheDocument();
    });

    it("syncs server data to store", async () => {
      const setConversations = jest.fn();

      mockConversationStoreWith({
        conversations: mockConversations, // Need cache for immediate render
        activeConversationId: null,
        setConversations,
      });

      renderWithProvider(<ConversationList />);

      await waitFor(() => {
        expect(setConversations).toHaveBeenCalled();
      }, { timeout: 3000 });
    });
  });

  describe("Empty States", () => {
    it("shows empty state when no conversations", async () => {
      (api.listConversations as jest.Mock).mockResolvedValue([]);

      renderWithProvider(<ConversationList />);

      await waitFor(() => {
        expect(screen.getByText(/no conversations yet/i)).toBeInTheDocument();
      });
    });

    it("shows no results message when search has no matches", async () => {
      const { fireEvent } = await import("@testing-library/react");

      mockConversationStoreWith({
        conversations: mockConversations, // Provide cached data
        activeConversationId: null,
        setConversations: jest.fn(),
      });

      renderWithProvider(<ConversationList />);

      // Conversations should appear immediately
      expect(screen.getByTestId("conversation-conv1")).toBeInTheDocument();

      const searchInput = screen.getByPlaceholderText(/search conversations/i);

      // Type search query that won't match
      fireEvent.change(searchInput, { target: { value: "nonexistent" } });

      await waitFor(() => {
        expect(screen.getByText(/no conversations found/i)).toBeInTheDocument();
      });
    });
  });

  describe("Search Functionality", () => {
    it("renders search input", async () => {
      mockConversationStoreWith({
        conversations: mockConversations,
        activeConversationId: null,
        setConversations: jest.fn(),
      });

      renderWithProvider(<ConversationList />);

      expect(screen.getByPlaceholderText(/search conversations/i)).toBeInTheDocument();
    });

    it("filters conversations by search query", async () => {
      const { fireEvent } = await import("@testing-library/react");

      mockConversationStoreWith({
        conversations: mockConversations, // Provide cached data
        activeConversationId: null,
        setConversations: jest.fn(),
      });

      renderWithProvider(<ConversationList />);

      // With cached data, conversations appear immediately
      expect(screen.getByTestId("conversation-conv1")).toBeInTheDocument();
      expect(screen.getByTestId("conversation-conv2")).toBeInTheDocument();

      const searchInput = screen.getByPlaceholderText(/search conversations/i);

      fireEvent.change(searchInput, { target: { value: "conv1" } });

      // Should show only conv1
      expect(screen.getByTestId("conversation-conv1")).toBeInTheDocument();
      expect(screen.queryByTestId("conversation-conv2")).not.toBeInTheDocument();
    });
  });
});
