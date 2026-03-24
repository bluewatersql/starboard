/**
 * CodeBlockWithActions component tests.
 *
 * Tests for syntax-highlighted code blocks with copy functionality.
 */

import React from "react";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import { ThemeProvider, createTheme } from "@mui/material/styles";
import { CodeBlockWithActions } from "../CodeBlockWithActions";

// Mock Shiki to avoid async loading issues in tests
jest.mock("shiki", () => ({
  createHighlighter: jest.fn().mockResolvedValue({
    codeToHtml: jest.fn((code: string) => {
      return `<pre class="shiki"><code>${code}</code></pre>`;
    }),
  }),
}));

// Mock clipboard API
const mockWriteText = jest.fn().mockResolvedValue(undefined);
Object.assign(navigator, {
  clipboard: {
    writeText: mockWriteText,
  },
});

const theme = createTheme();

const renderWithTheme = (component: React.ReactNode) => {
  return render(<ThemeProvider theme={theme}>{component}</ThemeProvider>);
};

// Sample code snippets for testing
const shortSQL = "SELECT * FROM users WHERE id = 1;";

const longSQL = `SELECT 
  u.user_id,
  u.username,
  u.email,
  p.profile_name,
  p.created_at,
  COUNT(o.order_id) as total_orders,
  SUM(o.amount) as total_spent,
  AVG(o.amount) as avg_order_value,
  MAX(o.created_at) as last_order_date,
  MIN(o.created_at) as first_order_date
FROM users u
LEFT JOIN profiles p ON u.user_id = p.user_id
LEFT JOIN orders o ON u.user_id = o.user_id
WHERE u.status = 'active'
  AND u.created_at >= '2024-01-01'
GROUP BY u.user_id, u.username, u.email, p.profile_name, p.created_at
HAVING COUNT(o.order_id) > 5
ORDER BY total_spent DESC
LIMIT 100;`;

const pythonCode = `def calculate_total(items: list[dict]) -> float:
    """Calculate total price of items."""
    return sum(item['price'] * item['quantity'] for item in items)`;

const jsonCode = `{
  "name": "starboard",
  "version": "1.0.0",
  "dependencies": {
    "react": "^18.0.0"
  }
}`;

