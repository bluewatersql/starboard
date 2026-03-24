# Cluster Agent Test Prompts & Expected Behaviors

This document provides test prompts and expected behaviors for validating the Cluster Agent implementation.

---

## 1. Basic Cluster Analysis

### 1.1 Single Cluster Configuration Analysis

**Prompt:**
```
Analyze the configuration of cluster 0123-456789-abcdef
```

**Expected Behavior:**
1. Agent recognizes cluster_id from prompt
2. Calls `get_cluster_config` with cluster_id
3. Calls `get_cluster_metrics` for utilization data
4. Generates report with:
   - Configuration summary (node type, DBR version, autoscaling settings)
   - Resource utilization analysis
   - Optimization recommendations
5. Completes with `report_type: "cluster"`

**Tool Call Sequence:**
```
1. get_cluster_config(cluster_id="0123-456789-abcdef")
2. get_cluster_metrics(cluster_id="0123-456789-abcdef")
3. complete(report_type="cluster", ...)
```

---

### 1.2 Cluster Without ID (Clarification Flow)

**Prompt:**
```
Why is my cluster slow?
```

**Expected Behavior:**
1. Agent detects missing cluster_id
2. Calls `request_user_input` to ask for cluster identifier
3. Waits for user response with cluster_id
4. Proceeds with analysis once ID is provided

**Tool Call Sequence:**
```
1. request_user_input(question="Could you provide the cluster ID...")
   → User provides: "0123-456789-abcdef"
2. get_cluster_config(cluster_id="0123-456789-abcdef")
3. get_cluster_metrics(cluster_id="0123-456789-abcdef")
4. complete(...)
```

---

### 1.3 Cluster Health Check

**Prompt:**
```
Check the health of cluster 0123-456789-abcdef
```

**Expected Behavior:**
1. Agent fetches cluster config and metrics
2. May fetch cluster events for scaling history
3. Generates health report with:
   - Overall health score (0-100)
   - Metric breakdown (CPU, memory, disk, network)
   - Risk factors identified
   - Remediation recommendations

**Key Assertions:**
- Health score reflects actual utilization patterns
- Risk factors are specific and actionable
- Report type is "cluster"

---

## 2. Advanced Cluster Scenarios

### 2.1 Autoscaling Analysis

**Prompt:**
```
Is autoscaling configured correctly on cluster 0123-456789-abcdef?
```

**Expected Behavior:**
1. Fetches cluster configuration
2. Fetches cluster events to see scaling history
3. Analyzes:
   - Min/max worker counts
   - Scaling frequency and patterns
   - Under/over-provisioning indicators
4. Provides specific autoscaling recommendations

**Tool Call Sequence:**
```
1. get_cluster_config(cluster_id="0123-456789-abcdef")
2. get_cluster_events(cluster_id="0123-456789-abcdef")
3. complete(...)
```

---

### 2.2 Spark Performance Analysis

**Prompt:**
```
Analyze Spark performance on cluster 0123-456789-abcdef for job run 12345
```

**Expected Behavior:**
1. Fetches cluster configuration
2. Fetches Spark logs for the specific run
3. Identifies:
   - Shuffle spill issues
   - Memory pressure
   - Executor failures
   - Stage bottlenecks
4. Provides Spark-specific tuning recommendations

**Tool Call Sequence:**
```
1. get_cluster_config(cluster_id="0123-456789-abcdef")
2. get_spark_logs(cluster_id="0123-456789-abcdef", run_id="12345")
3. complete(...)
```

---

### 2.3 Cost Optimization

**Prompt:**
```
How can I reduce costs for cluster 0123-456789-abcdef?
```

**Expected Behavior:**
1. Fetches configuration (instance types, node counts)
2. Fetches metrics (actual utilization)
3. Analyzes cost drivers:
   - Over-provisioned resources
   - Spot instance eligibility
   - Instance pool opportunities
   - Autoscaling adjustments
4. Provides cost-focused recommendations with estimated savings

**Key Assertions:**
- Recommendations include cost impact estimates
- Considers spot vs. on-demand tradeoffs
- Suggests instance pool if applicable

---

## 3. Handoff Scenarios

### 3.1 Handoff FROM Job Agent

**Context:** User started with job analysis, Job Agent identified cluster issues

**Incoming Handoff Context:**
```json
{
  "source_agent": "job",
  "cluster_id": "0123-456789-abcdef",
  "job_id": "67890",
  "context": "Job failed due to out-of-memory errors on the cluster"
}
```

