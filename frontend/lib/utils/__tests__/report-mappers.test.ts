/**
 * Tests for report data transformation utilities.
 */

import {
  convertImpactEstimate,
  extractSQLFromFixes,
  formatCategory,
  formatImpactPercentage,
  formatEffortTime,
  mapFindingsToRecommendations,
  hasRecommendations,
  extractFindings,
  type Finding,
} from "../report-mappers";

describe("convertImpactEstimate", () => {
  it("should return 'high' for query_time_pct >= 20%", () => {
    expect(
      convertImpactEstimate({
        query_time_pct: 25,
        confidence: "high",
      })
    ).toBe("high");

    expect(
      convertImpactEstimate({
        query_time_pct: 20,
        confidence: "medium",
      })
    ).toBe("high");
  });

  it("should return 'medium' for query_time_pct 10-19%", () => {
    expect(
      convertImpactEstimate({
        query_time_pct: 15,
        confidence: "medium",
      })
    ).toBe("medium");

    expect(
      convertImpactEstimate({
        query_time_pct: 10,
        confidence: "low",
      })
    ).toBe("medium");
  });

  it("should return 'low' for query_time_pct < 10%", () => {
    expect(
      convertImpactEstimate({
        query_time_pct: 5,
        confidence: "low",
      })
    ).toBe("low");

    expect(
      convertImpactEstimate({
        query_time_pct: 0,
        confidence: "low",
      })
    ).toBe("low");
  });

  it("should fallback to cost_pct if query_time_pct is zero", () => {
    expect(
      convertImpactEstimate({
        query_time_pct: 0,
        cost_pct: 30,
        confidence: "high",
      })
    ).toBe("high");

    expect(
      convertImpactEstimate({
        query_time_pct: 0,
        cost_pct: 15,
        confidence: "medium",
      })
    ).toBe("medium");

    expect(
      convertImpactEstimate({
        query_time_pct: 0,
        cost_pct: 5,
        confidence: "low",
      })
    ).toBe("low");
  });

  it("should prioritize query_time_pct over cost_pct", () => {
    expect(
      convertImpactEstimate({
        query_time_pct: 25,
        cost_pct: 5,
        confidence: "high",
      })
    ).toBe("high");
  });
});

describe("extractSQLFromFixes", () => {
  it("should return SQL from SQL_REWRITE fix", () => {
    const fixes = [
      {
        type: "SQL_REWRITE" as const,
        snippet: "SELECT * FROM table WHERE date = '2024-01-01'",
        notes: "Add date filter",
      },
    ];

    expect(extractSQLFromFixes(fixes)).toBe(
      "SELECT * FROM table WHERE date = '2024-01-01'"
    );
  });

  it("should return SQL from DDL_DML fix", () => {
    const fixes = [
      {
        type: "DDL_DML" as const,
        snippet: "CREATE INDEX idx_user_id ON users(user_id)",
        notes: "Add index",
      },
    ];

    expect(extractSQLFromFixes(fixes)).toBe(
      "CREATE INDEX idx_user_id ON users(user_id)"
    );
  });

  it("should prioritize SQL_REWRITE over other types", () => {
    const fixes = [
      {
        type: "CONFIG_CHANGE" as const,
        snippet: "spark.sql.adaptive.enabled = true",
      },
      {
        type: "SQL_REWRITE" as const,
        snippet: "SELECT DISTINCT user_id FROM users",
      },
    ];

    expect(extractSQLFromFixes(fixes)).toBe(
      "SELECT DISTINCT user_id FROM users"
    );
  });

  it("should return first non-SQL fix as fallback", () => {
    const fixes = [
      {
        type: "CONFIG_CHANGE" as const,
        snippet: "spark.sql.shuffle.partitions = 200",
      },
    ];

    expect(extractSQLFromFixes(fixes)).toBe(
      "spark.sql.shuffle.partitions = 200"
    );
  });

  it("should return undefined for empty array", () => {
    expect(extractSQLFromFixes([])).toBeUndefined();
  });

  it("should return undefined for undefined input", () => {
    expect(extractSQLFromFixes(undefined)).toBeUndefined();
  });

  it("should skip fixes with empty snippets", () => {
    const fixes = [
      {
        type: "SQL_REWRITE" as const,
        snippet: "",
      },
      {
        type: "DDL_DML" as const,
        snippet: "CREATE TABLE foo AS SELECT * FROM bar",
      },
    ];

    expect(extractSQLFromFixes(fixes)).toBe(
      "CREATE TABLE foo AS SELECT * FROM bar"
    );
  });
});

