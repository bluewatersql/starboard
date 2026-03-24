/**
 * ConfirmationDialog component tests.
 */

import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import { ThemeProvider, createTheme } from "@mui/material/styles";
import { ConfirmationDialog } from "../ConfirmationDialog";

const theme = createTheme();

const renderWithTheme = (component: React.ReactNode) =>
  render(<ThemeProvider theme={theme}>{component}</ThemeProvider>);

const defaultProps = {
  open: true,
  title: "Delete item?",
  message: "This action cannot be undone.",
  onConfirm: jest.fn(),
  onCancel: jest.fn(),
};

describe("ConfirmationDialog", () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  describe("Rendering", () => {
    it("renders the title", () => {
      renderWithTheme(<ConfirmationDialog {...defaultProps} />);
      expect(screen.getByText("Delete item?")).toBeInTheDocument();
    });

    it("renders the message", () => {
      renderWithTheme(<ConfirmationDialog {...defaultProps} />);
      expect(screen.getByText("This action cannot be undone.")).toBeInTheDocument();
    });

    it("renders default button labels", () => {
      renderWithTheme(<ConfirmationDialog {...defaultProps} />);
      expect(screen.getByText("Confirm")).toBeInTheDocument();
      expect(screen.getByText("Cancel")).toBeInTheDocument();
    });

    it("renders custom button labels", () => {
      renderWithTheme(
        <ConfirmationDialog
          {...defaultProps}
          confirmLabel="Yes, delete"
          cancelLabel="No, keep it"
        />
      );
      expect(screen.getByText("Yes, delete")).toBeInTheDocument();
      expect(screen.getByText("No, keep it")).toBeInTheDocument();
    });

    it("does not render when closed", () => {
      renderWithTheme(
        <ConfirmationDialog {...defaultProps} open={false} />
      );
      expect(screen.queryByText("Delete item?")).not.toBeInTheDocument();
    });
  });

  describe("Confirm action", () => {
    it("calls onConfirm when confirm button is clicked", () => {
      const onConfirm = jest.fn();
      renderWithTheme(
        <ConfirmationDialog {...defaultProps} onConfirm={onConfirm} />
      );
      fireEvent.click(screen.getByText("Confirm"));
      expect(onConfirm).toHaveBeenCalledTimes(1);
    });

    it("does not call onCancel when confirm is clicked", () => {
      const onCancel = jest.fn();
      renderWithTheme(
        <ConfirmationDialog {...defaultProps} onCancel={onCancel} />
      );
      fireEvent.click(screen.getByText("Confirm"));
      expect(onCancel).not.toHaveBeenCalled();
    });
  });

  describe("Cancel action", () => {
    it("calls onCancel when cancel button is clicked", () => {
      const onCancel = jest.fn();
      renderWithTheme(
        <ConfirmationDialog {...defaultProps} onCancel={onCancel} />
      );
      fireEvent.click(screen.getByText("Cancel"));
      expect(onCancel).toHaveBeenCalledTimes(1);
    });

    it("does not call onConfirm when cancel is clicked", () => {
      const onConfirm = jest.fn();
      renderWithTheme(
        <ConfirmationDialog {...defaultProps} onConfirm={onConfirm} />
      );
      fireEvent.click(screen.getByText("Cancel"));
      expect(onConfirm).not.toHaveBeenCalled();
    });
  });
});
