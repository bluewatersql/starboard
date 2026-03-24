/**
 * ExampleQueries - Display example query cards on homepage.
 *
 * Shows 6-8 example queries categorized by use case that users
 * can click to populate the HeroPrompt.
 *
 * UX vNext Phase 1: FT-005
 */

"use client";

import React from "react";
import { Box, Card, CardContent, Typography, Grid, Chip } from "@mui/material";
import WorkIcon from "@mui/icons-material/Work";
import QueryStatsIcon from "@mui/icons-material/QueryStats";
import TableChartIcon from "@mui/icons-material/TableChart";
import AttachMoneyIcon from "@mui/icons-material/AttachMoney";

interface ExampleQuery {
  id: string;
  category: "Job" | "Query" | "Table" | "Cost";
  text: string;
  icon: React.ReactNode;
}

const EXAMPLE_QUERIES: ExampleQuery[] = [
  {
    id: "job-performance",
    category: "Job",
    text: "Analyze job performance for job 12345 and suggest optimizations",
    icon: <WorkIcon />,
  },
  {
    id: "job-failures",
    category: "Job",
    text: "Why did job 67890 fail in the last run?",
    icon: <WorkIcon />,
  },
  {
    id: "query-slow",
    category: "Query",
    text: "Why is query q_abc123 running slowly?",
    icon: <QueryStatsIcon />,
  },
  {
    id: "query-optimize",
    category: "Query",
    text: "Optimize this query: SELECT * FROM large_table WHERE date > '2024-01-01'",
    icon: <QueryStatsIcon />,
  },
  {
    id: "table-schema",
    category: "Table",
    text: "Show me the schema and statistics for table sales.customer_orders",
    icon: <TableChartIcon />,
  },
  {
    id: "table-lineage",
    category: "Table",
    text: "What is the lineage for table analytics.daily_metrics?",
    icon: <TableChartIcon />,
  },
  {
    id: "cost-analysis",
    category: "Cost",
    text: "Analyze cost trends for the last 30 days",
    icon: <AttachMoneyIcon />,
  },
  {
    id: "cost-warehouse",
    category: "Cost",
    text: "Which warehouse is consuming the most credits?",
    icon: <AttachMoneyIcon />,
  },
];

interface ExampleQueriesProps {
  /**
   * Callback when an example query is selected.
   * Receives the query text to populate HeroPrompt.
   */
  onSelect?: (queryText: string) => void;
  
  /**
   * Optional className for styling.
   */
  className?: string;
}

export function ExampleQueries({ onSelect, className }: ExampleQueriesProps) {
  const handleQueryClick = (query: ExampleQuery) => {
    if (onSelect) {
      onSelect(query.text);
    }
  };

  return (
    <Box className={className}>
      <Typography
        variant="h6"
        sx={{
          mb: 3,
          textAlign: "center",
          color: "text.secondary",
        }}
      >
        Example Queries
      </Typography>

      <Grid container spacing={2}>
        {EXAMPLE_QUERIES.map((query) => (
          <Grid key={query.id} size={{ xs: 12, sm: 6, md: 3 }}>
            <Card
              component="button"
              onClick={() => handleQueryClick(query)}
              sx={{
                height: "100%",
                textAlign: "left",
                cursor: "pointer",
                border: "1px solid",
                borderColor: "divider",
                transition: "all 0.2s ease",
                background: "transparent",
                padding: 0,
                width: "100%",
                "&:hover": {
                  borderColor: "primary.main",
                  transform: "translateY(-2px)",
                  boxShadow: 2,
                  backgroundColor: "action.hover",
                },
                "&:focus": {
                  outline: "2px solid",
                  outlineColor: "primary.main",
                  outlineOffset: "2px",
                },
                "&:active": {
                  transform: "translateY(0)",
                },
              }}
            >
              <CardContent
                sx={{
                  display: "flex",
                  flexDirection: "column",
                  gap: 1,
                  height: "100%",
                }}
              >
                {/* Category Chip */}
                <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
                  <Box
                    sx={{
                      color: "primary.main",
                      display: "flex",
                      fontSize: "1.25rem",
                    }}
                  >
                    {query.icon}
                  </Box>
                  <Chip
                    label={query.category}
                    size="small"
                    variant="outlined"
                    sx={{
                      fontSize: "0.75rem",
                      height: "20px",
                    }}
                  />
                </Box>

                {/* Query Text */}
                <Typography
                  variant="body2"
                  sx={{
                    flex: 1,
                    color: "text.primary",
                    lineHeight: 1.5,
                  }}
                >
                  {query.text}
                </Typography>
              </CardContent>
            </Card>
          </Grid>
        ))}
      </Grid>

      {/* Helper Text */}
      <Typography
        variant="caption"
        color="text.secondary"
        sx={{
          display: "block",
          mt: 2,
          textAlign: "center",
        }}
      >
        Click any example to get started
      </Typography>
    </Box>
  );
}

