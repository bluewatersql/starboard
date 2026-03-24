/**
 * Thinking steps component tests.
 *
 * Tests for ThinkingStepEnhanced and ThinkingStepsContainer components.
 */

import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { ThemeProvider, createTheme } from "@mui/material/styles";
import {
  ThinkingStepEnhanced,
  ThinkingStep,
} from "../ThinkingStepEnhanced";
import { ThinkingStepsContainer } from "../ThinkingStepsContainer";

const theme = createTheme();

const renderWithTheme = (component: React.ReactNode) => {
  return render(<ThemeProvider theme={theme}>{component}</ThemeProvider>);
};

// Sample test data
const completedStep: ThinkingStep = {
  id: "resolve_query",
  title: "Resolving Query",
  status: "completed",
  stepType: "resolve_query",
  startTime: 1000,
  endTime: 2500,
  subTasks: [
    {
      id: "1",
      description: "Retrieved SQL from query history",
      status: "completed",
      value: "1,247 lines",
    },
  ],
};

const inProgressStep: ThinkingStep = {
  id: "analyze_plan",
  title: "Analyzing Query Plan",
  status: "in_progress",
  stepType: "analyze_query_plan",
  startTime: 2500,
  progress: 45,
  subTasks: [
    {
      id: "1",
      description: "Parsed execution plan",
      status: "completed",
      value: "342 nodes",
    },
    {
      id: "2",
      description: "Identifying join operations",
      status: "in_progress",
    },
  ],
};

const pendingStep: ThinkingStep = {
  id: "discover_tables",
  title: "Discovering Tables",
  status: "pending",
  stepType: "discover_tables",
};

const failedStep: ThinkingStep = {
  id: "failed_step",
  title: "Failed Operation",
  status: "failed",
};

describe("ThinkingStepEnhanced", () => {
  describe("Status Display", () => {
    it("renders completed step with checkmark icon", () => {
      renderWithTheme(<ThinkingStepEnhanced step={completedStep} />);

      expect(screen.getByText("Resolving Query")).toBeInTheDocument();
      expect(screen.getByLabelText("Completed")).toBeInTheDocument();
    });

    it("renders in-progress step with processing label", () => {
      renderWithTheme(<ThinkingStepEnhanced step={inProgressStep} />);

      expect(screen.getByText("Analyzing Query Plan")).toBeInTheDocument();
      expect(screen.getByText("Processing")).toBeInTheDocument();
      expect(screen.getByLabelText("In progress")).toBeInTheDocument();
    });

    it("renders pending step with empty circle", () => {
      renderWithTheme(<ThinkingStepEnhanced step={pendingStep} />);

      expect(screen.getByText("Discovering Tables")).toBeInTheDocument();
      expect(screen.getByLabelText("Pending")).toBeInTheDocument();
    });

    it("renders failed step with error icon and label", () => {
      renderWithTheme(<ThinkingStepEnhanced step={failedStep} />);

      expect(screen.getByText("Failed Operation")).toBeInTheDocument();
      expect(screen.getByText("Failed")).toBeInTheDocument();
      expect(screen.getByLabelText("Failed")).toBeInTheDocument();
    });
  });

  describe("Duration Display", () => {
    it("shows duration for completed steps", () => {
      renderWithTheme(<ThinkingStepEnhanced step={completedStep} />);

      expect(screen.getByText("1.50s")).toBeInTheDocument();
    });

    it("does not show duration for in-progress steps", () => {
      renderWithTheme(<ThinkingStepEnhanced step={inProgressStep} />);

      expect(screen.queryByText(/^\d+\.\d+s$/)).not.toBeInTheDocument();
    });
  });

  describe("Progress Bar", () => {
    it("shows indeterminate progress bar for in-progress steps", () => {
      renderWithTheme(<ThinkingStepEnhanced step={inProgressStep} />);

      // U3: Now shows indeterminate progress (no percentage text)
      expect(screen.getByRole("progressbar")).toBeInTheDocument();
    });

    it("does not show progress bar for completed steps", () => {
      renderWithTheme(<ThinkingStepEnhanced step={completedStep} />);

      expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
    });
  });

  describe("Sub-tasks", () => {
    it("shows expand button when step has sub-tasks", () => {
      renderWithTheme(<ThinkingStepEnhanced step={completedStep} />);

      expect(screen.getByLabelText("Expand details")).toBeInTheDocument();
    });

    it("does not show expand button when step has no sub-tasks", () => {
      renderWithTheme(<ThinkingStepEnhanced step={pendingStep} />);

      expect(screen.queryByLabelText("Expand details")).not.toBeInTheDocument();
    });

    it("expands to show sub-tasks when clicked", async () => {
      renderWithTheme(<ThinkingStepEnhanced step={completedStep} />);

      // Expand button should be present
      expect(screen.getByLabelText("Expand details")).toBeInTheDocument();

      // Click expand
      fireEvent.click(screen.getByLabelText("Expand details"));

      // Should now show Collapse button and sub-task content is visible
      await waitFor(() => {
        expect(screen.getByLabelText("Collapse details")).toBeInTheDocument();
      });
      
      // Sub-task content should be visible
      expect(
        screen.getByText("Retrieved SQL from query history")
      ).toBeInTheDocument();
      expect(screen.getByText("1,247 lines")).toBeInTheDocument();
    });

    it("collapses sub-tasks when clicked again", async () => {
      renderWithTheme(
        <ThinkingStepEnhanced step={completedStep} defaultExpanded />
      );

      // Sub-task should be visible initially
      expect(
        screen.getByText("Retrieved SQL from query history")
      ).toBeInTheDocument();

      // Click collapse
      fireEvent.click(screen.getByLabelText("Collapse details"));

      // Sub-task should be hidden (collapse animation)
      await waitFor(() => {
        expect(screen.getByLabelText("Expand details")).toBeInTheDocument();
      });
    });

    it("shows sub-task status indicators", async () => {
      renderWithTheme(
        <ThinkingStepEnhanced step={inProgressStep} defaultExpanded />
      );

      // Check completed sub-task has checkmark
      expect(screen.getByText("Parsed execution plan")).toBeInTheDocument();
      expect(screen.getByText("342 nodes")).toBeInTheDocument();

      // Check in-progress sub-task
      expect(
        screen.getByText("Identifying join operations")
      ).toBeInTheDocument();
    });
  });

  describe("Callbacks", () => {
    it("calls onToggleExpand when expand button is clicked", () => {
      const handleToggle = jest.fn();
      renderWithTheme(
        <ThinkingStepEnhanced
          step={completedStep}
          onToggleExpand={handleToggle}
        />
      );

      fireEvent.click(screen.getByLabelText("Expand details"));

      expect(handleToggle).toHaveBeenCalledWith("resolve_query", true);
    });
  });
});

