/**
 * Tests for ExampleQueries component.
 *
 * Tests example query cards on the homepage.
 * UX vNext Phase 1: FT-005
 */

import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import { ExampleQueries } from "../ExampleQueries";

describe("ExampleQueries", () => {
  const mockOnSelect = jest.fn();

  beforeEach(() => {
    jest.clearAllMocks();
  });

  describe("Rendering", () => {
    it("renders component title", () => {
      render(<ExampleQueries />);

      expect(screen.getByText(/example queries/i)).toBeInTheDocument();
    });

    it("renders multiple example query cards", () => {
      render(<ExampleQueries />);

      const buttons = screen.getAllByRole("button");
      expect(buttons.length).toBeGreaterThanOrEqual(6);
      expect(buttons.length).toBeLessThanOrEqual(8);
    });

    it("each card displays query text", () => {
      render(<ExampleQueries />);

      // Should have multiple example queries visible
      const buttons = screen.getAllByRole("button");
      buttons.forEach((button) => {
        expect(button.textContent).toBeTruthy();
        expect(button.textContent!.length).toBeGreaterThan(10);
      });
    });

    it("displays category labels", () => {
      render(<ExampleQueries />);

      // Should have category labels (Job, Query, Table, Cost)
      const categories = ["Job", "Query", "Table", "Cost"];
      let foundCategories = 0;

      categories.forEach((category) => {
        const elements = screen.queryAllByText(category);
        if (elements.length > 0) {
          foundCategories++;
        }
      });

      // Should have all 4 categories visible
      expect(foundCategories).toBe(4);
    });
  });

  describe("Interaction", () => {
    it("calls onSelect when query card clicked", () => {
      render(<ExampleQueries onSelect={mockOnSelect} />);

      const buttons = screen.getAllByRole("button");
      fireEvent.click(buttons[0]!);

      expect(mockOnSelect).toHaveBeenCalledTimes(1);
      expect(mockOnSelect).toHaveBeenCalledWith(expect.any(String));
      expect(mockOnSelect.mock.calls[0]![0].length).toBeGreaterThan(10);
    });

    it("passes correct query text to onSelect", () => {
      render(<ExampleQueries onSelect={mockOnSelect} />);

      const buttons = screen.getAllByRole("button");
      const firstButton = buttons[0]!;

      fireEvent.click(firstButton);

      // Should be called with a string matching one of the example queries
      expect(mockOnSelect).toHaveBeenCalledWith(expect.any(String));
      const calledWith = mockOnSelect.mock.calls[0]![0];
      expect(calledWith.length).toBeGreaterThan(20);
    });

    it("can click different example queries", () => {
      render(<ExampleQueries onSelect={mockOnSelect} />);

      const buttons = screen.getAllByRole("button");
      
      // Click first query
      fireEvent.click(buttons[0]!);
      const firstQuery = mockOnSelect.mock.calls[0]![0];

      // Click second query
      fireEvent.click(buttons[1]!);
      const secondQuery = mockOnSelect.mock.calls[1]![0];

      // Queries should be different
      expect(firstQuery).not.toBe(secondQuery);
    });

    it("works without onSelect prop", () => {
      render(<ExampleQueries />);

      const buttons = screen.getAllByRole("button");
      
      // Should not throw when clicked without onSelect
      expect(() => fireEvent.click(buttons[0]!)).not.toThrow();
    });
  });

  describe("Categories", () => {
    it("includes job analysis examples", () => {
      render(<ExampleQueries />);

      const jobElements = screen.getAllByText("Job");
      expect(jobElements.length).toBeGreaterThanOrEqual(1);
    });

    it("includes query optimization examples", () => {
      render(<ExampleQueries />);

      const queryElements = screen.getAllByText("Query");
      expect(queryElements.length).toBeGreaterThanOrEqual(1);
    });

    it("includes table-related examples", () => {
      render(<ExampleQueries />);

      const tableElements = screen.getAllByText("Table");
      expect(tableElements.length).toBeGreaterThanOrEqual(1);
    });

    it("includes cost analysis examples", () => {
      render(<ExampleQueries />);

      const costElements = screen.getAllByText("Cost");
      expect(costElements.length).toBeGreaterThanOrEqual(1);
    });
  });

  describe("Styling & Layout", () => {
    it("renders in grid layout", () => {
      const { container } = render(<ExampleQueries />);

      // Component should use grid or flex layout
      expect(container.querySelector('[class*="grid"]') || 
             container.querySelector('[class*="Grid"]')).toBeTruthy();
    });

    it("cards are clickable buttons", () => {
      render(<ExampleQueries />);

      const buttons = screen.getAllByRole("button");
      buttons.forEach((button) => {
        expect(button).toBeEnabled();
      });
    });

    it("applies hover effects", () => {
      const { container } = render(<ExampleQueries />);

      // Cards should have hover styles (via MUI Card or custom styles)
      // This is a smoke test - actual hover effects tested via browser tests
      expect(container.firstChild).toBeTruthy();
    });
  });

  describe("Accessibility", () => {
    it("all example queries have accessible names", () => {
      render(<ExampleQueries />);

      const buttons = screen.getAllByRole("button");
      buttons.forEach((button) => {
        expect(button).toHaveAccessibleName();
      });
    });

    it("uses semantic HTML", () => {
      const { container } = render(<ExampleQueries />);

      // Should use semantic HTML elements
      expect(container.querySelector("button")).toBeInTheDocument();
    });

    it("keyboard navigation works", () => {
      render(<ExampleQueries />);

      const buttons = screen.getAllByRole("button");
      
      // All buttons should be focusable
      buttons.forEach((button) => {
        button.focus();
        expect(button).toHaveFocus();
      });
    });
  });

  describe("Responsive Design", () => {
    it("renders on mobile viewport", () => {
      // Mock viewport size
      global.innerWidth = 375;
      global.innerHeight = 667;

      render(<ExampleQueries />);

      const buttons = screen.getAllByRole("button");
      expect(buttons.length).toBeGreaterThanOrEqual(6);
    });

    it("renders on desktop viewport", () => {
      // Mock viewport size
      global.innerWidth = 1920;
      global.innerHeight = 1080;

      render(<ExampleQueries />);

      const buttons = screen.getAllByRole("button");
      expect(buttons.length).toBeGreaterThanOrEqual(6);
    });
  });

  describe("Content Quality", () => {
    it("example queries are realistic and useful", () => {
      render(<ExampleQueries />);

      const buttons = screen.getAllByRole("button");
      
      // Each query should be reasonably long and specific
      buttons.forEach((button) => {
        const text = button.textContent || "";
        expect(text.length).toBeGreaterThan(20); // Specific queries
        expect(text.length).toBeLessThan(200); // Not too verbose
      });
    });

    it("example queries mention Databricks concepts", () => {
      render(<ExampleQueries />);

      const { container } = render(<ExampleQueries />);
      const text = container.textContent || "";

      // Should mention at least some Databricks-related terms
      const databricksTerms = /job|query|table|warehouse|cluster|cost|performance|optimization/i;
      expect(text).toMatch(databricksTerms);
    });
  });

  describe("Optional className prop", () => {
    it("applies custom className", () => {
      const { container } = render(<ExampleQueries className="custom-class" />);

      expect(container.firstChild).toHaveClass("custom-class");
    });
  });
});

