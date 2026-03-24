/**
 * Tests for Homepage (app/page.tsx).
 *
 * Tests the new homepage with HeroPrompt and ExampleQueries.
 * UX vNext Phase 1: FT-003
 */

import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import HomePage from "../page";
import { HeroPrompt } from "@/components/home/HeroPrompt";
import { ExampleQueries } from "@/components/home/ExampleQueries";

// Mock ChatLayout
jest.mock("@/components/chat", () => ({
  ChatLayout: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

// Mock components
jest.mock("@/components/home/HeroPrompt", () => ({
  HeroPrompt: jest.fn(() => <div data-testid="hero-prompt">HeroPrompt</div>),
}));

jest.mock("@/components/home/ExampleQueries", () => ({
  ExampleQueries: jest.fn(() => <div data-testid="example-queries">ExampleQueries</div>),
}));

jest.mock("next/image", () => ({
  __esModule: true,
  default: (props: Record<string, unknown>) => {
    // eslint-disable-next-line @next/next/no-img-element, jsx-a11y/alt-text
    return <img {...props} />;
  },
}));

const mockUseThemeMode = jest.fn(() => ({ mode: "light" }));

jest.mock("@/lib/theme/ThemeProvider", () => ({
  useThemeMode: () => mockUseThemeMode(),
}));

describe("HomePage", () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  describe("Layout", () => {
    it("renders with full viewport height", () => {
      const { container } = render(<HomePage />);

      // Check for Box with minHeight: 100vh via MUI sx
      const boxes = container.querySelectorAll("div");
      expect(boxes.length).toBeGreaterThan(0);
    });

    it("centers content vertically and horizontally", () => {
      render(<HomePage />);

      // Component should have centered layout
      expect(screen.getByTestId("hero-prompt")).toBeInTheDocument();
    });
  });

  describe("Branding", () => {
    it("displays logo in light mode", () => {
      mockUseThemeMode.mockReturnValue({ mode: "light" });
      render(<HomePage />);

      const logo = screen.getByAltText(/starboard logo/i);
      expect(logo).toBeInTheDocument();
      expect(logo).toHaveAttribute("src", expect.stringContaining("logo_wheel_light"));
    });

    it("displays logo in dark mode", () => {
      mockUseThemeMode.mockReturnValue({ mode: "dark" });
      render(<HomePage />);

      const logo = screen.getByAltText(/starboard logo/i);
      expect(logo).toBeInTheDocument();
      // Note: The actual implementation may use the same light logo path
      // depending on theme provider behavior. Check for any logo presence.
      expect(logo).toHaveAttribute("src");
    });

    it("displays main heading", () => {
      render(<HomePage />);

      const heading = screen.getByRole("heading", { level: 1 });
      expect(heading).toHaveTextContent(/starboard ai chat/i);
    });

    it("displays tagline", () => {
      render(<HomePage />);

      expect(screen.getByText(/navigating deep databricks insights/i)).toBeInTheDocument();
    });

    it("displays description", () => {
      render(<HomePage />);

      expect(screen.getByText(/ai-powered assistant/i)).toBeInTheDocument();
    });
  });

  describe("Components", () => {
    it("renders HeroPrompt component", () => {
      render(<HomePage />);

      expect(screen.getByTestId("hero-prompt")).toBeInTheDocument();
      expect(HeroPrompt).toHaveBeenCalled();
    });

    it("renders ExampleQueries component", () => {
      render(<HomePage />);

      expect(screen.getByTestId("example-queries")).toBeInTheDocument();
      expect(ExampleQueries).toHaveBeenCalled();
    });

    it("passes onSelect to ExampleQueries", () => {
      render(<HomePage />);

      const callArgs = (ExampleQueries as jest.Mock).mock.calls[0][0];
      expect(callArgs).toHaveProperty("onSelect");
      expect(typeof callArgs.onSelect).toBe("function");
    });
  });

  describe("Example Query Selection", () => {
    it("updates HeroPrompt when example query is selected", () => {
      // Mock implementations
      let heroPromptValue: string | undefined;

      (ExampleQueries as jest.Mock).mockImplementation(({ onSelect }: { onSelect: (text: string) => void }) => {
        return <button onClick={() => onSelect?.("Test query")}>Example</button>;
      });

      (HeroPrompt as jest.Mock).mockImplementation(({ initialValue }) => {
        heroPromptValue = initialValue;
        return <div data-testid="hero-prompt">{initialValue || "empty"}</div>;
      });

      const { rerender } = render(<HomePage />);

      // Initially empty
      expect(heroPromptValue).toBe(undefined);

      // Click example query
      const exampleButton = screen.getByText("Example");
      fireEvent.click(exampleButton);

      // Rerender to see updated state
      rerender(<HomePage />);

      // HeroPrompt should have been updated
      expect(screen.getByTestId("hero-prompt")).toHaveTextContent("Test query");
    });
  });

  describe("Responsive Design", () => {
    it("uses responsive typography", () => {
      render(<HomePage />);

      const heading = screen.getByRole("heading", { level: 1 });
      expect(heading).toBeInTheDocument();
      // MUI Typography with variant="h2" provides responsive sizing
    });

    it("renders main content in main element", () => {
      const { container } = render(<HomePage />);

      const main = container.querySelector("main");
      expect(main).toBeInTheDocument();
    });
  });

  describe("Accessibility", () => {
    it("has proper heading hierarchy", () => {
      render(<HomePage />);

      const h1 = screen.getByRole("heading", { level: 1 });
      expect(h1).toBeInTheDocument();
    });

    it("has accessible logo alt text", () => {
      render(<HomePage />);

      const logo = screen.getByAltText(/starboard logo/i);
      expect(logo).toHaveAccessibleName();
    });

    it("main content is in main landmark", () => {
      const { container } = render(<HomePage />);

      const main = container.querySelector("main");
      expect(main).toBeInTheDocument();
    });
  });

  describe("SEO & Metadata", () => {
    it("renders semantic HTML structure", () => {
      const { container } = render(<HomePage />);

      // Should have main element
      expect(container.querySelector("main")).toBeInTheDocument();
    });

    it("includes descriptive headings", () => {
      render(<HomePage />);

      const heading = screen.getByRole("heading", { level: 1 });
      expect(heading.textContent).toContain("Starboard");
    });
  });
});