**Expected Behavior:**
1. Agent recognizes cluster_id from handoff context
2. Immediately calls cluster tools (no clarification needed)
3. Focuses analysis on memory-related issues
4. References the job context in findings

**Key Assertions:**
- Does NOT ask for cluster_id (already provided)
- Prioritizes memory analysis given handoff context
- Maintains continuity with job agent's findings

---

### 3.2 Handoff TO Job Agent

**Prompt:**
```
Analyze cluster 0123-456789-abcdef
```

*After analysis, cluster is healthy but user asks:*
```
What jobs run on this cluster?
```

**Expected Behavior:**
1. Completes cluster analysis
2. In next_steps, includes option to route to Job Agent
3. If user selects job analysis:
   - `action_type: "route"`
   - `target_agent: "job"`
   - Passes cluster_id in context

**Next Steps Example:**
```json
{
  "next_steps": [
    {
      "title": "Analyze jobs on this cluster",
      "description": "View job performance and failures",
      "action_type": "route",
      "target_agent": "job"
    }
  ]
}
```

---

### 3.3 Handoff TO Warehouse Agent

**Prompt:**
```
My warehouse is slow, here's the warehouse_id: abc123
```

**Expected Behavior:**
1. Intent Router routes to Warehouse Agent (NOT Cluster Agent)
2. If mistakenly routed to Cluster Agent:
   - Agent should recognize warehouse_id
   - Suggest handoff to Warehouse Agent
   - NOT attempt warehouse analysis with cluster tools

**Key Assertions:**
- warehouse_id routes to warehouse domain
- Cluster Agent does NOT have warehouse tools
- Clear separation between cluster and warehouse domains

---

## 4. Fleet Analysis

### 4.1 Multiple Cluster Analysis

**Prompt:**
```
Analyze these clusters: 0123-456789-abcdef, 0123-456789-ghijkl, 0123-456789-mnopqr
```

**Expected Behavior:**
1. Agent processes clusters in bounded parallel batches
2. Uses semaphore to limit concurrent API calls (max ~10)
3. Aggregates findings across clusters
4. Generates fleet-level report with:
   - Per-cluster summaries
   - Common patterns identified
   - Fleet-wide recommendations

**Concurrency Requirements:**
- Maximum 10 concurrent API calls
- Graceful handling of individual cluster failures
- Progress indication if available

---

### 4.2 Fleet Health Overview

**Prompt:**
```
Give me a health overview of all my clusters
```

**Expected Behavior:**
1. May need to enumerate clusters first
2. Analyzes each cluster with bounded concurrency
3. Generates portfolio-style report:
   - Healthy vs. unhealthy cluster counts
   - Top risk factors across fleet
   - Priority remediation items

**Key Assertions:**
- Does not overwhelm APIs with parallel requests
- Provides actionable fleet-level insights
- Handles partial failures gracefully

---

## 5. Error Handling

### 5.1 Invalid Cluster ID

**Prompt:**
```
Analyze cluster invalid-cluster-id
```

**Expected Behavior:**
1. Calls get_cluster_config
2. Receives error (cluster not found)
3. Informs user cluster doesn't exist
4. Offers to help with valid cluster ID

**Key Assertions:**
- Does NOT fabricate data
- Clear error message to user
- Offers recovery path

---

### 5.2 API Rate Limiting

**Prompt:**
```
Analyze 50 clusters in my workspace
```

**Expected Behavior:**
1. Implements bounded concurrency (semaphore)
2. Respects rate limits with backoff
3. Completes analysis even if some calls are delayed
4. Reports any failures due to rate limiting

**Key Assertions:**
- Semaphore limits concurrent calls to ~10
- Exponential backoff on 429 errors
- Partial results returned on timeout

---

### 5.3 Tool Failure Recovery

**Prompt:**
```
Analyze cluster 0123-456789-abcdef
```

*Scenario: get_cluster_metrics fails but get_cluster_config succeeds*

**Expected Behavior:**
1. Reports what was successfully retrieved
2. Notes which data couldn't be fetched
3. Provides partial recommendations based on available data
4. Suggests retry or alternative approaches

**Key Assertions:**
- Does NOT fail completely on partial tool failures
- Clearly indicates data gaps
- Provides value with available data

---

## 6. Edge Cases

### 6.1 Terminated/Deleted Cluster

**Prompt:**
```
Why did cluster 0123-456789-abcdef fail yesterday?
```

**Expected Behavior:**
1. Attempts to fetch cluster info
2. Discovers cluster is terminated/deleted
3. May still have historical events if available
4. Provides what information is accessible
5. Explains limitations of historical analysis

