# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Golden tests for unified optimization schemas across all domains.

These tests validate the structure and field requirements of optimization
report schemas for query, job, table, compute, and diagnostic domains.

The schemas ensure consistent, detailed output across all agents including:
- Summary with current state
- Analysis findings with evidence, impact estimates, and effort
- Testing/validation plans
- Prioritized next steps (1-4 actions)
"""

import pytest
from starboard_core.domain.models.llm_schemas import (
    Finding,
    OptimizerAdvisorReport,
)


class TestQueryOptimizationSchema:
    """Test query optimization report schema."""

    def test_query_report_complete_structure(self):
        """Test complete query optimization report validates correctly."""
        valid_report = {
            "summary": {
                "overview": "Query analysis reveals partition pruning opportunity",
                "current_state": {
                    "cloud_provider": "AWS",
                    "runtime_version": "13.3 LTS",
                    "warehouse_tier": "Pro",
                    "warehouse_size": "Medium",
                    "key_symptoms": [
                        "High data read",
                        "Long duration",
                        "Full table scan",
                    ],
                },
            },
            "analysis": {
                "findings": [
                    {
                        "id": "query_finding_001",
                        "category": "QUERY",
                        "title": "Missing partition predicate causing full table scan",
                        "recommendation": "Add partition filter to WHERE clause to reduce data scanned by 95%",
                        "fixes": [
                            {
                                "type": "SQL_REWRITE",
                                "snippet": "-- Before:\nSELECT * FROM sales WHERE amount > 1000\n\n-- After:\nSELECT * FROM sales WHERE date >= '2024-01-01' AND amount > 1000",
                                "notes": "Table is partitioned by 'date'. Adding partition filter reduces scan from 10TB to 500GB.",
                            }
                        ],
                        "proofs": {
                            "evidence": [
                                "Explain plan shows full table scan on 'sales' (10TB, 50B rows)",
                                "Table metadata shows partitioning by 'date' column",
                                "Query reads all 365 partitions but only needs last 30 days",
                            ],
                            "code_line_refs": [{"object": "explain_plan", "line": 12}],
                            "references": [
                                {
                                    "title": "Partition Pruning in Databricks",
                                    "url": "https://docs.databricks.com/delta/partition-optimization.html",
                                    "cloud": "aws",
                                }
                            ],
                        },
                        "impact_estimate": {
                            "query_time_pct": -85.0,
                            "data_read_pct": -95.0,
                            "shuffle_pct": 0.0,
                            "cost_pct": -90.0,
                            "confidence": "high",
                        },
                        "effort": {"level": "low", "estimate_hours": 0.5},
                        "risks": ["Ensure date filter matches business logic"],
                        "rank": 1,
                    }
                ],
                "query_rewrite": {
                    "applicable": True,
                    "sql": "SELECT * FROM sales WHERE date >= '2024-01-01' AND amount > 1000",
                    "notes": "Added partition filter to enable partition pruning",
                },
            },
            "next_steps": [
                {
                    "id": "analyze_partitioning",
                    "number": 1,
                    "title": "Analyze table partitioning strategy",
                    "description": "Would you like me to analyze the table partitioning strategy in more detail?",
                    "action_type": "continue",
                },
                {
                    "id": "check_slow_queries",
                    "number": 2,
                    "title": "Check top 5 slowest queries",
                    "description": "Shall I check the top 5 slowest queries for similar issues?",
                    "action_type": "continue",
                },
            ],
        }

        # Validate against Pydantic model
        report = OptimizerAdvisorReport.model_validate(valid_report)

        # Assertions
        assert report.summary.overview
        assert report.summary.current_state.cloud_provider == "AWS"
        assert len(report.analysis.findings) == 1
        assert report.analysis.findings[0].category == "QUERY"
        assert report.analysis.findings[0].impact_estimate.query_time_pct == -85.0
        assert report.analysis.findings[0].effort.level == "low"
        assert report.analysis.query_rewrite.applicable is True
        assert len(report.next_steps) == 2
        assert report.next_steps[0].number == 1


class TestJobOptimizationSchema:
    """Test job optimization report schema."""

    def test_job_report_with_code_findings(self):
        """Test job optimization report with code-level findings."""
        valid_report = {
            "summary": {
                "overview": "Job analysis reveals inefficient broadcast join causing OOM errors",
                "current_state": {
                    "cloud_provider": "AWS",
                    "runtime_version": "13.3 LTS",
                    "cluster_type": "Job Compute",
                    "cluster_size": "Standard_DS3_v2 (4 cores, 14GB)",
                    "key_symptoms": [
                        "High shuffle",
                        "OOM errors",
                        "Long task duration",
                    ],
                },
            },
            "analysis": {
                "findings": [
                    {
                        "id": "job_finding_001",
                        "category": "CODE",
                        "title": "Large broadcast join causing OOM",
                        "recommendation": "Filter broadcast table before join to reduce size from 5GB to 500MB",
                        "fixes": [
                            {
                                "type": "CODE_REWRITE",
                                "snippet": "# Before:\nlarge_df.join(broadcast(small_df), 'id')\n\n# After:\nfiltered_df = small_df.filter(col('active') == True)\nlarge_df.join(filtered_df, 'id')",
                                "notes": "80% of rows are filtered out later anyway. Filter first to avoid OOM.",
                            }
                        ],
                        "proofs": {
                            "evidence": [
                                "Spark logs show OOM during broadcast exchange in task 23",
                                "Broadcast table is 5GB but driver memory is 2GB",
                                "Code analysis shows 80% of broadcast rows filtered in subsequent operations",
                            ],
                            "code_line_refs": [
                                {"object": "notebook_cell_5", "line": 23}
                            ],
                            "references": [
                                {
                                    "title": "Join Optimization in Spark",
                                    "url": "https://docs.databricks.com/spark/latest/spark-sql/join-optimization.html",
                                    "cloud": "aws",
                                }
                            ],
                        },
                        "impact_estimate": {
                            "query_time_pct": -60.0,
                            "data_read_pct": 0.0,
                            "shuffle_pct": -80.0,
                            "cost_pct": -50.0,
                            "confidence": "high",
                        },
                        "effort": {"level": "low", "estimate_hours": 1.0},
                        "risks": [
                            "Verify filter logic with business stakeholder",
                            "Test on full dataset to ensure no data loss",
                        ],
                        "rank": 1,
                    }
                ],
            },
            "next_steps": [
                {
                    "id": "step_1",
                    "number": 1,
                    "title": "Would you like me to analyze the...",
                    "description": "Would you like me to analyze the Spark logs for additional optimization opportunities?",
                    "action_type": "continue",
                }
            ],
        }

        # Validate
        report = OptimizerAdvisorReport.model_validate(valid_report)

        # Assertions
        assert report.analysis.findings[0].category == "CODE"
        assert report.analysis.findings[0].fixes[0].type == "CODE_REWRITE"
        assert "OOM" in report.summary.current_state.key_symptoms[1]
        assert report.analysis.query_rewrite is None  # Not required for job domain


class TestTableOptimizationSchema:
    """Test table optimization report schema."""

    def test_table_report_with_optimization_findings(self):
        """Test table optimization report with maintenance recommendations."""
        valid_report = {
            "summary": {
                "overview": "Table analysis shows stale statistics impacting query performance",
                "current_state": {
                    "cloud_provider": "AWS",
                    "runtime_version": "13.3 LTS",
                    "table_format": "Delta",
                    "key_symptoms": [
                        "Stale statistics",
                        "No optimization history",
                        "Large table (1TB)",
                    ],
                },
            },
            "analysis": {
                "findings": [
                    {
                        "id": "table_finding_001",
                        "category": "TABLE",
                        "title": "Stale table statistics impacting query performance",
                        "recommendation": "Run ANALYZE TABLE to update statistics used by query optimizer",
                        "fixes": [
                            {
                                "type": "DDL_DML",
                                "snippet": "ANALYZE TABLE catalog.schema.sales COMPUTE STATISTICS FOR ALL COLUMNS",
                                "notes": "Run during off-peak hours. Takes ~10 minutes for 1TB table.",
                            }
                        ],
                        "proofs": {
                            "evidence": [
                                "Last statistics update was 90 days ago",
                                "Table has grown from 500GB to 1TB since last ANALYZE",
                                "20+ downstream queries show sub-optimal query plans",
                            ],
                            "code_line_refs": [],
                            "references": [
                                {
                                    "title": "Table Statistics in Databricks",
                                    "url": "https://docs.databricks.com/sql/language-manual/sql-ref-syntax-aux-analyze-table.html",
                                    "cloud": "aws",
                                }
                            ],
                        },
                        "impact_estimate": {
                            "query_time_pct": -20.0,
                            "data_read_pct": 0.0,
                            "shuffle_pct": 0.0,
                            "cost_pct": -15.0,
                            "confidence": "high",
                        },
                        "effort": {"level": "low", "estimate_hours": 0.5},
                        "risks": [
                            "Requires READ permission",
                            "May take 10-30 minutes for large tables",
                        ],
                        "rank": 1,
                    }
                ],
            },
            "next_steps": [
                {
                    "id": "step_1",
                    "number": 1,
                    "title": "Would you like me to analyze downstream...",
                    "description": "Would you like me to analyze downstream queries that use this table?",
                    "action_type": "continue",
                }
            ],
        }

        # Validate
        report = OptimizerAdvisorReport.model_validate(valid_report)

        # Assertions
        assert report.analysis.findings[0].category == "TABLE"
        assert report.analysis.findings[0].fixes[0].type == "DDL_DML"
        assert report.summary.current_state.table_format == "Delta"


class TestComputeOptimizationSchema:
    """Test compute optimization report schema."""

    def test_compute_report_with_resource_findings(self):
        """Test compute optimization report with sizing recommendations."""
        valid_report = {
            "summary": {
                "overview": "Cluster analysis shows over-provisioning with low CPU utilization",
                "current_state": {
                    "cloud_provider": "AWS",
                    "runtime_version": "13.3 LTS",
                    "resource_type": "Cluster",
                    "resource_size": "8 workers, Standard_DS3_v2",
                    "key_symptoms": [
                        "High cost",
                        "Low CPU utilization (15%)",
                        "Underutilized memory",
                    ],
                },
            },
            "analysis": {
                "findings": [
                    {
                        "id": "compute_finding_001",
                        "category": "CLUSTER",
                        "title": "Over-provisioned cluster with low utilization",
                        "recommendation": "Reduce cluster size from 8 to 4 workers for 40% cost savings",
                        "fixes": [
                            {
                                "type": "CLUSTER_TUNING",
                                "snippet": '{\n  "num_workers": 4,\n  "autoscale": {"min_workers": 2, "max_workers": 6}\n}',
                                "notes": "Average CPU is 15%, peak is 45%. 4 workers handles peak with headroom.",
                            }
                        ],
                        "proofs": {
                            "evidence": [
                                "Average CPU utilization is 15% over 7 days",
                                "Peak CPU utilization is 45%",
                                "Current cost is $8/hour, projected cost is $4.80/hour",
                            ],
                            "code_line_refs": [],
                            "references": [
                                {
                                    "title": "Cluster Sizing Best Practices",
                                    "url": "https://docs.databricks.com/clusters/sizing.html",
                                    "cloud": "aws",
                                }
                            ],
                        },
                        "impact_estimate": {
                            "query_time_pct": 0.0,
                            "data_read_pct": 0.0,
                            "shuffle_pct": 0.0,
                            "cost_pct": -40.0,
                            "confidence": "high",
                        },
                        "effort": {"level": "low", "estimate_hours": 0.5},
                        "risks": [
                            "Test during off-peak hours",
                            "Monitor for performance degradation",
                        ],
                        "rank": 1,
                    }
                ],
            },
            "next_steps": [
                {
                    "id": "step_1",
                    "number": 1,
                    "title": "Would you like me to analyze cost...",
                    "description": "Would you like me to analyze cost trends for other clusters or warehouses?",
                    "action_type": "continue",
                }
            ],
        }

        # Validate
        report = OptimizerAdvisorReport.model_validate(valid_report)

        # Assertions
        assert report.analysis.findings[0].category == "CLUSTER"
        assert report.analysis.findings[0].fixes[0].type == "CLUSTER_TUNING"
        assert report.analysis.findings[0].impact_estimate.cost_pct == -40.0


class TestDiagnosticOptimizationSchema:
    """Test diagnostic report schema."""

    def test_diagnostic_report_with_root_cause(self):
        """Test diagnostic report with root cause analysis."""
        valid_report = {
            "summary": {
                "overview": "Root cause identified: OOM error due to large broadcast in job task 5",
                "current_state": {
                    "cloud_provider": "AWS",
                    "runtime_version": "13.3 LTS",
                    "key_symptoms": [
                        "OOM errors",
                        "Job failures",
                        "Task 5 failing consistently",
                    ],
                },
            },
            "analysis": {
                "findings": [
                    {
                        "id": "diag_finding_001",
                        "category": "CODE",
                        "title": "OOM error caused by large broadcast in job task 5",
                        "recommendation": "Replace broadcast hint with regular join or filter broadcast table",
                        "fixes": [
                            {
                                "type": "CODE_REWRITE",
                                "snippet": "# Remove broadcast hint and let Spark choose join strategy\nlarge_df.join(small_df, 'id')  # Was: broadcast(small_df)",
                                "notes": "Broadcast table is 5GB but driver has 2GB memory. Let Spark use sort-merge join.",
                            }
                        ],
                        "proofs": {
                            "evidence": [
                                "Error: java.lang.OutOfMemoryError: Not enough memory to build broadcast",
                                "Spark logs show broadcast size is 5GB",
                                "Driver configured with 2GB memory",
                            ],
                            "code_line_refs": [
                                {"object": "notebook_cell_5", "line": 23}
                            ],
                            "references": [
                                {
                                    "title": "Troubleshooting OOM Errors",
                                    "url": "https://docs.databricks.com/kb/clusters/out-of-memory.html",
                                    "cloud": "aws",
                                }
                            ],
                        },
                        "impact_estimate": {
                            "query_time_pct": 0.0,
                            "data_read_pct": 0.0,
                            "shuffle_pct": 20.0,
                            "cost_pct": 0.0,
                            "confidence": "high",
                        },
                        "effort": {"level": "low", "estimate_hours": 0.5},
                        "risks": ["Test thoroughly to ensure results match"],
                        "rank": 1,
                    }
                ],
            },
            "next_steps": [
                {
                    "id": "step_1",
                    "number": 1,
                    "title": "Would you like me to check for...",
                    "description": "Would you like me to check for similar patterns in other jobs or notebooks?",
                    "action_type": "continue",
                }
            ],
        }

        # Validate
        report = OptimizerAdvisorReport.model_validate(valid_report)

        # Assertions
        assert report.analysis.findings[0].category == "CODE"
        assert "OOM" in report.summary.current_state.key_symptoms[0]


class TestSchemaValidation:
    """Test schema validation and edge cases."""

    def test_finding_category_validation(self):
        """Test that invalid categories are rejected."""
        from pydantic import ValidationError

        invalid_finding = {
            "id": "test_001",
            "category": "INVALID_CATEGORY",  # Invalid
            "title": "Test",
            "recommendation": "Test",
            "fixes": [],
            "proofs": {"evidence": [], "code_line_refs": [], "references": []},
            "impact_estimate": {
                "query_time_pct": 0.0,
                "data_read_pct": 0.0,
                "shuffle_pct": 0.0,
                "cost_pct": 0.0,
                "confidence": "medium",
            },
            "effort": {"level": "low", "estimate_hours": 1.0},
            "risks": [],
            "rank": 1,
        }

        with pytest.raises(ValidationError):
            Finding.model_validate(invalid_finding)

    def test_next_steps_count_validation(self):
        """Test that next_steps must be 1-4 items."""
        from pydantic import ValidationError

        # Test 0 items (should fail)
        with pytest.raises(ValidationError):
            OptimizerAdvisorReport.model_validate(
                {
                    "summary": {
                        "overview": "Test",
                        "current_state": {
                            "cloud_provider": "AWS",
                            "key_symptoms": [],
                        },
                    },
                    "analysis": {"findings": []},
                    "next_steps": [],  # Empty list (invalid)
                }
            )

        # Test 5 items (should fail)
        with pytest.raises(ValidationError):
            OptimizerAdvisorReport.model_validate(
                {
                    "summary": {
                        "overview": "Test",
                        "current_state": {
                            "cloud_provider": "AWS",
                            "key_symptoms": [],
                        },
                    },
                    "analysis": {"findings": []},
                    "next_steps": [
                        {
                            "rank": i,
                            "action": f"Action {i}",
                        }
                        for i in range(1, 5)
                    ],  # 4 items (invalid, max is 3)
                }
            )

    def test_query_rewrite_optional(self):
        """Test that query_rewrite is optional in analysis."""
        valid_report = {
            "summary": {
                "overview": "Test",
                "current_state": {"cloud_provider": "AWS", "key_symptoms": []},
            },
            "analysis": {
                "findings": [
                    {
                        "id": "test_001",
                        "category": "JOB_CONFIG",
                        "title": "Test",
                        "recommendation": "Test",
                        "fixes": [],
                        "proofs": {
                            "evidence": [],
                            "code_line_refs": [],
                            "references": [],
                        },
                        "impact_estimate": {
                            "query_time_pct": 0.0,
                            "data_read_pct": 0.0,
                            "shuffle_pct": 0.0,
                            "cost_pct": 0.0,
                            "confidence": "medium",
                        },
                        "effort": {"level": "low", "estimate_hours": 1.0},
                        "risks": [],
                        "rank": 1,
                    }
                ]
                # No query_rewrite (should be valid)
            },
            "next_steps": [
                {
                    "id": "step_1",
                    "number": 1,
                    "title": "Would you like me to investigate further?",
                    "description": "Would you like me to investigate further?",
                    "action_type": "continue",
                }
            ],
        }

        # Should validate successfully
        report = OptimizerAdvisorReport.model_validate(valid_report)
        assert report.analysis.query_rewrite is None
