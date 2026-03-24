/**
 * Action components tests.
 *
 * Tests for InlineActions, QuickActionMenu, and StatusBadge.
 */

import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { ThemeProvider, createTheme } from "@mui/material/styles";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { InlineActions, ActionConfig } from "../InlineActions";
import { QuickActionMenu } from "../QuickActionMenu";
import { StatusBadge } from "../StatusBadge";
import DeleteIcon from "@mui/icons-material/Delete";

// Mock clipboard API
const mockWriteText = jest.fn().mockResolvedValue(undefined);
Object.assign(navigator, {
  clipboard: {
    writeText: mockWriteText,
  },
});

// Mock the UI store
const mockUIState = {
  addNotification: jest.fn(),
  removeNotification: jest.fn(),
  notifications: [],
};
jest.mock("@/lib/store/uiStore", () => ({
  useUIStore: (selector: (s: typeof mockUIState) => unknown) => selector(mockUIState),
}));

const theme = createTheme();

const renderWithTheme = (component: React.ReactNode) => {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        gcTime: 0,
        staleTime: 0,
      },
      mutations: {
        retry: false,
      },
    },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <ThemeProvider theme={theme}>{component}</ThemeProvider>
    </QueryClientProvider>
  );
};

describe("InlineActions", () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  describe("Rendering", () => {
    it("renders default actions", () => {
      renderWithTheme(
        <InlineActions
          recommendationId="rec-123"
          onAction={jest.fn()}
        />
      );

      expect(screen.getByText("Mark as Applied")).toBeInTheDocument();
      expect(screen.getByText("Explain More")).toBeInTheDocument();
      expect(screen.getByText("Skip")).toBeInTheDocument();
    });

    it("renders copy SQL button when sqlCode is provided", () => {
      renderWithTheme(
        <InlineActions
          recommendationId="rec-123"
          onAction={jest.fn()}
          sqlCode="SELECT * FROM table"
        />
      );

      expect(screen.getByText("Copy SQL")).toBeInTheDocument();
    });

    it("hides copy SQL button when no sqlCode", () => {
      renderWithTheme(
        <InlineActions
          recommendationId="rec-123"
          onAction={jest.fn()}
        />
      );

      expect(screen.queryByText("Copy SQL")).not.toBeInTheDocument();
    });
  });

  describe("Action Handling", () => {
    it("calls onAction when button is clicked", async () => {
      const handleAction = jest.fn().mockResolvedValue(undefined);
      renderWithTheme(
        <InlineActions
          recommendationId="rec-123"
          onAction={handleAction}
        />
      );

      fireEvent.click(screen.getByText("Mark as Applied"));

      await waitFor(
        () => {
          expect(handleAction).toHaveBeenCalledWith(
            "mark_applied",
            "rec-123",
            undefined
          );
        },
        { timeout: 3000 }
      );
    });

    it("copies SQL to clipboard without calling onAction", async () => {
      const handleAction = jest.fn();
      renderWithTheme(
        <InlineActions
          recommendationId="rec-123"
          onAction={handleAction}
          sqlCode="SELECT * FROM users"
        />
      );

      fireEvent.click(screen.getByText("Copy SQL"));

      await waitFor(() => {
        expect(mockWriteText).toHaveBeenCalledWith("SELECT * FROM users");
        expect(handleAction).not.toHaveBeenCalled();
      });
    });

    it("shows 'Copied!' after copying SQL", async () => {
      renderWithTheme(
        <InlineActions
          recommendationId="rec-123"
          onAction={jest.fn()}
          sqlCode="SELECT 1"
        />
      );

      fireEvent.click(screen.getByText("Copy SQL"));

      await waitFor(() => {
        expect(screen.getByText("Copied!")).toBeInTheDocument();
      });
    });

    it("shows confirmation dialog for actions with confirmRequired", async () => {
      const customActions: ActionConfig[] = [
        {
          id: "delete",
          label: "Delete",
          icon: DeleteIcon,
          variant: "danger",
          confirmRequired: true,
          confirmMessage: "Delete this recommendation?",
        },
      ];

      const handleAction = jest.fn();
      renderWithTheme(
        <InlineActions
          recommendationId="rec-123"
          actions={customActions}
          onAction={handleAction}
        />
      );

      fireEvent.click(screen.getByText("Delete"));

      await waitFor(() => {
        expect(screen.getByText("Delete this recommendation?")).toBeInTheDocument();
      });
    });

    it("does not call onAction if confirmation is cancelled", async () => {
      const customActions: ActionConfig[] = [
        {
          id: "delete",
          label: "Delete",
          icon: DeleteIcon,
          confirmRequired: true,
        },
      ];

      const handleAction = jest.fn();
      renderWithTheme(
        <InlineActions
          recommendationId="rec-123"
          actions={customActions}
          onAction={handleAction}
        />
      );

      fireEvent.click(screen.getByText("Delete"));

      // Wait for dialog then cancel
      await waitFor(() => {
        expect(screen.getByText("Cancel")).toBeInTheDocument();
      });
      fireEvent.click(screen.getByText("Cancel"));

      expect(handleAction).not.toHaveBeenCalled();
    });
  });

  describe("Applied State", () => {
    it("shows 'Applied' after action is completed", async () => {
      const handleAction = jest.fn().mockResolvedValue(undefined);
      renderWithTheme(
        <InlineActions
          recommendationId="rec-123"
          onAction={handleAction}
        />
      );

      fireEvent.click(screen.getByText("Mark as Applied"));

      await waitFor(() => {
        expect(screen.getByText("Applied")).toBeInTheDocument();
      });
    });

    it("disables button after action is applied", async () => {
      const handleAction = jest.fn().mockResolvedValue(undefined);
      renderWithTheme(
        <InlineActions
          recommendationId="rec-123"
          onAction={handleAction}
        />
      );

      fireEvent.click(screen.getByText("Mark as Applied"));

      await waitFor(() => {
        const button = screen.getByText("Applied").closest("button");
        expect(button).toBeDisabled();
      });
    });
  });

  describe("Compact Mode", () => {
    it("renders icon-only buttons in compact mode", () => {
      renderWithTheme(
        <InlineActions
          recommendationId="rec-123"
          onAction={jest.fn()}
          compact
        />
      );

      // Should not have text labels in compact mode
      expect(screen.queryByText("Mark as Applied")).not.toBeInTheDocument();
      // But should have tooltips (aria-label)
      expect(screen.getByLabelText("Mark as Applied")).toBeInTheDocument();
    });
  });
});

