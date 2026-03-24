/**
 * TokenDisplay component tests.
 *
 * Tests for token/cost display chip with tooltip breakdown.
 * Written TDD-first before implementation.
 */

import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ThemeProvider, createTheme } from "@mui/material/styles";
import { TokenDisplay } from "../TokenDisplay";

const theme = createTheme();

const renderWithTheme = (component: React.ReactNode) => {
  return render(<ThemeProvider theme={theme}>{component}</ThemeProvider>);
};

describe("TokenDisplay", () => {
  describe("renders nothing when no data", () => {
    it("returns null when no props are provided", () => {
      const { container } = renderWithTheme(<TokenDisplay />);
      expect(container).toBeEmptyDOMElement();
    });

    it("returns null when all token counts are undefined", () => {
      const { container } = renderWithTheme(
        <TokenDisplay
          inputTokens={undefined}
          outputTokens={undefined}
          totalTokens={undefined}
          estimatedCostUsd={undefined}
        />
      );
      expect(container).toBeEmptyDOMElement();
    });

    it("returns null when tokens are zero and no cost", () => {
      const { container } = renderWithTheme(<TokenDisplay totalTokens={0} />);
      expect(container).toBeEmptyDOMElement();
    });
  });

  describe("renders chip with token count", () => {
    it("displays total tokens when provided", () => {
      renderWithTheme(<TokenDisplay totalTokens={1500} />);
      expect(screen.getByText(/1,500 tokens/)).toBeInTheDocument();
    });

    it("formats large token counts with locale separators", () => {
      renderWithTheme(<TokenDisplay totalTokens={125000} />);
      expect(screen.getByText(/125,000 tokens/)).toBeInTheDocument();
    });

    it("displays cost when provided alongside tokens", () => {
      renderWithTheme(
        <TokenDisplay totalTokens={5000} estimatedCostUsd={0.0125} />
      );
      expect(screen.getByText(/5,000 tokens/)).toBeInTheDocument();
      expect(screen.getByText(/\$0\.0125/)).toBeInTheDocument();
    });

    it("renders cost only (no tokens) when only cost is provided", () => {
      renderWithTheme(<TokenDisplay estimatedCostUsd={0.0050} />);
      expect(screen.getByText(/\$0\.0050/)).toBeInTheDocument();
    });

    it("formats cost to 4 decimal places", () => {
      renderWithTheme(
        <TokenDisplay totalTokens={1000} estimatedCostUsd={0.001} />
      );
      expect(screen.getByText(/\$0\.0010/)).toBeInTheDocument();
    });
  });

  describe("tooltip shows breakdown", () => {
    it("renders a chip element with accessible text", () => {
      renderWithTheme(<TokenDisplay totalTokens={1000} />);
      expect(screen.getByText(/1,000 tokens/)).toBeInTheDocument();
    });

    it("shows model name in tooltip when provided", async () => {
      const user = userEvent.setup();
      renderWithTheme(
        <TokenDisplay
          totalTokens={2000}
          estimatedCostUsd={0.002}
          model="claude-sonnet-4-5"
        />
      );
      const chipLabel = screen.getByText(/2,000 tokens/);
      await user.hover(chipLabel);
      await waitFor(() => {
        expect(screen.getByText(/claude-sonnet-4-5/)).toBeInTheDocument();
      });
    });

    it("shows input/output token breakdown in tooltip", async () => {
      const user = userEvent.setup();
      renderWithTheme(
        <TokenDisplay
          inputTokens={800}
          outputTokens={200}
          totalTokens={1000}
        />
      );
      const chipLabel = screen.getByText(/1,000 tokens/);
      await user.hover(chipLabel);
      await waitFor(() => {
        expect(screen.getByText(/800/)).toBeInTheDocument();
        expect(screen.getByText(/200/)).toBeInTheDocument();
      });
    });
  });

  describe("handles partial data gracefully", () => {
    it("renders when only inputTokens is provided", () => {
      renderWithTheme(<TokenDisplay inputTokens={500} />);
      expect(screen.getByText(/500/)).toBeInTheDocument();
    });

    it("renders when only outputTokens is provided", () => {
      renderWithTheme(<TokenDisplay outputTokens={300} />);
      expect(screen.getByText(/300/)).toBeInTheDocument();
    });

    it("uses sum of input+output as total when totalTokens is absent", () => {
      renderWithTheme(
        <TokenDisplay inputTokens={700} outputTokens={300} />
      );
      expect(screen.getByText(/1,000 tokens/)).toBeInTheDocument();
    });

    it("prefers explicit totalTokens over computed sum", () => {
      renderWithTheme(
        <TokenDisplay inputTokens={700} outputTokens={300} totalTokens={1200} />
      );
      expect(screen.getByText(/1,200 tokens/)).toBeInTheDocument();
    });
  });
});
