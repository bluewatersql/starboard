/**
 * Tests for Footer component.
 */

import React from "react";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { Footer } from "../Footer";

// Mock useConfigStore
const mockConfigState = { model: "gpt-4", temperature: 0.7 };
jest.mock("@/lib/store/configStore", () => ({
  useConfigStore: jest.fn((selector) => selector(mockConfigState)),
}));

describe("Footer", () => {
  it("renders disclaimer", () => {
    render(<Footer />);
    expect(screen.getByText(/AI can make mistakes/i)).toBeInTheDocument();
  });

  it("displays model information", () => {
    render(<Footer />);
    expect(screen.getByText(/Model: gpt-4/i)).toBeInTheDocument();
    expect(screen.getByText(/temp: 0.7/i)).toBeInTheDocument();
  });

  it("displays copyright with current year", () => {
    render(<Footer />);
    const currentYear = new Date().getFullYear();
    expect(screen.getByText(new RegExp(currentYear.toString()))).toBeInTheDocument();
  });

  it("includes Starboard AI link", () => {
    render(<Footer />);
    const link = screen.getByRole("link", { name: /starboard ai/i });
    expect(link).toBeInTheDocument();
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
  });

  it("renders as footer element", () => {
    const { container } = render(<Footer />);
    expect(container.querySelector("footer")).toBeInTheDocument();
  });
});

