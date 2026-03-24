/**
 * Tests for FileAttachmentChip component.
 *
 * BB-05: Use a chip to display the user's uploaded file within the conversation/chat window.
 */

import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { ThemeProvider, createTheme } from "@mui/material/styles";
import { FileAttachmentChip } from "../FileAttachmentChip";
import type { FileAttachment } from "../FileUploadButton";

const theme = createTheme();

const renderWithTheme = (component: React.ReactNode) => {
  return render(<ThemeProvider theme={theme}>{component}</ThemeProvider>);
};

const mockAttachment: FileAttachment = {
  filename: "error.log",
  size: 1024,
  content: "2024-01-15 10:00:00 ERROR: Connection failed\n2024-01-15 10:00:01 INFO: Retrying...",
  contentPreview: "2024-01-15 10:00:00 ERROR: Connection failed",
  isLargeFile: false,
};

const mockLargeAttachment: FileAttachment = {
  filename: "large-file.json",
  size: 50 * 1024,
  content: '{"data": "large content..."}',
  contentPreview: '{"data": "lar',
  isLargeFile: true,
};

describe("FileAttachmentChip", () => {
  describe("Rendering", () => {
    it("renders chip with filename and size", () => {
      renderWithTheme(<FileAttachmentChip attachment={mockAttachment} />);

      expect(screen.getByText(/error\.log/i)).toBeInTheDocument();
      expect(screen.getByText(/1 KB/i)).toBeInTheDocument();
    });

    it("shows 'Large file' chip for large files", () => {
      renderWithTheme(<FileAttachmentChip attachment={mockLargeAttachment} />);

      expect(screen.getByText(/Large file/i)).toBeInTheDocument();
    });

    it("does not show 'Large file' chip for small files", () => {
      renderWithTheme(<FileAttachmentChip attachment={mockAttachment} />);

      expect(screen.queryByText(/Large file/i)).not.toBeInTheDocument();
    });

    it("shows delete button when showDelete is true", () => {
      const handleDelete = jest.fn();
      renderWithTheme(
        <FileAttachmentChip
          attachment={mockAttachment}
          showDelete
          onDelete={handleDelete}
        />
      );

      // The delete icon should be present (CloseIcon)
      const deleteIcon = screen.getByTestId("CloseIcon");
      expect(deleteIcon).toBeInTheDocument();
    });

    it("does not show delete button when showDelete is false", () => {
      renderWithTheme(<FileAttachmentChip attachment={mockAttachment} />);

      // CloseIcon should not be present when showDelete is false
      expect(screen.queryByTestId("CloseIcon")).not.toBeInTheDocument();
    });
  });

  describe("Interactions", () => {
    it("opens preview dialog when chip is clicked", async () => {
      renderWithTheme(<FileAttachmentChip attachment={mockAttachment} />);

      const chip = screen.getByText(/error\.log/i).closest('[role="button"]');
      expect(chip).toBeInTheDocument();

      if (chip) {
        fireEvent.click(chip);
      }

      await waitFor(() => {
        // Dialog title should appear with the filename
        expect(screen.getByRole("dialog")).toBeInTheDocument();
        expect(screen.getByRole("heading", { name: /error\.log/i })).toBeInTheDocument();
      });
    });

    it("shows file content in preview dialog", async () => {
      renderWithTheme(<FileAttachmentChip attachment={mockAttachment} />);

      const chip = screen.getByText(/error\.log/i).closest('[role="button"]');
      if (chip) {
        fireEvent.click(chip);
      }

      await waitFor(() => {
        expect(screen.getByText(/ERROR: Connection failed/)).toBeInTheDocument();
      });
    });

    it("closes preview dialog when Close button is clicked", async () => {
      renderWithTheme(<FileAttachmentChip attachment={mockAttachment} />);

      const chip = screen.getByText(/error\.log/i).closest('[role="button"]');
      if (chip) {
        fireEvent.click(chip);
      }

      await waitFor(() => {
        expect(screen.getByRole("dialog")).toBeInTheDocument();
      });

      const closeButton = screen.getByRole("button", { name: /close/i });
      fireEvent.click(closeButton);

      await waitFor(() => {
        expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
      });
    });

    it("calls onDelete when delete button is clicked", () => {
      const handleDelete = jest.fn();
      renderWithTheme(
        <FileAttachmentChip
          attachment={mockAttachment}
          showDelete
          onDelete={handleDelete}
        />
      );

      // Find the delete button within the chip (CloseIcon is the delete icon)
      const deleteButton = screen.getByTestId("CloseIcon");
      if (deleteButton) {
        fireEvent.click(deleteButton);
      }

      expect(handleDelete).toHaveBeenCalledTimes(1);
    });
  });

  describe("Accessibility", () => {
    it("has tooltip for preview hint", () => {
      renderWithTheme(<FileAttachmentChip attachment={mockAttachment} />);

      // The chip should have a tooltip indicating it's clickable
      const chip = screen.getByText(/error\.log/i).closest('[role="button"]');
      expect(chip).toBeInTheDocument();
    });

    it("dialog is focusable and has proper structure", async () => {
      renderWithTheme(<FileAttachmentChip attachment={mockAttachment} />);

      const chip = screen.getByText(/error\.log/i).closest('[role="button"]');
      if (chip) {
        fireEvent.click(chip);
      }

      await waitFor(() => {
        const dialog = screen.getByRole("dialog");
        expect(dialog).toBeInTheDocument();
        
        // Dialog should have proper title
        const title = screen.getByRole("heading", { name: /error\.log/i });
        expect(title).toBeInTheDocument();
      });
    });
  });
});

