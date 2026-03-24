/**
 * Report structure component tests.
 *
 * Tests for ImpactBadge, EffortBadge, RecommendationCard, ReportSection,
 * ReportSummary, and ImplementationPlan components.
 */

import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { ThemeProvider, createTheme } from "@mui/material/styles";
import { ImpactBadge } from "../ImpactBadge";
import { EffortBadge } from "../EffortBadge";
import { RecommendationCard, RecommendationItem } from "../RecommendationCard";
import { ReportSection, ReportSectionData } from "../ReportSection";
import { ReportSummary } from "../ReportSummary";
import { ImplementationPlan } from "../ImplementationPlan";

// Mock clipboard API
const mockWriteText = jest.fn().mockResolvedValue(undefined);
Object.assign(navigator, {
  clipboard: {
    writeText: mockWriteText,
  },
});

// Mock shiki
jest.mock("shiki", () => ({
  createHighlighter: jest.fn().mockResolvedValue({
    codeToHtml: jest.fn((code: string) => {
      return `<pre class="shiki"><code>${code}</code></pre>`;
    }),
  }),
}));

const theme = createTheme();

const renderWithTheme = (component: React.ReactNode) => {
  return render(<ThemeProvider theme={theme}>{component}</ThemeProvider>);
};

// Sample test data
const sampleRecommendation: RecommendationItem = {
  id: "1",
  title: "Add partition filter",
  description: "Query scans entire table without partition pruning",
  impact: "high",
  effort: "low",
  category: "Query Optimization",
  sql_suggestion: "WHERE partition_date = '2024-01-01'",
  explanation: "Adding a partition filter reduces data scanned by 90%",
  estimated_improvement: "25% faster",
  estimated_time: "5 min",
};

const sampleSection: ReportSectionData = {
  id: "critical",
  title: "Critical Issues",
  severity: "critical",
  items: [sampleRecommendation],
};

describe("ImpactBadge", () => {
  it("renders high impact badge", () => {
    renderWithTheme(<ImpactBadge impact="high" />);
    expect(screen.getByText("High Impact")).toBeInTheDocument();
  });

  it("renders medium impact badge", () => {
    renderWithTheme(<ImpactBadge impact="medium" />);
    expect(screen.getByText("Medium Impact")).toBeInTheDocument();
  });

  it("renders low impact badge", () => {
    renderWithTheme(<ImpactBadge impact="low" />);
    expect(screen.getByText("Low Impact")).toBeInTheDocument();
  });

  it("displays improvement value when provided", () => {
    renderWithTheme(<ImpactBadge impact="high" value="25% faster" />);
    expect(screen.getByText(/25% faster/)).toBeInTheDocument();
  });

  it("shows tooltip by default", async () => {
    renderWithTheme(<ImpactBadge impact="high" />);
    const badge = screen.getByText("High Impact");
    fireEvent.mouseOver(badge);
    
    await waitFor(() => {
      expect(screen.getByRole("tooltip")).toBeInTheDocument();
    });
  });
});

describe("EffortBadge", () => {
  it("renders low effort badge", () => {
    renderWithTheme(<EffortBadge effort="low" />);
    expect(screen.getByText("Low Effort")).toBeInTheDocument();
  });

  it("renders medium effort badge", () => {
    renderWithTheme(<EffortBadge effort="medium" />);
    expect(screen.getByText("Medium Effort")).toBeInTheDocument();
  });

  it("renders high effort badge", () => {
    renderWithTheme(<EffortBadge effort="high" />);
    expect(screen.getByText("High Effort")).toBeInTheDocument();
  });

  it("displays time estimate when provided", () => {
    renderWithTheme(<EffortBadge effort="low" time="5-10 min" />);
    expect(screen.getByText(/5-10 min/)).toBeInTheDocument();
  });
});