describe("formatCategory", () => {
  it("should convert SCREAMING_SNAKE_CASE to Title Case", () => {
    expect(formatCategory("QUERY_OPTIMIZATION")).toBe("Query Optimization");
    expect(formatCategory("TABLE_LAYOUT")).toBe("Table Layout");
    expect(formatCategory("CLUSTER_CONFIG")).toBe("Cluster Config");
  });

  it("should handle single-word categories", () => {
    expect(formatCategory("QUERY")).toBe("Query");
    expect(formatCategory("TABLE")).toBe("Table");
    expect(formatCategory("WAREHOUSE")).toBe("Warehouse");
  });

  it("should handle lowercase input", () => {
    expect(formatCategory("query")).toBe("Query");
    expect(formatCategory("table")).toBe("Table");
  });
});

describe("formatImpactPercentage", () => {
  it("should format query_time_pct as percentage", () => {
    expect(
      formatImpactPercentage({
        query_time_pct: 25,
        confidence: "high",
      })
    ).toBe("~25% faster");

    expect(
      formatImpactPercentage({
        query_time_pct: 15.7,
        confidence: "medium",
      })
    ).toBe("~16% faster");
  });

  it("should format cost_pct when query_time_pct is zero", () => {
    expect(
      formatImpactPercentage({
        query_time_pct: 0,
        cost_pct: 30,
        confidence: "high",
      })
    ).toBe("~30% cheaper");
  });

  it("should format data_read_pct as fallback", () => {
    expect(
      formatImpactPercentage({
        query_time_pct: 0,
        cost_pct: 0,
        data_read_pct: 40,
        confidence: "medium",
      })
    ).toBe("~40% less data");
  });

  it("should return undefined when all percentages are zero", () => {
    expect(
      formatImpactPercentage({
        query_time_pct: 0,
        cost_pct: 0,
        data_read_pct: 0,
        confidence: "low",
      })
    ).toBeUndefined();
  });

  it("should prioritize query_time_pct over other metrics", () => {
    expect(
      formatImpactPercentage({
        query_time_pct: 20,
        cost_pct: 50,
        data_read_pct: 60,
        confidence: "high",
      })
    ).toBe("~20% faster");
  });
});

describe("formatEffortTime", () => {
  it("should format estimate_hours as time string", () => {
    expect(formatEffortTime({ level: "low", estimate_hours: 0.5 })).toBe(
      "0.5h"
    );
    expect(formatEffortTime({ level: "medium", estimate_hours: 2 })).toBe("2h");
    expect(formatEffortTime({ level: "high", estimate_hours: 8 })).toBe("8h");
  });

  it("should return undefined when estimate_hours is null", () => {
    expect(formatEffortTime({ level: "low", estimate_hours: null })).toBeUndefined();
  });

  it("should return undefined when estimate_hours is missing", () => {
    expect(formatEffortTime({ level: "medium" })).toBeUndefined();
  });
});

