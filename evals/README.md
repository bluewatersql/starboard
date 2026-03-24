# Evaluation Framework

This directory contains the evaluation framework for agent behavior, prompt quality, and system performance.

## Structure

```
evals/
├── datasets/           # Golden datasets and test cases
│   ├── query_*.json   # Query agent eval cases
│   ├── job_*.json     # Job agent eval cases
│   └── ...
├── runners/           # Evaluation execution
│   ├── batch_runner.py    # Batch evaluation runner
│   └── ci_runner.py       # CI/CD integration runner
├── metrics/           # Evaluation metrics and scoring
│   └── evaluator.py       # Core evaluation logic
└── README.md
```

## Usage

### Running Evaluations

```bash
# Run all evaluations
make test-evals

# Run specific domain evaluation
python -m evals.runners.batch_runner --domain query

# Run CI smoke tests (fast subset)
python -m evals.runners.ci_runner
```

### Dataset Format

Each evaluation dataset is a JSON file with the following structure:

```json
{
  "domain": "query",
  "version": "1.0.0",
  "cases": [
    {
      "id": "query_001",
      "description": "Partition predicate optimization",
      "input": {
        "goal": "Optimize this SQL query",
        "context": {...}
      },
      "expected": {
        "contains": ["partition", "predicate"],
        "category": "QUERY",
        "min_confidence": 0.8
      },
      "tags": ["partition", "optimization"]
    }
  ]
}
```

## Metrics Tracked

| Metric | Description | Target |
|--------|-------------|--------|
| Accuracy | % of cases matching expected output | ≥90% |
| Latency p50 | Median response time | <2s |
| Latency p95 | 95th percentile response time | <5s |
| Token Usage | Average tokens per evaluation | <3000 |
| Cost | Average cost per evaluation | <$0.05 |

## Adding New Evaluations

1. Create a dataset file in `datasets/` following the format above
2. Register the dataset in `runners/batch_runner.py`
3. Add any custom assertions to `metrics/evaluator.py`
4. Run evaluations and verify baseline metrics

## CI Integration

Evaluations run automatically on PRs that modify:
- `packages/starboard-server/starboard_server/prompts/`
- `packages/starboard-server/starboard_server/agents/`
- `packages/starboard-server/starboard_server/tools/`

Merge is blocked if:
- Accuracy drops >5% from baseline
- Latency p95 increases >50%
- Any critical test case fails

## Standards Reference

See `.cursor/04_testing_and_evals.md` for complete evaluation requirements.