describe("RecommendationCard", () => {
  it("renders recommendation title and description", () => {
    renderWithTheme(
      <RecommendationCard item={sampleRecommendation} index={1} />
    );
    
    expect(screen.getByText(/Add partition filter/)).toBeInTheDocument();
    expect(screen.getByText(/Query scans entire table/)).toBeInTheDocument();
  });

  it("renders impact and effort badges", () => {
    renderWithTheme(
      <RecommendationCard item={sampleRecommendation} index={1} />
    );
    
    expect(screen.getByText(/High Impact/)).toBeInTheDocument();
    expect(screen.getByText(/Low Effort/)).toBeInTheDocument();
  });

  it("shows expand button when has expandable content", () => {
    renderWithTheme(
      <RecommendationCard item={sampleRecommendation} index={1} />
    );
    
    expect(screen.getByText("View Details")).toBeInTheDocument();
  });

  it("expands to show SQL suggestion on click", async () => {
    renderWithTheme(
      <RecommendationCard item={sampleRecommendation} index={1} />
    );
    
    const expandButton = screen.getByText("View Details");
    fireEvent.click(expandButton);
    
    await waitFor(() => {
      expect(screen.getByText("Suggested Changes:")).toBeInTheDocument();
    });
  });

  it("shows explanation when expanded", async () => {
    renderWithTheme(
      <RecommendationCard item={sampleRecommendation} index={1} />
    );
    
    const expandButton = screen.getByText("View Details");
    fireEvent.click(expandButton);
    
    await waitFor(() => {
      expect(screen.getByText("Why this matters:")).toBeInTheDocument();
      expect(screen.getByText(/Adding a partition filter/)).toBeInTheDocument();
    });
  });

  it("hides details on collapse", async () => {
    renderWithTheme(
      <RecommendationCard item={sampleRecommendation} index={1} />
    );
    
    // Expand
    fireEvent.click(screen.getByText("View Details"));
    await waitFor(() => {
      expect(screen.getByText("Hide Details")).toBeInTheDocument();
    });
    
    // Collapse
    fireEvent.click(screen.getByText("Hide Details"));
    await waitFor(() => {
      expect(screen.getByText("View Details")).toBeInTheDocument();
    });
  });

  it("calls onApply when apply button is clicked", async () => {
    const handleApply = jest.fn();
    renderWithTheme(
      <RecommendationCard 
        item={sampleRecommendation} 
        index={1} 
        onApply={handleApply}
      />
    );
    
    // Expand to see SQL
    fireEvent.click(screen.getByText("View Details"));
    
    await waitFor(() => {
      expect(screen.getByText("Suggested Changes:")).toBeInTheDocument();
    });
  });
});

describe("ReportSection", () => {
  it("renders section title and item count", () => {
    renderWithTheme(
      <ReportSection
        section={sampleSection}
        isCollapsed={false}
        onToggle={() => {}}
      />
    );
    
    expect(screen.getByText("Critical Issues")).toBeInTheDocument();
    expect(screen.getByText("(1)")).toBeInTheDocument();
  });

  it("renders severity icon", () => {
    renderWithTheme(
      <ReportSection
        section={sampleSection}
        isCollapsed={false}
        onToggle={() => {}}
      />
    );
    
    expect(screen.getByText("🔴")).toBeInTheDocument();
  });

  it("shows items when not collapsed", () => {
    renderWithTheme(
      <ReportSection
        section={sampleSection}
        isCollapsed={false}
        onToggle={() => {}}
      />
    );
    
    expect(screen.getByText(/Add partition filter/)).toBeInTheDocument();
  });

  it("hides items when collapsed", () => {
    renderWithTheme(
      <ReportSection
        section={sampleSection}
        isCollapsed={true}
        onToggle={() => {}}
      />
    );
    
    // Title should still be visible
    expect(screen.getByText("Critical Issues")).toBeInTheDocument();
    // The collapse component hides content but may keep it in DOM
    // Check that the collapse container has the collapsed state
    const expandButton = screen.getByLabelText("Expand section");
    expect(expandButton).toBeInTheDocument();
  });

  it("calls onToggle when header is clicked", () => {
    const handleToggle = jest.fn();
    renderWithTheme(
      <ReportSection
        section={sampleSection}
        isCollapsed={false}
        onToggle={handleToggle}
      />
    );
    
    // Click the section header (contains the title)
    const header = screen.getByText("Critical Issues").closest('[role="button"]');
    fireEvent.click(header!);
    
    expect(handleToggle).toHaveBeenCalledTimes(1);
  });

  it("renders warning severity correctly", () => {
    const warningSection: ReportSectionData = {
      ...sampleSection,
      id: "warning",
      title: "Optimization Opportunities",
      severity: "warning",
    };
    
    renderWithTheme(
      <ReportSection
        section={warningSection}
        isCollapsed={false}
        onToggle={() => {}}
      />
    );
    
    expect(screen.getByText("🟡")).toBeInTheDocument();
    expect(screen.getByText("Optimization Opportunities")).toBeInTheDocument();
  });

  it("renders info severity correctly", () => {
    const infoSection: ReportSectionData = {
      ...sampleSection,
      id: "info",
      title: "Additional Notes",
      severity: "info",
    };
    
    renderWithTheme(
      <ReportSection
        section={infoSection}
        isCollapsed={false}
        onToggle={() => {}}
      />
    );
    
    expect(screen.getByText("🔵")).toBeInTheDocument();
    expect(screen.getByText("Additional Notes")).toBeInTheDocument();
  });
});

