/**
 * Tests for DiagnosticReportBubble component.
 */

import React from "react";
import { render, screen } from "@testing-library/react";
import { ThemeProvider, createTheme } from "@mui/material/styles";
import { DiagnosticReportBubble } from "../DiagnosticReportBubble";
import type { Message, DiagnosticReport } from "@/lib/types/api";
import { MessageRole, MessageStatus } from "@/lib/types/api";

const theme = createTheme();

const mockMessage: Message = {
  id: "msg-1",
  message_id: "msg-1",
  conversation_id: "conv-1",
  role: MessageRole.ASSISTANT,
  content: "Diagnostic analysis complete.",
  status: MessageStatus.COMPLETED,
  timestamp: new Date().toISOString(),
  metadata: {
    complete_report: {},
    tokens_used: 1500,
    cost_usd: 0.0045,
    duration_seconds: 2.5,
  },
};

const mockReport: DiagnosticReport = {
  report_type: "diagnostic",
  summary: {
    overview: "Your job failed due to an Out of Memory (OOM) error.",
    artifact_type: "stack_trace",
    mode: "offline",
    confidence: 0.85,
  },
  evidence_windows: [
    {
      id: "EV001",
      type: "exception",
      content: "java.lang.OutOfMemoryError: Java heap space",
      line_start: 45,
      line_end: 45,
      confidence: 0.95,
    },
    {
      id: "EV002",
      type: "error",
      content: "Exit code 137 - Container killed by YARN",
      line_start: 120,
      line_end: 120,
      confidence: 0.8,
    },
  ],
  findings: [
    {
      id: "F001",
      category: "MEMORY",
      title: "Java Heap Space Exhaustion",
      confidence: "high",
      explanation:
        "The executor ran out of heap memory during a shuffle operation.",
      evidence_refs: ["EV001", "EV002"],
      recommendations: [
        "Increase spark.executor.memory to 8g",
        "Enable dynamic allocation",
      ],
      pattern_id: "java_heap_space",
    },
    {
      id: "F002",
      category: "DATA",
      title: "Possible Data Skew",
      confidence: "medium",
      explanation:
        "The failure pattern suggests some partitions may have significantly more data than others.",
      evidence_refs: ["EV001"],
      recommendations: [
        "Check partition sizes with df.groupBy(spark_partition_id()).count()",
        "Consider salting the join key",
      ],
    },
  ],
  fingerprint: {
    primary_symptom: "oom",
    likely_root_causes: ["heap_exhaustion", "data_skew"],
    extracted_context: { job_id: "12345", cluster_id: "0123-456789-abc" },
    evidence_snippets: ["EV001", "EV002"],
    recommended_handoff_target: "cluster",
  },
};

describe("DiagnosticReportBubble", () => {
  const renderComponent = (
    report: DiagnosticReport = mockReport,
    message: Message = mockMessage
  ) => {
    return render(
      <ThemeProvider theme={theme}>
        <DiagnosticReportBubble message={message} report={report} />
      </ThemeProvider>
    );
  };

  it("renders the report title", () => {
    renderComponent();
    expect(screen.getByText(/Diagnostic Analysis/)).toBeInTheDocument();
  });

  it("displays the overview", () => {
    renderComponent();
    expect(
      screen.getByText(/Your job failed due to an Out of Memory/)
    ).toBeInTheDocument();
  });

  it("shows confidence meter", () => {
    renderComponent();
    expect(screen.getByText("85%")).toBeInTheDocument();
    expect(screen.getByText("Confidence")).toBeInTheDocument();
  });

  it("displays mode badge", () => {
    renderComponent();
    expect(screen.getByText("Mode: OFFLINE")).toBeInTheDocument();
  });

  it("displays artifact type badge", () => {
    renderComponent();
    expect(screen.getByText("Artifact: stack_trace")).toBeInTheDocument();
  });

  it("renders findings count", () => {
    renderComponent();
    expect(screen.getByText(/Findings \(2\)/)).toBeInTheDocument();
  });

  it("renders finding cards", () => {
    renderComponent();
    expect(screen.getByText("Java Heap Space Exhaustion")).toBeInTheDocument();
    expect(screen.getByText("Possible Data Skew")).toBeInTheDocument();
  });

  it("displays finding categories", () => {
    renderComponent();
    expect(screen.getByText("MEMORY")).toBeInTheDocument();
    expect(screen.getByText("DATA")).toBeInTheDocument();
  });

  it("displays confidence levels on findings", () => {
    renderComponent();
    expect(screen.getByText("high")).toBeInTheDocument();
    expect(screen.getByText("medium")).toBeInTheDocument();
  });

  it("renders evidence section", () => {
    renderComponent();
    expect(screen.getByText(/All Evidence \(2 items\)/)).toBeInTheDocument();
  });

  it("shows handoff recommendation when present", () => {
    renderComponent();
    expect(screen.getByText("Specialist Recommended")).toBeInTheDocument();
    expect(screen.getByText(/cluster/)).toBeInTheDocument();
  });

  it("renders without findings gracefully", () => {
    const reportNoFindings: DiagnosticReport = {
      ...mockReport,
      findings: [],
    };
    renderComponent(reportNoFindings);
    expect(screen.queryByText(/Findings/)).not.toBeInTheDocument();
  });

  it("renders high confidence as 'Diagnosis'", () => {
    const highConfidenceReport: DiagnosticReport = {
      ...mockReport,
      summary: { ...mockReport.summary, confidence: 0.95 },
    };
    renderComponent(highConfidenceReport);
    expect(screen.getByText("Diagnosis")).toBeInTheDocument();
  });

  it("renders medium confidence as 'Likely Diagnosis'", () => {
    renderComponent(); // 0.85 confidence
    expect(screen.getByText("Likely Diagnosis")).toBeInTheDocument();
  });

  it("renders low confidence as 'Analysis'", () => {
    const lowConfidenceReport: DiagnosticReport = {
      ...mockReport,
      summary: { ...mockReport.summary, confidence: 0.5 },
    };
    renderComponent(lowConfidenceReport);
    expect(screen.getByText("Analysis")).toBeInTheDocument();
  });

  it("displays online mode correctly", () => {
    const onlineReport: DiagnosticReport = {
      ...mockReport,
      summary: { ...mockReport.summary, mode: "online" },
    };
    renderComponent(onlineReport);
    expect(screen.getByText("Mode: ONLINE")).toBeInTheDocument();
  });

  it("displays hybrid mode correctly", () => {
    const hybridReport: DiagnosticReport = {
      ...mockReport,
      summary: { ...mockReport.summary, mode: "hybrid" },
    };
    renderComponent(hybridReport);
    expect(screen.getByText("Mode: HYBRID")).toBeInTheDocument();
  });

  it("shows budget exhausted warning when true", () => {
    const exhaustedReport: DiagnosticReport = {
      ...mockReport,
      budget_exhausted: true,
    };
    renderComponent(exhaustedReport);
    // Budget exhausted alert contains this specific text
    expect(
      screen.getByText(/Token Budget Exhausted/i)
    ).toBeInTheDocument();
  });
});

