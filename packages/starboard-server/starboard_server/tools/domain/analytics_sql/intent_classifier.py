# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Analytics SQL - Intent Classification.

Classifies user intent from natural language queries using pattern matching
and keyword analysis. This is a lightweight, rule-based classifier that doesn't
require LLM calls for basic intent detection.

For complex queries or low-confidence classifications, the caller can optionally
use an LLM-based classifier.
"""

import re
from re import Pattern
from typing import Any

from starboard_server.tools.domain.analytics_sql.models import (
    AggregationType,
    QueryDomain,
    QueryIntent,
    QueryIntentContext,
    TimeGranularity,
)


class IntentClassifier:
    """Rule-based intent classifier for analytics queries.

    This classifier uses pattern matching and keyword analysis to extract:
    - Primary intent (cost, performance, trends, etc.)
    - Target domain (billing, compute, query, jobs)
    - Aggregation type (sum, top_n, avg, etc.)
    - Time range and granularity
    - Dimensions and metrics
    - Filters

    For queries that don't match patterns well, it returns UNKNOWN intent
    with low confidence, allowing the caller to fall back to LLM classification.
    """

    # Intent patterns
    COST_PATTERNS: list[Pattern] = [
        re.compile(r"\b(costs?|spend|spending|expense|price|bill|billing)\b", re.I),
        re.compile(r"\btotal.*(costs?|spend|spending|expense)\b", re.I),
        re.compile(r"\bDBU.*(cost|usage|consumption)\b", re.I),
        re.compile(r"\bhow much.*paid\b", re.I),
        re.compile(r"\bshow.*(costs?|spend|expense|spending)\b", re.I),
        re.compile(r"\b(warehouse|cluster|job).*(costs?|spend|expense)\b", re.I),
    ]

    PERFORMANCE_PATTERNS: list[Pattern] = [
        re.compile(
            r"\b(slow|slowest|fast|fastest|performance|duration|latency)\b", re.I
        ),
        re.compile(r"\bquery.*(time|speed|duration)\b", re.I),
    ]

    TREND_PATTERNS: list[Pattern] = [
        re.compile(
            r"\b(trend|trends|over time|growth|change|increase|decrease)\b", re.I
        ),
        re.compile(r"\b(daily|weekly|monthly).*(cost|usage)\b", re.I),
        re.compile(r"\bover.*(day|week|month)\b", re.I),
        re.compile(r"\b(cost|usage).*(trend|trends)\b", re.I),
    ]

    COMPARISON_PATTERNS: list[Pattern] = [
        re.compile(r"\b(compare|comparison|vs|versus|between)\b", re.I),
    ]

    TROUBLESHOOTING_PATTERNS: list[Pattern] = [
        re.compile(r"\b(fail|failed|failure|error|issue|problem)\b", re.I),
    ]

    # Domain patterns
    BILLING_PATTERNS: list[Pattern] = [
        re.compile(r"\b(costs?|billing|usage|DBU|spend|price)\b", re.I),
    ]

    WAREHOUSE_PATTERNS: list[Pattern] = [
        re.compile(r"\b(warehouse|SQL.?warehouse)\b", re.I),
    ]

    CLUSTER_PATTERNS: list[Pattern] = [
        re.compile(r"\b(cluster|interactive)\b", re.I),
    ]

    QUERY_PATTERNS: list[Pattern] = [
        re.compile(r"\b(query|queries|SQL|statement)\b", re.I),
    ]

    JOB_PATTERNS: list[Pattern] = [
        re.compile(r"\b(job|jobs|workflow|pipeline)\b", re.I),
    ]

    # Time patterns
    TIME_RANGE_PATTERNS: dict[Pattern, Any] = {
        re.compile(r"\b(\d+)\s*(day|days)\b", re.I): lambda m: int(m.group(1)),
        re.compile(r"\b(\d+)\s*(week|weeks)\b", re.I): lambda m: int(m.group(1)) * 7,
        re.compile(r"\b(\d+)\s*(month|months)\b", re.I): lambda m: int(m.group(1)) * 30,
        re.compile(r"\blast\s*week\b", re.I): lambda _: 7,
        re.compile(r"\blast\s*month\b", re.I): lambda _: 30,
        re.compile(r"\blast\s*quarter\b", re.I): lambda _: 90,
        re.compile(r"\blast\s*year\b", re.I): lambda _: 365,
    }

    TIME_GRANULARITY_PATTERNS: dict[Pattern, TimeGranularity] = {
        re.compile(r"\bby\s*hour\b", re.I): TimeGranularity.HOUR,
        re.compile(r"\bhourly\b", re.I): TimeGranularity.HOUR,
        re.compile(r"\bby\s*day\b", re.I): TimeGranularity.DAY,
        re.compile(r"\bdaily\b", re.I): TimeGranularity.DAY,
        re.compile(r"\bby\s*week\b", re.I): TimeGranularity.WEEK,
        re.compile(r"\bweekly\b", re.I): TimeGranularity.WEEK,
        re.compile(r"\bby\s*month\b", re.I): TimeGranularity.MONTH,
        re.compile(r"\bmonthly\b", re.I): TimeGranularity.MONTH,
    }

    # Aggregation patterns
    TOP_N_PATTERN = re.compile(r"\btop\s+(\d+)\b", re.I)
    BOTTOM_N_PATTERN = re.compile(r"\b(bottom|worst)\s+(\d+)\b", re.I)
    SLOWEST_PATTERN = re.compile(r"\b(slowest|fastest)\b", re.I)

    def classify(self, query: str) -> QueryIntentContext:
        """Classify user query and extract parameters.

        Args:
            query: Natural language query

        Returns:
            QueryIntentContext with classified intent and extracted parameters

        Raises:
            ValueError: If query is empty
        """
        if not query or not query.strip():
            raise ValueError("Query cannot be empty")

        query = query.strip()

        # Extract components
        intent = self._classify_intent(query)
        domain = self._classify_domain(query)
        rag_resource_domains = self._classify_rag_domains(query, intent, domain)
        aggregation, limit = self._extract_aggregation(query)
        time_range_days = self._extract_time_range(query)
        time_granularity = self._extract_time_granularity(query)
        metrics = self._extract_metrics(query, intent)
        dimensions = self._extract_dimensions(query, domain)
        filters = self._extract_filters(query)

        # Calculate confidence
        confidence = self._calculate_confidence(intent, domain, query)

        # Generate reasoning
        reasoning = self._generate_reasoning(
            query, intent, domain, aggregation, time_range_days
        )

        return QueryIntentContext(
            intent=intent,
            domain=domain,
            metrics=metrics,
            dimensions=dimensions,
            rag_resource_domains=rag_resource_domains,
            aggregation=aggregation,
            time_range_days=time_range_days,
            time_granularity=time_granularity,
            filters=filters,
            limit=limit,
            confidence=confidence,
            reasoning=reasoning,
        )

    def _classify_intent(self, query: str) -> QueryIntent:
        """Classify primary intent from query."""
        # Check for trend patterns FIRST (more specific than cost)
        if self._matches_patterns(query, self.TREND_PATTERNS):
            return QueryIntent.TREND_ANALYSIS

        # Check for comparison patterns SECOND (also more specific)
        if self._matches_patterns(query, self.COMPARISON_PATTERNS):
            return QueryIntent.COMPARISON

        # Then check other intents
        if self._matches_patterns(query, self.COST_PATTERNS):
            return QueryIntent.COST_ANALYSIS
        if self._matches_patterns(query, self.PERFORMANCE_PATTERNS):
            return QueryIntent.PERFORMANCE_ANALYSIS
        if self._matches_patterns(query, self.TROUBLESHOOTING_PATTERNS):
            return QueryIntent.TROUBLESHOOTING

        # Default to UNKNOWN if no clear match
        return QueryIntent.UNKNOWN

    def _classify_domain(self, query: str) -> QueryDomain:
        """Classify target domain from query."""
        matches = []

        # Check billing FIRST (cost queries are always billing even if they mention resources)
        if self._matches_patterns(query, self.BILLING_PATTERNS):
            billing_match = True
        else:
            billing_match = False

        # Then check other domains
        if self._matches_patterns(query, self.WAREHOUSE_PATTERNS):
            matches.append(QueryDomain.COMPUTE)
        if self._matches_patterns(query, self.CLUSTER_PATTERNS):
            matches.append(QueryDomain.COMPUTE)
        if self._matches_patterns(query, self.QUERY_PATTERNS):
            matches.append(QueryDomain.QUERY)
        if self._matches_patterns(query, self.JOB_PATTERNS):
            matches.append(QueryDomain.LAKEFLOW)

        if billing_match and matches:
            return QueryDomain.MIXED
        if billing_match:
            return QueryDomain.BILLING

        if len(matches) == 1:
            return matches[0]

        if len(matches) > 1:
            return QueryDomain.MIXED

        return QueryDomain.UNKNOWN

    def _classify_rag_domains(
        self, query: str, intent: QueryIntent, domain: QueryDomain
    ) -> list[str]:
        """Classify RAG resource domains (Databricks resource-model aligned)."""
        domains: list[str] = []

        # Warehouse + cost → billing + compute
        if intent == QueryIntent.COST_ANALYSIS and re.search(
            r"\bwarehouse\b", query, re.I
        ):
            domains.extend(["finops_billing", "compute_warehouses"])
        elif intent == QueryIntent.COST_ANALYSIS:
            domains.append("finops_billing")
        elif domain == QueryDomain.COMPUTE:
            domains.append("compute_warehouses")

        # Deduplicate while preserving order
        seen = set()
        deduped = []
        for d in domains:
            if d not in seen:
                deduped.append(d)
                seen.add(d)
        return deduped

    def _extract_aggregation(self, query: str) -> tuple[AggregationType, int | None]:
        """Extract aggregation type and limit."""
        # Check for TOP N
        match = self.TOP_N_PATTERN.search(query)
        if match:
            return AggregationType.TOP_N, int(match.group(1))

        # Check for BOTTOM N
        match = self.BOTTOM_N_PATTERN.search(query)
        if match:
            return AggregationType.BOTTOM_N, int(match.group(2))

        # Check for slowest/fastest (implies TOP_N or MAX)
        if self.SLOWEST_PATTERN.search(query):
            return AggregationType.MAX, None

        # Check for aggregation keywords
        if re.search(r"\b(sum|total|aggregate)\b", query, re.I):
            return AggregationType.SUM, None
        if re.search(r"\b(avg|average|mean)\b", query, re.I):
            return AggregationType.AVG, None
        if re.search(r"\b(count|number of)\b", query, re.I):
            return AggregationType.COUNT, None
        if re.search(r"\b(max|maximum|highest)\b", query, re.I):
            return AggregationType.MAX, None
        if re.search(r"\b(min|minimum|lowest)\b", query, re.I):
            return AggregationType.MIN, None

        # Default to SUM for cost queries
        if re.search(r"\b(cost|spend|expense)\b", query, re.I):
            return AggregationType.SUM, None

        return AggregationType.NONE, None

    def _extract_time_range(self, query: str) -> int | None:
        """Extract time range in days."""
        for pattern, extractor in self.TIME_RANGE_PATTERNS.items():
            match = pattern.search(query)
            if match:
                return extractor(match)
        return None

    def _extract_time_granularity(self, query: str) -> TimeGranularity:
        """Extract time granularity."""
        for pattern, granularity in self.TIME_GRANULARITY_PATTERNS.items():
            if pattern.search(query):
                return granularity
        return TimeGranularity.NONE

    def _extract_metrics(self, query: str, intent: QueryIntent) -> list[str]:
        """Extract requested metrics."""
        metrics = []

        # Cost-related metrics
        if re.search(r"\bcost\b", query, re.I):
            metrics.append("total_cost_usd")
        if re.search(r"\b(DBU|usage)\b", query, re.I):
            metrics.append("usage_quantity")

        # Performance metrics
        if re.search(r"\bduration\b", query, re.I):
            metrics.append("duration_ms")
        if re.search(r"\brows\b", query, re.I):
            metrics.append("rows_produced")

        # If no specific metrics, infer from intent
        if not metrics:
            if intent == QueryIntent.COST_ANALYSIS:
                metrics.append("total_cost_usd")
            elif intent == QueryIntent.PERFORMANCE_ANALYSIS:
                metrics.append("duration_ms")

        return metrics

    def _extract_dimensions(self, query: str, domain: QueryDomain) -> list[str]:  # noqa: ARG002
        """Extract grouping dimensions."""
        dimensions = []

        # Common dimensions
        if re.search(r"\bwarehouse", query, re.I):
            dimensions.extend(["warehouse_id", "warehouse_name"])
        if re.search(r"\bcluster", query, re.I):
            dimensions.extend(["cluster_id", "cluster_name"])
        if re.search(r"\bjob", query, re.I):
            dimensions.extend(["job_id", "job_name"])
        if re.search(r"\bworkspace", query, re.I):
            dimensions.extend(["workspace_id", "workspace_name"])
        if re.search(r"\buser", query, re.I):
            dimensions.append("user_name")

        return dimensions

    def _extract_filters(self, query: str) -> dict[str, str | list[str]]:
        """Extract filters from query."""
        filters: dict[str, str | list[str]] = {}

        # Serverless filter
        if re.search(r"\bserverless\b", query, re.I):
            filters["compute_type"] = "SERVERLESS"

        # Cluster type filter
        if re.search(r"\ball.?purpose\b", query, re.I):
            filters["compute_type"] = "ALL_PURPOSE"

        return filters

    def _calculate_confidence(
        self, intent: QueryIntent, domain: QueryDomain, query: str
    ) -> float:
        """Calculate confidence score for classification."""
        confidence = 0.5  # Base confidence

        # Increase confidence for clear intent
        if intent != QueryIntent.UNKNOWN:
            confidence += 0.2

        # Increase confidence for clear domain
        if domain not in [QueryDomain.UNKNOWN, QueryDomain.MIXED]:
            confidence += 0.2

        # Increase confidence for specific keywords
        if re.search(r"\b(top|bottom|\d+)\b", query, re.I):
            confidence += 0.1

        return min(confidence, 1.0)

    def _generate_reasoning(
        self,
        query: str,
        intent: QueryIntent,
        domain: QueryDomain,
        aggregation: AggregationType,
        time_range_days: int | None,
    ) -> str:
        """Generate reasoning for classification."""
        parts = [f"User query: '{query}'"]
        parts.append(f"Classified as {intent.value} intent")
        parts.append(f"Domain: {domain.value}")
        parts.append(f"Aggregation: {aggregation.value}")

        if time_range_days:
            parts.append(f"Time range: {time_range_days} days")

        return ". ".join(parts)

    def _matches_patterns(self, query: str, patterns: list[Pattern]) -> bool:
        """Check if query matches any of the given patterns."""
        return any(pattern.search(query) for pattern in patterns)
