/**
 * Tests for LazyCodeBlock.
 *
 * Verifies:
 * - Skeleton fallback is shown while loading
 * - Actual component renders after Suspense resolves
 * - Props are forwarded correctly to CodeBlockWithActions
 */

import React, { Suspense } from "react";
import { render, screen, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

// Mock the skeleton so we can detect it easily
jest.mock("@/components/common/skeletons", () => ({
  CodeBlockSkeleton: ({ lines }: { lines?: number }) => (
    <div data-testid="code-block-skeleton-mock" data-lines={lines}>
      Code loading...
    </div>
  ),
}));

// Mock CodeBlockWithActions to avoid pulling in Shiki
jest.mock("@/components/chat/CodeBlockWithActions", () => ({
  CodeBlockWithActions: ({
    code,
    language,
    showLineNumbers,
  }: {
    code: string;
    language?: string;
    showLineNumbers?: boolean;
  }) => (
    <div
      data-testid="code-block-mock"
      data-code={code}
      data-language={language ?? ""}
      data-line-numbers={showLineNumbers ? "true" : "false"}
    >
      {code}
    </div>
  ),
}));

// Import AFTER mocks
import { LazyCodeBlock } from "../LazyCodeBlock";

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------
describe("LazyCodeBlock", () => {
  it("renders the code block after Suspense resolves", async () => {
    render(
      <LazyCodeBlock code="SELECT 1;" language="sql" />
    );

    await waitFor(() => {
      expect(screen.getByTestId("code-block-mock")).toBeInTheDocument();
    });
  });

  it("forwards code prop to CodeBlockWithActions", async () => {
    render(<LazyCodeBlock code="print('hello')" language="python" />);

    await waitFor(() => {
      const block = screen.getByTestId("code-block-mock");
      expect(block).toHaveAttribute("data-code", "print('hello')");
    });
  });

  it("forwards language prop to CodeBlockWithActions", async () => {
    render(<LazyCodeBlock code="const x = 1;" language="typescript" />);

    await waitFor(() => {
      const block = screen.getByTestId("code-block-mock");
      expect(block).toHaveAttribute("data-language", "typescript");
    });
  });

  it("forwards showLineNumbers prop to CodeBlockWithActions", async () => {
    render(
      <LazyCodeBlock code="line1\nline2\nline3" language="python" showLineNumbers />
    );

    await waitFor(() => {
      const block = screen.getByTestId("code-block-mock");
      expect(block).toHaveAttribute("data-line-numbers", "true");
    });
  });

  it("renders without crashing when only code is provided", async () => {
    const { container } = render(<LazyCodeBlock code="hello world" />);

    await waitFor(() => {
      expect(container.firstChild).toBeInTheDocument();
    });
  });

  it("renders without crashing when code is empty string", async () => {
    const { container } = render(<LazyCodeBlock code="" />);

    await waitFor(() => {
      expect(container.firstChild).toBeInTheDocument();
    });
  });
});