---

### 6.2 Serverless Context (No Cluster)

**Prompt:**
```
Optimize my serverless compute
```

**Expected Behavior:**
1. Recognizes serverless context
2. Explains that Cluster Agent handles job clusters
3. Suggests routing to appropriate agent (Warehouse or Analytics)
4. Does NOT attempt cluster analysis on serverless

**Key Assertions:**
- Correct identification of serverless
- Appropriate handoff suggestion
- No false cluster analysis

---

### 6.3 Mixed Cluster and Warehouse Request

**Prompt:**
```
Compare the performance of cluster 0123-456789-abcdef and warehouse abc123
```

**Expected Behavior:**
1. Cluster Agent handles cluster analysis
2. For warehouse, either:
   a. Completes cluster portion, suggests warehouse handoff
   b. Acknowledges can only analyze cluster
3. Does NOT fabricate warehouse data

**Key Assertions:**
- Clear scope of Cluster Agent capabilities
- Proper handoff for warehouse analysis
- No cross-domain tool misuse

---

## 7. Report Format Validation

### 7.1 Cluster Report Structure

**Expected Report Fields:**
```json
{
  "report_type": "cluster",
  "summary": {
    "overview": "string",
    "current_state": {
      "key_symptoms": ["list", "of", "observations"]
    }
  },
  "health_metrics": {
    "overall_score": 85,
    "metric_scores": {
      "cpu_utilization": 90,
      "memory_utilization": 75,
      "disk_io": 85,
      "network_io": 95
    },
    "risk_factors": ["list of identified risks"]
  },
  "analysis": {
    "findings": [
      {
        "title": "Finding title",
        "category": "category",
        "recommendation": "Action to take"
      }
    ]
  },
  "next_steps": [
    {
      "title": "Step title",
      "description": "What this does",
      "action_type": "continue|route|complete",
      "target_agent": "optional agent name"
    }
  ]
}
```

---

### 7.2 Frontend Rendering Check

**Test Steps:**
1. Trigger cluster analysis
2. Verify report renders in frontend
3. Check `ReportBubble.tsx` routes to cluster report component
4. Verify health scores display correctly
5. Confirm next_steps are clickable/actionable

---

## 8. Integration Test Scenarios

### 8.1 Full Conversation Flow

```
User: "I need help optimizing my Databricks costs"
→ Router: Routes to Analytics or clarifies
→ User: "Specifically cluster 0123-456789-abcdef"
→ Router: Routes to Cluster Agent
→ Cluster Agent: Analyzes, provides report
→ User: "Apply the autoscaling changes"
→ Cluster Agent: Provides guidance (or hands off to implementation)
```

### 8.2 Multi-Agent Workflow

```
User: "Job 12345 is failing"
→ Router: Routes to Job Agent
→ Job Agent: Identifies OOM on cluster 0123-456789-abcdef
→ Job Agent: Hands off to Cluster Agent
→ Cluster Agent: Analyzes cluster, recommends sizing
→ Cluster Agent: Offers to hand back to Job Agent for validation
```

---

## 9. Performance Benchmarks

| Scenario | Expected Latency | Tool Calls |
|----------|------------------|------------|
| Single cluster basic | < 5s | 2-3 |
| Single cluster deep | < 10s | 4-5 |
| Fleet (10 clusters) | < 30s | 20-30 |
| Fleet (50 clusters) | < 60s | 100-150 |

---

## 10. Regression Checklist

- [ ] Cluster analysis completes with report_type: "cluster"
- [ ] warehouse_id routes to Warehouse Agent, not Cluster
- [ ] Handoff from Job Agent preserves cluster_id
- [ ] Fleet analysis respects concurrency limits
- [ ] Partial failures don't crash entire analysis
- [ ] Frontend renders cluster reports correctly
- [ ] Next steps include valid agent routing options
- [ ] Health scores calculate correctly from metrics
- [ ] Risk factors are specific and actionable

---

## Appendix: Test Data

### Sample Cluster IDs for Testing
```
# Interactive clusters
0123-456789-test1234
0123-456789-test5678

# Job clusters (ephemeral)
0124-123456-jobclstr

# Pool-backed clusters
0125-654321-poolback
```

### Sample Configurations to Test
- Autoscaling enabled vs. disabled
- Spot instances vs. on-demand
- Single-node vs. multi-node
- Various DBR versions (12.x, 13.x, 14.x, 15.x)
- With and without instance pools