describe("CodeBlockWithActions", () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  describe("Basic Rendering", () => {
    it("renders with SQL language badge by default", async () => {
      renderWithTheme(<CodeBlockWithActions code={shortSQL} />);
      
      await waitFor(() => {
        expect(screen.getByText("sql")).toBeInTheDocument();
      });
    });

    it("renders with specified language badge", async () => {
      renderWithTheme(<CodeBlockWithActions code={pythonCode} language="python" />);
      
      await waitFor(() => {
        expect(screen.getByText("python")).toBeInTheDocument();
      });
    });

    it("renders filename when provided", async () => {
      renderWithTheme(
        <CodeBlockWithActions 
          code={shortSQL} 
          filename="query.sql" 
        />
      );
      
      await waitFor(() => {
        expect(screen.getByText("query.sql")).toBeInTheDocument();
      });
    });

    it("renders Copy button", async () => {
      renderWithTheme(<CodeBlockWithActions code={shortSQL} />);
      
      await waitFor(() => {
        expect(screen.getByRole("button", { name: /copy/i })).toBeInTheDocument();
      });
    });

    it("renders the code block container", async () => {
      renderWithTheme(<CodeBlockWithActions code={shortSQL} />);
      
      await waitFor(() => {
        const container = document.querySelector('[class*="MuiPaper"]');
        expect(container).toBeInTheDocument();
      });
    });
  });

  describe("Copy Functionality", () => {
    it("copies code to clipboard when Copy button clicked", async () => {
      renderWithTheme(<CodeBlockWithActions code={shortSQL} />);
      
      await waitFor(() => {
        expect(screen.getByRole("button", { name: /copy/i })).toBeInTheDocument();
      });
      
      const copyButton = screen.getByRole("button", { name: /copy/i });
      fireEvent.click(copyButton);
      
      await waitFor(() => {
        expect(mockWriteText).toHaveBeenCalledWith(shortSQL);
      });
    });

    it("shows 'Copied!' feedback after successful copy", async () => {
      renderWithTheme(<CodeBlockWithActions code={shortSQL} />);
      
      await waitFor(() => {
        expect(screen.getByRole("button", { name: /copy/i })).toBeInTheDocument();
      });
      
      const copyButton = screen.getByRole("button", { name: /copy/i });
      fireEvent.click(copyButton);
      
      await waitFor(() => {
        expect(screen.getByLabelText(/copied/i)).toBeInTheDocument();
      });
    });

    it("reverts to 'Copy' after timeout", async () => {
      jest.useFakeTimers();
      
      renderWithTheme(<CodeBlockWithActions code={shortSQL} />);
      
      await waitFor(() => {
        expect(screen.getByRole("button", { name: /copy/i })).toBeInTheDocument();
      });
      
      const copyButton = screen.getByRole("button", { name: /copy/i });
      fireEvent.click(copyButton);
      
      await waitFor(() => {
        expect(screen.getByLabelText(/copied/i)).toBeInTheDocument();
      });
      
      // Advance timers by 2.5 seconds
      act(() => {
        jest.advanceTimersByTime(2500);
      });
      
      await waitFor(() => {
        expect(screen.getByRole("button", { name: /copy/i })).toBeInTheDocument();
      });
      
      jest.useRealTimers();
    });

    it("handles clipboard API failure gracefully", async () => {
      const consoleSpy = jest.spyOn(console, "error").mockImplementation(() => {});
      mockWriteText.mockRejectedValueOnce(new Error("Clipboard access denied"));
      
      renderWithTheme(<CodeBlockWithActions code={shortSQL} />);
      
      await waitFor(() => {
        expect(screen.getByRole("button", { name: /copy/i })).toBeInTheDocument();
      });
      
      const copyButton = screen.getByRole("button", { name: /copy/i });
      fireEvent.click(copyButton);
      
      await waitFor(() => {
        expect(consoleSpy).toHaveBeenCalled();
      });
      
      consoleSpy.mockRestore();
    });
  });

  describe("Wrap Toggle", () => {
    it("renders wrap toggle button by default", async () => {
      renderWithTheme(<CodeBlockWithActions code={shortSQL} />);
      
      await waitFor(() => {
        expect(screen.getByLabelText(/wrap/i)).toBeInTheDocument();
      });
    });

    it("toggles wrap state when clicked", async () => {
      renderWithTheme(<CodeBlockWithActions code={shortSQL} />);
      
      await waitFor(() => {
        expect(screen.getByLabelText(/disable wrap/i)).toBeInTheDocument();
      });
      
      const wrapToggle = screen.getByLabelText(/disable wrap/i);
      fireEvent.click(wrapToggle);
      
      await waitFor(() => {
        expect(screen.getByLabelText(/enable wrap/i)).toBeInTheDocument();
      });
    });

    it("hides wrap toggle when enableWrapToggle is false", async () => {
      renderWithTheme(
        <CodeBlockWithActions 
          code={shortSQL} 
          enableWrapToggle={false} 
        />
      );
      
      await waitFor(() => {
        expect(screen.queryByText("sql")).toBeInTheDocument();
      });
      
      expect(screen.queryByLabelText(/wrap/i)).not.toBeInTheDocument();
    });
  });

  describe("Language Support", () => {
    it("renders SQL code with language badge", async () => {
      renderWithTheme(<CodeBlockWithActions code={shortSQL} language="sql" />);
      
      await waitFor(() => {
        expect(screen.getByText("sql")).toBeInTheDocument();
      });
    });

    it("renders Python code with language badge", async () => {
      renderWithTheme(<CodeBlockWithActions code={pythonCode} language="python" />);
      
      await waitFor(() => {
        expect(screen.getByText("python")).toBeInTheDocument();
      });
    });

    it("renders JSON code with language badge", async () => {
      renderWithTheme(<CodeBlockWithActions code={jsonCode} language="json" />);
      
      await waitFor(() => {
        expect(screen.getByText("json")).toBeInTheDocument();
      });
    });

    it("handles unknown language gracefully", async () => {
      const customCode = "some custom code here";
      renderWithTheme(
        <CodeBlockWithActions 
          code={customCode} 
          language="unknown-lang" 
        />
      );
      
      // Unknown languages fallback to plaintext for highlighting
      await waitFor(() => {
        expect(screen.getByText("plaintext")).toBeInTheDocument();
      });
    });
  });

  describe("Apply Button", () => {
    it("does not render Apply button by default", async () => {
      renderWithTheme(<CodeBlockWithActions code={shortSQL} />);
      
      await waitFor(() => {
        expect(screen.getByText("sql")).toBeInTheDocument();
      });
      
      expect(screen.queryByRole("button", { name: /apply/i })).not.toBeInTheDocument();
    });

    it("renders Apply button when onApply is provided", async () => {
      const handleApply = jest.fn();
      renderWithTheme(
        <CodeBlockWithActions 
          code={shortSQL} 
          onApply={handleApply} 
        />
      );
      
      await waitFor(() => {
        expect(screen.getByRole("button", { name: /apply/i })).toBeInTheDocument();
      });
    });

    it("calls onApply with code when Apply clicked", async () => {
      const handleApply = jest.fn();
      renderWithTheme(
        <CodeBlockWithActions 
          code={shortSQL} 
          onApply={handleApply} 
        />
      );
      
      await waitFor(() => {
        expect(screen.getByRole("button", { name: /apply/i })).toBeInTheDocument();
      });
      
      const applyButton = screen.getByRole("button", { name: /apply/i });
      fireEvent.click(applyButton);
      
      expect(handleApply).toHaveBeenCalledWith(shortSQL);
    });
  });

  describe("Accessibility", () => {
    it("has accessible copy button", async () => {
      renderWithTheme(<CodeBlockWithActions code={shortSQL} />);
      
      await waitFor(() => {
        const copyButton = screen.getByRole("button", { name: /copy/i });
        expect(copyButton).toHaveAttribute("aria-label");
      });
    });

    it("wrap toggle has accessible label", async () => {
      renderWithTheme(<CodeBlockWithActions code={shortSQL} />);
      
      await waitFor(() => {
        const wrapToggle = screen.getByLabelText(/wrap/i);
        expect(wrapToggle).toBeInTheDocument();
      });
    });
  });

  describe("Max Height", () => {
    it("renders component with default max height setting", async () => {
      renderWithTheme(<CodeBlockWithActions code={longSQL} />);
      
      await waitFor(() => {
        expect(screen.getByText("sql")).toBeInTheDocument();
      });
      
      const container = document.querySelector('[class*="MuiPaper"]');
      expect(container).toBeInTheDocument();
    });

    it("renders component with custom max height setting", async () => {
      renderWithTheme(
        <CodeBlockWithActions 
          code={longSQL} 
          maxHeight="300px" 
        />
      );
      
      await waitFor(() => {
        expect(screen.getByText("sql")).toBeInTheDocument();
      });
      
      const container = document.querySelector('[class*="MuiPaper"]');
      expect(container).toBeInTheDocument();
    });
  });

  describe("Line Numbers", () => {
    it("renders component for short code", async () => {
      renderWithTheme(<CodeBlockWithActions code={shortSQL} />);
      
      await waitFor(() => {
        expect(screen.getByText("sql")).toBeInTheDocument();
      });
      
      const container = document.querySelector('[class*="MuiPaper"]');
      expect(container).toBeInTheDocument();
    });

    it("renders component with showLineNumbers prop", async () => {
      renderWithTheme(
        <CodeBlockWithActions 
          code={shortSQL} 
          showLineNumbers={true} 
        />
      );
      
      await waitFor(() => {
        expect(screen.getByText("sql")).toBeInTheDocument();
      });
      
      const container = document.querySelector('[class*="MuiPaper"]');
      expect(container).toBeInTheDocument();
    });

    it("renders component for long code (auto line numbers)", async () => {
      renderWithTheme(<CodeBlockWithActions code={longSQL} />);
      
      await waitFor(() => {
        expect(screen.getByText("sql")).toBeInTheDocument();
      });
      
      const container = document.querySelector('[class*="MuiPaper"]');
      expect(container).toBeInTheDocument();
    });
  });

  describe("Highlighted Lines", () => {
    it("renders component with highlighted lines prop", async () => {
      renderWithTheme(
        <CodeBlockWithActions 
          code={longSQL} 
          highlightLines={[1, 2, 3]} 
          showLineNumbers={true}
        />
      );
      
      await waitFor(() => {
        expect(screen.getByText("sql")).toBeInTheDocument();
      });
      
      const container = document.querySelector('[class*="MuiPaper"]');
      expect(container).toBeInTheDocument();
    });
  });
});
