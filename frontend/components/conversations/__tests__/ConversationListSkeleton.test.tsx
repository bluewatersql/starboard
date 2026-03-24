/**
 * Tests for ConversationListSkeleton component.
 */

import React from "react";
import { render } from "@testing-library/react";
import "@testing-library/jest-dom";
import { ConversationListSkeleton } from "../ConversationListSkeleton";

describe("ConversationListSkeleton", () => {
  it("renders without crashing", () => {
    const { container } = render(<ConversationListSkeleton />);
    expect(container).toBeInTheDocument();
  });

  it("renders 5 skeleton items", () => {
    const { container } = render(<ConversationListSkeleton />);
    // Each skeleton has 2 Skeleton components (title + timestamp)
    const skeletons = container.querySelectorAll(".MuiSkeleton-root");
    expect(skeletons.length).toBe(10); // 5 items × 2 skeletons each
  });

  it("renders skeleton items in a container", () => {
    const { container } = render(<ConversationListSkeleton />);
    const wrapper = container.firstChild;
    expect(wrapper).toBeInTheDocument();
  });

  it("uses MUI Skeleton component", () => {
    const { container } = render(<ConversationListSkeleton />);
    const skeletons = container.querySelectorAll(".MuiSkeleton-root");
    expect(skeletons.length).toBeGreaterThan(0);
  });

  it("has proper spacing between items", () => {
    const { container } = render(<ConversationListSkeleton />);
    const items = container.querySelectorAll("div[class*='MuiBox-root']");
    // Should have multiple Box components for layout
    expect(items.length).toBeGreaterThan(1);
  });
});

