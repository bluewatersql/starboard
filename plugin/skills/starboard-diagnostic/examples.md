# Starboard Diagnostic — Examples

Level-3 sample invocations and expected JSON. Loaded on demand. All commands go
through `${CLAUDE_SKILL_DIR}/scripts/run.sh` (Tier 1) and print the stable
envelope to stdout.

## 1. Triage an exit code

```bash
${CLAUDE_SKILL_DIR}/scripts/run.sh triage-exit --exit-code 137 --context "Container was OOMKilled"
```

```json
{
  "ok": true,
  "domain": "diagnostic",
  "command": "triage-exit",
  "data": {
    "exit_code": 137,
    "is_signal": true,
    "signal_number": 9,
    "primary_hypothesis": {
      "hypothesis_type": "oom",
      "confidence": 0.85,
      "supporting_evidence": ["Container was killed by OOM killer"],
      "contradicting_evidence": [],
      "next_steps": [
        "Check cluster event logs for OOMKilled events",
        "Review GC logs for memory pressure before termination"
      ]
    },
    "alternative_hypotheses": [
      {"hypothesis_type": "container_limit", "confidence": 0.275}
    ],
    "raw_interpretation": "Process terminated by SIGKILL (signal 9). Exit code 137 = 128 + 9."
  },
  "error": null,
  "meta": {"format": "json", "contract_version": "1.0"}
}
```

A SIGTERM exit (`--exit-code 143`) instead yields `primary_hypothesis.hypothesis_type == "cancellation"`.

## 2. Extract evidence from an error log

```bash
${CLAUDE_SKILL_DIR}/scripts/run.sh extract-evidence --text /path/to/error.log
```

```json
{
  "ok": true,
  "domain": "diagnostic",
  "command": "extract-evidence",
  "data": {
    "windows": [
      {
        "window_id": "ev_8c8752e4",
        "evidence_type": "oom",
        "line_start": 1,
        "line_end": 4,
        "content": "java.lang.OutOfMemoryError: Java heap space\n\tat org.apache.spark.Foo(Foo.scala:1)",
        "confidence": 0.95,
        "pattern_match": "OutOfMemoryError"
      }
    ],
    "summary": "Extracted 2 evidence window(s): oom, fatal exception",
    "has_fatal": true,
    "window_count": 2
  },
  "error": null,
  "meta": {"format": "json", "contract_version": "1.0"}
}
```

Cite windows by `window_id` (e.g. `ev_8c8752e4`) in your report.

## 3. End-to-end root-cause analysis

```bash
${CLAUDE_SKILL_DIR}/scripts/run.sh rca --text /path/to/error.log --exit-code 137
```

`data` merges the three stages:

```json
{
  "ok": true,
  "domain": "diagnostic",
  "command": "rca",
  "data": {
    "triage":   { "primary_hypothesis": {"hypothesis_type": "oom", "confidence": 0.85}, "...": "..." },
    "evidence": { "window_count": 2, "has_fatal": true, "...": "..." },
    "synthesis": {
      "primary_symptom": "unknown",
      "root_causes": ["Root cause undetermined - requires further investigation"],
      "confidence": 0.95,
      "evidence_chain": ["Evidence from artifact: ev_8c8752e4"],
      "recommended_actions": ["Review logs and error details for more specific guidance"]
    }
  },
  "error": null,
  "meta": {"format": "json", "contract_version": "1.0"}
}
```

Omit `--exit-code` for a text-only RCA; then `data.triage` is `null`.

## 4. Argument errors

A missing `--text` file or bad flags exit with code `4` and an envelope where
`ok` is `false`:

```bash
${CLAUDE_SKILL_DIR}/scripts/run.sh extract-evidence --text /no/such/file.log
# -> exit 4, {"ok": false, "error": "--text file not found: /no/such/file.log", ...}
```