describe("mapFindingsToRecommendations", () => {
  const mockFinding: Finding = {
    id: "finding_1",
    title: "Add partition filter",
    recommendation: "Query scans entire table without partition pruning",
    category: "QUERY",
    impact_estimate: {
      query_time_pct: 25,
      data_read_pct: 30,
      cost_pct: 20,
      confidence: "high",
    },
    effort: {
      level: "low",
      estimate_hours: 0.5,
    },
    fixes: [
      {
        type: "SQL_REWRITE",
        snippet: "WHERE partition_date = '2024-01-01'",
        notes: "Add partition filter to reduce data scanned",
      },
    ],
    rank: 1,
  };

  it("should transform finding to recommendation format", () => {
    const recommendations = mapFindingsToRecommendations([mockFinding]);

    expect(recommendations).toHaveLength(1);
    expect(recommendations[0]).toEqual({
      id: "finding_1",
      title: "Add partition filter",
      description: "Query scans entire table without partition pruning",
      explanation: "Query scans entire table without partition pruning",
      impact: "high",
      effort: "low",
      category: "Query",
      sql_suggestion: "WHERE partition_date = '2024-01-01'",
      estimated_improvement: "~25% faster",
      estimated_time: "0.5h",
    });
  });

  it("should handle multiple findings", () => {
    const findings = [
      mockFinding,
      {
        ...mockFinding,
        id: "finding_2",
        title: "Add index",
        category: "TABLE",
        impact_estimate: { query_time_pct: 15, confidence: "medium" },
        effort: { level: "medium" },
        fixes: [],
      } as Finding,
    ];

    const recommendations = mapFindingsToRecommendations(findings);
    expect(recommendations).toHaveLength(2);
    expect(recommendations[1].id).toBe("finding_2");
    expect(recommendations[1].impact).toBe("medium");
    expect(recommendations[1].sql_suggestion).toBeUndefined();
  });

  it("should handle findings without fixes", () => {
    const finding: Finding = {
      ...mockFinding,
      fixes: undefined,
    };

    const recommendations = mapFindingsToRecommendations([finding]);
    expect(recommendations[0].sql_suggestion).toBeUndefined();
  });

  it("should handle findings without estimate_hours", () => {
    const finding: Finding = {
      ...mockFinding,
      effort: { level: "medium" },
    };

    const recommendations = mapFindingsToRecommendations([finding]);
    expect(recommendations[0].estimated_time).toBeUndefined();
  });

  it("should return empty array for null input", () => {
    expect(mapFindingsToRecommendations(null as never)).toEqual([]);
  });

  it("should return empty array for undefined input", () => {
    expect(mapFindingsToRecommendations(undefined as never)).toEqual([]);
  });

  it("should return empty array for non-array input", () => {
    expect(mapFindingsToRecommendations({} as never)).toEqual([]);
  });
});

describe("hasRecommendations", () => {
  it("should return true for report with findings", () => {
    const report = {
      analysis: {
        findings: [
          {
            id: "1",
            title: "Test",
            recommendation: "Do something",
            category: "QUERY",
            impact_estimate: { query_time_pct: 10, confidence: "medium" },
            effort: { level: "low" },
            rank: 1,
          },
        ],
      },
    };

    expect(hasRecommendations(report)).toBe(true);
  });

  it("should return false for report with empty findings", () => {
    expect(hasRecommendations({ analysis: { findings: [] } })).toBe(false);
  });

  it("should return false for report without analysis", () => {
    expect(hasRecommendations({ other: "data" })).toBe(false);
  });

  it("should return false for null input", () => {
    expect(hasRecommendations(null)).toBe(false);
  });

  it("should return false for undefined input", () => {
    expect(hasRecommendations(undefined)).toBe(false);
  });

  it("should return false for non-object input", () => {
    expect(hasRecommendations("string")).toBe(false);
    expect(hasRecommendations(123)).toBe(false);
  });
});

describe("extractFindings", () => {
  const mockFinding = {
    id: "1",
    title: "Test",
    recommendation: "Do something",
    category: "QUERY",
    impact_estimate: { query_time_pct: 10, confidence: "medium" },
    effort: { level: "low" },
    rank: 1,
  };

  it("should extract findings from nested structure", () => {
    const report = {
      analysis: {
        findings: [mockFinding],
      },
    };

    const findings = extractFindings(report);
    expect(findings).toHaveLength(1);
    expect(findings[0].id).toBe("1");
  });

  it("should extract findings from flat structure", () => {
    const report = {
      findings: [mockFinding],
    };

    const findings = extractFindings(report);
    expect(findings).toHaveLength(1);
    expect(findings[0].id).toBe("1");
  });

  it("should prioritize nested structure over flat", () => {
    const report = {
      analysis: {
        findings: [{ ...mockFinding, id: "nested" }],
      },
      findings: [{ ...mockFinding, id: "flat" }],
    };

    const findings = extractFindings(report);
    expect(findings[0].id).toBe("nested");
  });

  it("should return empty array for report without findings", () => {
    expect(extractFindings({ other: "data" })).toEqual([]);
  });

  it("should return empty array for null input", () => {
    expect(extractFindings(null)).toEqual([]);
  });

  it("should return empty array for undefined input", () => {
    expect(extractFindings(undefined)).toEqual([]);
  });

  it("should return empty array for non-object input", () => {
    expect(extractFindings("string")).toEqual([]);
    expect(extractFindings(123)).toEqual([]);
  });
});