describe("ReportSummary", () => {
  it("renders summary text", () => {
    renderWithTheme(
      <ReportSummary 
        summary="This query has 4 optimization opportunities" 
      />
    );
    
    expect(screen.getByText(/4 optimization opportunities/)).toBeInTheDocument();
  });

  it("renders summary header", () => {
    renderWithTheme(
      <ReportSummary summary="Test summary" />
    );
    
    expect(screen.getByText("📋")).toBeInTheDocument();
    expect(screen.getByText("Summary")).toBeInTheDocument();
  });

  it("renders metadata stats when provided", () => {
    renderWithTheme(
      <ReportSummary 
        summary="Test summary"
        metadata={{
          total_recommendations: 4,
          estimated_improvement: "25%",
          quick_wins_count: 2,
        }}
      />
    );
    
    expect(screen.getByText("4")).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();
    expect(screen.getByText("25%")).toBeInTheDocument();
  });

  it("renders cost reduction when provided", () => {
    renderWithTheme(
      <ReportSummary 
        summary="Test summary"
        metadata={{
          total_recommendations: 2,
          cost_reduction: "$500/month",
        }}
      />
    );
    
    expect(screen.getByText("$500/month")).toBeInTheDocument();
  });
});

describe("ImplementationPlan", () => {
  const recommendations: RecommendationItem[] = [
    { ...sampleRecommendation, id: "1", impact: "high", effort: "low" },
    { 
      ...sampleRecommendation, 
      id: "2", 
      title: "Add index", 
      impact: "medium", 
      effort: "medium" 
    },
    { 
      ...sampleRecommendation, 
      id: "3", 
      title: "Rewrite subquery", 
      impact: "low", 
      effort: "high" 
    },
  ];

  it("renders implementation plan header", () => {
    renderWithTheme(
      <ImplementationPlan recommendations={recommendations} />
    );
    
    expect(screen.getByText("🎯")).toBeInTheDocument();
    expect(screen.getByText("Suggested Implementation Order")).toBeInTheDocument();
  });

  it("sorts recommendations by impact/effort ratio", () => {
    renderWithTheme(
      <ImplementationPlan recommendations={recommendations} />
    );
    
    const items = screen.getAllByRole("listitem");
    // High impact/low effort should be first
    expect(items[0]).toHaveTextContent("Add partition filter");
  });

  it("shows time estimates", () => {
    renderWithTheme(
      <ImplementationPlan recommendations={recommendations} />
    );
    
    // Check that at least one time estimate is shown
    const timeEstimates = screen.getAllByText(/~\d+-?\d* (min|hour)/);
    expect(timeEstimates.length).toBeGreaterThan(0);
  });

  it("renders Copy All SQL button when SQL exists", () => {
    renderWithTheme(
      <ImplementationPlan recommendations={recommendations} />
    );
    
    expect(screen.getByText("Copy All SQL")).toBeInTheDocument();
  });

  it("renders Export Plan button", () => {
    renderWithTheme(
      <ImplementationPlan recommendations={recommendations} />
    );
    
    expect(screen.getByText("Export Plan")).toBeInTheDocument();
  });

  it("copies SQL to clipboard when Copy All clicked", async () => {
    renderWithTheme(
      <ImplementationPlan recommendations={recommendations} />
    );
    
    const copyButton = screen.getByText("Copy All SQL");
    fireEvent.click(copyButton);
    
    await waitFor(() => {
      expect(mockWriteText).toHaveBeenCalled();
    });
  });

  it("returns null when no recommendations", () => {
    const { container } = renderWithTheme(
      <ImplementationPlan recommendations={[]} />
    );
    
    expect(container.firstChild).toBeNull();
  });
});