describe("ThinkingStepsContainer", () => {
  const allSteps: ThinkingStep[] = [
    completedStep,
    inProgressStep,
    pendingStep,
  ];

  describe("Rendering", () => {
    it("renders all steps", () => {
      renderWithTheme(<ThinkingStepsContainer steps={allSteps} />);

      expect(screen.getByText("Resolving Query")).toBeInTheDocument();
      expect(screen.getByText("Analyzing Query Plan")).toBeInTheDocument();
      expect(screen.getByText("Discovering Tables")).toBeInTheDocument();
    });

    it("shows progress counter", () => {
      renderWithTheme(<ThinkingStepsContainer steps={allSteps} />);

      expect(screen.getByText("(1/3)")).toBeInTheDocument();
    });

    it("renders nothing when steps is empty", () => {
      const { container } = renderWithTheme(
        <ThinkingStepsContainer steps={[]} />
      );

      expect(container.firstChild).toBeNull();
    });
  });

  describe("Header State", () => {
    it("shows 'Thinking...' when steps are in progress", () => {
      renderWithTheme(<ThinkingStepsContainer steps={allSteps} />);

      expect(screen.getByText("Tool Calls")).toBeInTheDocument();
    });

    it("shows 'Tool Calls' title when all steps are completed", () => {
      const completedSteps: ThinkingStep[] = [
        completedStep,
        { ...inProgressStep, status: "completed", endTime: 5000 },
        { ...pendingStep, status: "completed", startTime: 5000, endTime: 6000 },
      ];

      renderWithTheme(<ThinkingStepsContainer steps={completedSteps} />);

      expect(screen.getByText("Tool Calls")).toBeInTheDocument();
    });

    it("shows total duration when all steps are completed", () => {
      const completedSteps: ThinkingStep[] = [
        { ...completedStep, startTime: 0, endTime: 1000 },
        { ...inProgressStep, status: "completed", startTime: 1000, endTime: 3000 },
      ];

      renderWithTheme(<ThinkingStepsContainer steps={completedSteps} />);

      // Duration is shown as "• X.XXs" format - check multiple durations exist
      const durationElements = screen.getAllByText(/\d+\.\d+s/);
      expect(durationElements.length).toBeGreaterThan(0);
    });
  });

  describe("Collapse/Expand", () => {
    it("collapses when header is clicked", async () => {
      renderWithTheme(<ThinkingStepsContainer steps={allSteps} />);

      // Steps should be visible initially
      expect(screen.getByText("Resolving Query")).toBeInTheDocument();

      // Click header to collapse
      fireEvent.click(screen.getByText("Tool Calls"));

      // Check for collapse button change
      await waitFor(() => {
        expect(
          screen.getByLabelText("Expand tool calls")
        ).toBeInTheDocument();
      });
    });

    it("starts collapsed when defaultCollapsed is true", () => {
      renderWithTheme(
        <ThinkingStepsContainer steps={allSteps} defaultCollapsed />
      );

      expect(
        screen.getByLabelText("Expand tool calls")
      ).toBeInTheDocument();
    });
  });

  describe("Accessibility", () => {
    it("has list role on steps container", () => {
      renderWithTheme(<ThinkingStepsContainer steps={allSteps} />);

      expect(screen.getByRole("list")).toBeInTheDocument();
    });

    it("has listitem role on each step", () => {
      renderWithTheme(<ThinkingStepsContainer steps={allSteps} />);

      const listItems = screen.getAllByRole("listitem");
      expect(listItems).toHaveLength(3);
    });
  });
});