describe("QuickActionMenu", () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  describe("Rendering", () => {
    it("renders menu button", () => {
      renderWithTheme(
        <QuickActionMenu
          content="Test message"
        />
      );

      expect(screen.getByLabelText("Open actions menu")).toBeInTheDocument();
    });

    it("returns null when no actions are available", () => {
      const { container } = renderWithTheme(
        <QuickActionMenu />
      );

      expect(container.firstChild).toBeNull();
    });
  });

  describe("Menu Actions", () => {
    it("opens menu when button is clicked", async () => {
      renderWithTheme(
        <QuickActionMenu
          content="Test message"
        />
      );

      fireEvent.click(screen.getByLabelText("Open actions menu"));

      await waitFor(() => {
        expect(screen.getByText("Copy message")).toBeInTheDocument();
      });
    });

    it("copies content to clipboard", async () => {
      renderWithTheme(
        <QuickActionMenu
          content="Test message content"
        />
      );

      fireEvent.click(screen.getByLabelText("Open actions menu"));
      
      await waitFor(() => {
        expect(screen.getByText("Copy message")).toBeInTheDocument();
      });
      
      fireEvent.click(screen.getByText("Copy message"));

      await waitFor(() => {
        expect(mockWriteText).toHaveBeenCalledWith("Test message content");
      });
    });

    it("calls onShare when share is clicked", async () => {
      const handleShare = jest.fn();
      renderWithTheme(
        <QuickActionMenu
          content="Test"
          onShare={handleShare}
        />
      );

      fireEvent.click(screen.getByLabelText("Open actions menu"));
      
      await waitFor(() => {
        expect(screen.getByText("Share message")).toBeInTheDocument();
      });
      
      fireEvent.click(screen.getByText("Share message"));

      expect(handleShare).toHaveBeenCalled();
    });

    it("calls onRetry when retry is clicked", async () => {
      const handleRetry = jest.fn();
      renderWithTheme(
        <QuickActionMenu
          content="Test"
          onRetry={handleRetry}
        />
      );

      fireEvent.click(screen.getByLabelText("Open actions menu"));
      
      await waitFor(() => {
        expect(screen.getByText("Retry analysis")).toBeInTheDocument();
      });
      
      fireEvent.click(screen.getByText("Retry analysis"));

      expect(handleRetry).toHaveBeenCalled();
    });

    it("shows confirmation dialog before delete", async () => {
      const handleDelete = jest.fn();
      renderWithTheme(
        <QuickActionMenu
          content="Test"
          onDelete={handleDelete}
        />
      );

      fireEvent.click(screen.getByLabelText("Open actions menu"));

      await waitFor(() => {
        expect(screen.getByText("Delete message")).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText("Delete message"));

      await waitFor(() => {
        expect(screen.getByText("Delete message?")).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText("Confirm"));

      await waitFor(() => {
        expect(handleDelete).toHaveBeenCalled();
      });
    });
  });
});

describe("StatusBadge", () => {
  describe("Rendering", () => {
    it("renders completed status", () => {
      renderWithTheme(<StatusBadge status="completed" />);

      expect(screen.getByText("Completed")).toBeInTheDocument();
    });

    it("renders in_progress status", () => {
      renderWithTheme(<StatusBadge status="in_progress" />);

      expect(screen.getByText("In Progress")).toBeInTheDocument();
    });

    it("renders skipped status", () => {
      renderWithTheme(<StatusBadge status="skipped" />);

      expect(screen.getByText("Skipped")).toBeInTheDocument();
    });

    it("does not render not_started by default", () => {
      const { container } = renderWithTheme(
        <StatusBadge status="not_started" />
      );

      expect(container.firstChild).toBeNull();
    });

    it("renders not_started when showNotStarted is true", () => {
      renderWithTheme(
        <StatusBadge status="not_started" showNotStarted />
      );

      expect(screen.getByText("Not Started")).toBeInTheDocument();
    });
  });

  describe("Compact Mode", () => {
    it("shows short labels in compact mode", () => {
      renderWithTheme(<StatusBadge status="completed" compact />);

      expect(screen.getByText("Done")).toBeInTheDocument();
    });

    it("shows WIP for in_progress in compact mode", () => {
      renderWithTheme(<StatusBadge status="in_progress" compact />);

      expect(screen.getByText("WIP")).toBeInTheDocument();
    });
  });

  describe("Tooltips", () => {
    it("has tooltip with description", async () => {
      renderWithTheme(<StatusBadge status="completed" />);

      // Hover over badge
      fireEvent.mouseOver(screen.getByText("Completed"));

      await waitFor(() => {
        expect(screen.getByRole("tooltip")).toBeInTheDocument();
      });
    });
  });
});

