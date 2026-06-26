# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.

"""
Unit tests for ArtifactDetector.

Tests cover all detection rules for artifact type and language classification.
"""

import pytest
from starboard_server.tools.domain.diagnostic import ArtifactType, CodeLanguage
from starboard_server.tools.domain.diagnostic.artifact_detector import ArtifactDetector

# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def detector() -> ArtifactDetector:
    """Create a fresh detector instance."""
    return ArtifactDetector()


# =============================================================================
# STACK TRACE DETECTION
# =============================================================================


class TestStackTraceDetection:
    """Tests for stack trace artifact detection."""

    def test_python_traceback(self, detector: ArtifactDetector) -> None:
        """Python traceback is detected as STACK_TRACE."""
        text = """Traceback (most recent call last):
  File "/app/main.py", line 42, in run
    result = process_data(df)
  File "/app/processor.py", line 15, in process_data
    return df.collect()
RuntimeError: OOM while collecting DataFrame"""

        result = detector.detect(text)

        assert result.artifact_type == ArtifactType.STACK_TRACE
        assert result.confidence >= 0.9
        assert "python_traceback" in result.signals

    def test_java_exception_chain(self, detector: ArtifactDetector) -> None:
        """Java exception with 'Caused by' is detected as STACK_TRACE."""
        text = """org.apache.spark.SparkException: Job aborted due to stage failure
    at org.apache.spark.scheduler.DAGScheduler.failJobAndIndependentStages(DAGScheduler.scala:2454)
    at org.apache.spark.scheduler.DAGScheduler.$anonfun$abortStage$2(DAGScheduler.scala:2403)
Caused by: org.apache.spark.SparkException: Task failed while writing rows
    at org.apache.spark.sql.execution.datasources.FileFormatWriter$.executeTask(FileFormatWriter.scala:296)
Caused by: java.lang.OutOfMemoryError: Java heap space
    at java.util.Arrays.copyOf(Arrays.java:3236)"""

        result = detector.detect(text)

        assert result.artifact_type == ArtifactType.STACK_TRACE
        assert result.confidence >= 0.95
        assert "java_exception" in result.signals or "caused_by_chain" in result.signals

    def test_scala_stack_trace(self, detector: ArtifactDetector) -> None:
        """Scala/Spark stack trace is detected correctly."""
        text = """Exception in thread "main" java.lang.IllegalStateException: Cannot call methods on stopped SparkContext
    at org.apache.spark.SparkContext.assertNotStopped(SparkContext.scala:113)
    at org.apache.spark.SparkContext.parallelize(SparkContext.scala:779)
    at com.example.Main$.main(Main.scala:25)
    at com.example.Main.main(Main.scala)"""

        result = detector.detect(text)

        assert result.artifact_type == ArtifactType.STACK_TRACE
        assert result.confidence >= 0.9


# =============================================================================
# LOG DETECTION
# =============================================================================


class TestLogDetection:
    """Tests for log artifact detection."""

    def test_spark_logs_with_timestamps(self, detector: ArtifactDetector) -> None:
        """Spark application logs are detected as LOGS."""
        text = """2025-12-17 10:15:23 INFO SparkContext: Starting job 1
2025-12-17 10:15:24 INFO DAGScheduler: Submitting 4 missing tasks
2025-12-17 10:15:24 WARN TaskSchedulerImpl: Initial job has not accepted any resources
2025-12-17 10:15:25 INFO TaskSetManager: Starting task 0.0 in stage 0.0
2025-12-17 10:15:26 ERROR Executor: Exception in task 0.0
2025-12-17 10:15:26 INFO TaskSetManager: Lost task 0.0, resubmitting"""

        result = detector.detect(text)

        assert result.artifact_type == ArtifactType.LOGS
        assert result.confidence >= 0.85
        assert "timestamp_density" in result.signals or "log_levels" in result.signals

    def test_databricks_driver_logs(self, detector: ArtifactDetector) -> None:
        """Databricks driver logs with log levels are detected."""
        text = """[INFO] [2025-12-17 08:30:15.123] [main] Starting Databricks job
[WARN] [2025-12-17 08:30:16.456] [executor-1] Memory pressure detected
[ERROR] [2025-12-17 08:30:17.789] [executor-1] OutOfMemoryError occurred
[INFO] [2025-12-17 08:30:18.012] [main] Retrying task 0"""

        result = detector.detect(text)

        assert result.artifact_type == ArtifactType.LOGS
        assert result.confidence >= 0.85

    def test_iso_timestamp_logs(self, detector: ArtifactDetector) -> None:
        """Logs with ISO timestamps are detected."""
        text = """2025-12-17T10:15:23.456Z INFO Starting application
2025-12-17T10:15:24.789Z DEBUG Initializing SparkSession
2025-12-17T10:15:25.012Z WARN Resource contention detected
2025-12-17T10:15:26.345Z ERROR Fatal error occurred"""

        result = detector.detect(text)

        assert result.artifact_type == ArtifactType.LOGS
        assert result.confidence >= 0.85


# =============================================================================
# GC LOG DETECTION
# =============================================================================


class TestGCLogDetection:
    """Tests for GC log artifact detection."""

    def test_gc_logs_standard_format(self, detector: ArtifactDetector) -> None:
        """Standard JVM GC logs are detected as GC_LOGS."""
        text = """[GC (Allocation Failure) [PSYoungGen: 262144K->32768K(305664K)] 524288K->294912K(1005056K), 0.1234567 secs]
[GC (Allocation Failure) [PSYoungGen: 294912K->32768K(305664K)] 557056K->327680K(1005056K), 0.0987654 secs]
[Full GC (Ergonomics) [PSYoungGen: 32768K->0K(305664K)] [ParOldGen: 294912K->262144K(699392K)] 327680K->262144K(1005056K), 1.2345678 secs]
[GC (Allocation Failure) [PSYoungGen: 262144K->32768K(305664K)] 524288K->294912K(1005056K), 0.0567890 secs]"""

        result = detector.detect(text)

        assert result.artifact_type == ArtifactType.GC_LOGS
        assert result.confidence >= 0.9
        assert "gc_pattern" in result.signals

    def test_gc_logs_g1_format(self, detector: ArtifactDetector) -> None:
        """G1 GC logs are detected correctly."""
        text = """[2025-12-17T10:15:23.456+0000][gc,start] GC(42) Pause Young (Normal)
[2025-12-17T10:15:23.789+0000][gc,heap] GC(42) Eden regions: 24->0(25)
[2025-12-17T10:15:23.789+0000][gc,heap] GC(42) Survivor regions: 3->3(4)
[2025-12-17T10:15:23.789+0000][gc] GC(42) Pause Young (Normal) 450M->150M(512M) 333.456ms"""

        result = detector.detect(text)

        assert result.artifact_type == ArtifactType.GC_LOGS
        assert result.confidence >= 0.7  # G1 format is less explicit than standard


# =============================================================================
# EXIT CODE DETECTION
# =============================================================================


class TestExitCodeDetection:
    """Tests for exit code error message detection."""

    def test_exit_code_137(self, detector: ArtifactDetector) -> None:
        """Exit code 137 is detected as ERROR_MESSAGE."""
        text = "Command exited with code 137"

        result = detector.detect(text)

        assert result.artifact_type == ArtifactType.ERROR_MESSAGE
        assert result.confidence >= 0.8
        assert "exit_code" in result.signals

    def test_exit_code_143(self, detector: ArtifactDetector) -> None:
        """Exit code 143 is detected as ERROR_MESSAGE."""
        text = "Process exited with code 143"

        result = detector.detect(text)

        assert result.artifact_type == ArtifactType.ERROR_MESSAGE
        assert "exit_code" in result.signals

    def test_exit_code_in_longer_message(self, detector: ArtifactDetector) -> None:
        """Exit code in context is still detected."""
        text = """Job failed with error:
Reason: Command exited with code 137
The task was terminated unexpectedly."""

        result = detector.detect(text)

        assert result.artifact_type == ArtifactType.ERROR_MESSAGE
        assert "exit_code" in result.signals


# =============================================================================
# SQL CODE DETECTION
# =============================================================================


class TestSQLCodeDetection:
    """Tests for SQL code artifact detection."""

    def test_select_query(self, detector: ArtifactDetector) -> None:
        """SELECT query is detected as CODE with SQL language."""
        text = """SELECT
    customer_id,
    SUM(amount) as total_spend
FROM sales.transactions
WHERE transaction_date >= '2025-01-01'
GROUP BY customer_id
HAVING SUM(amount) > 1000
ORDER BY total_spend DESC
LIMIT 100"""

        result = detector.detect(text)

        assert result.artifact_type == ArtifactType.CODE
        assert result.language == CodeLanguage.SQL
        assert result.confidence >= 0.85

    def test_cte_query(self, detector: ArtifactDetector) -> None:
        """CTE query with WITH clause is detected as SQL."""
        text = """WITH monthly_sales AS (
    SELECT
        DATE_TRUNC('month', sale_date) as month,
        SUM(amount) as revenue
    FROM sales
    GROUP BY 1
)
SELECT * FROM monthly_sales WHERE revenue > 10000"""

        result = detector.detect(text)

        assert result.artifact_type == ArtifactType.CODE
        assert result.language == CodeLanguage.SQL

    def test_create_table(self, detector: ArtifactDetector) -> None:
        """CREATE TABLE is detected as SQL."""
        text = """CREATE TABLE IF NOT EXISTS catalog.schema.my_table (
    id BIGINT,
    name STRING,
    created_at TIMESTAMP
) USING DELTA
PARTITIONED BY (created_at)"""

        result = detector.detect(text)

        assert result.artifact_type == ArtifactType.CODE
        assert result.language == CodeLanguage.SQL

    def test_insert_statement(self, detector: ArtifactDetector) -> None:
        """INSERT statement is detected as SQL."""
        text = """INSERT INTO target_table
SELECT * FROM source_table
WHERE status = 'active'"""

        result = detector.detect(text)

        assert result.artifact_type == ArtifactType.CODE
        assert result.language == CodeLanguage.SQL


# =============================================================================
# PYTHON CODE DETECTION
# =============================================================================


class TestPythonCodeDetection:
    """Tests for Python code artifact detection."""

    def test_python_function(self, detector: ArtifactDetector) -> None:
        """Python function definition is detected as CODE with PYTHON language."""
        text = """def process_data(df: DataFrame) -> DataFrame:
    \"\"\"Process the input DataFrame.\"\"\"
    result = df.filter(df.status == 'active')
    result = result.groupBy('category').agg(sum('amount'))
    return result"""

        result = detector.detect(text)

        assert result.artifact_type == ArtifactType.CODE
        assert result.language == CodeLanguage.PYTHON
        assert result.confidence >= 0.75  # Single def with indentation

    def test_python_imports(self, detector: ArtifactDetector) -> None:
        """Python imports are detected correctly."""
        text = """from pyspark.sql import SparkSession
from pyspark.sql.functions import col, sum, avg
import pandas as pd

spark = SparkSession.builder.appName("MyApp").getOrCreate()
df = spark.read.table("my_catalog.my_schema.my_table")"""

        result = detector.detect(text)

        assert result.artifact_type == ArtifactType.CODE
        assert result.language == CodeLanguage.PYTHON

    def test_python_class(self, detector: ArtifactDetector) -> None:
        """Python class definition is detected correctly."""
        text = """class DataProcessor:
    def __init__(self, spark):
        self.spark = spark

    def load_data(self, table_name: str):
        return self.spark.read.table(table_name)"""

        result = detector.detect(text)

        assert result.artifact_type == ArtifactType.CODE
        assert result.language == CodeLanguage.PYTHON


# =============================================================================
# SCALA CODE DETECTION
# =============================================================================


class TestScalaCodeDetection:
    """Tests for Scala code artifact detection."""

    def test_scala_val_var(self, detector: ArtifactDetector) -> None:
        """Scala val/var declarations are detected as SCALA."""
        text = """val spark = SparkSession.builder()
    .appName("MyApp")
    .getOrCreate()

val df = spark.read.table("my_table")
var count = df.count()"""

        result = detector.detect(text)

        assert result.artifact_type == ArtifactType.CODE
        assert result.language == CodeLanguage.SCALA
        assert result.confidence >= 0.85

    def test_scala_case_class(self, detector: ArtifactDetector) -> None:
        """Scala case class is detected correctly."""
        text = """case class Customer(
  id: Long,
  name: String,
  email: String,
  createdAt: Timestamp
)

val customerDS = spark.read.table("customers").as[Customer]"""

        result = detector.detect(text)

        assert result.artifact_type == ArtifactType.CODE
        assert result.language == CodeLanguage.SCALA

    def test_scala_object(self, detector: ArtifactDetector) -> None:
        """Scala object definition is detected."""
        text = """object DataPipeline {
  def main(args: Array[String]): Unit = {
    val spark = SparkSession.builder().getOrCreate()
    processData(spark)
  }

  def processData(spark: SparkSession): Unit = {
    val df = spark.read.parquet("/data/input")
    df.write.saveAsTable("output")
  }
}"""

        result = detector.detect(text)

        assert result.artifact_type == ArtifactType.CODE
        assert result.language == CodeLanguage.SCALA


# =============================================================================
# ERROR MESSAGE DETECTION
# =============================================================================


class TestErrorMessageDetection:
    """Tests for short error message detection."""

    def test_simple_exception_message(self, detector: ArtifactDetector) -> None:
        """Simple exception message is detected as ERROR_MESSAGE."""
        text = "java.lang.OutOfMemoryError: Java heap space"

        result = detector.detect(text)

        assert result.artifact_type == ArtifactType.ERROR_MESSAGE
        assert result.confidence >= 0.5  # Short standalone exception

    def test_sqlstate_error(self, detector: ArtifactDetector) -> None:
        """SQLSTATE error is detected as ERROR_MESSAGE."""
        text = "[SQLSTATE 42000] [Error 1064] You have an error in your SQL syntax"

        result = detector.detect(text)

        assert result.artifact_type == ArtifactType.ERROR_MESSAGE
        assert "sqlstate" in result.signals

    def test_permission_denied(self, detector: ArtifactDetector) -> None:
        """Permission denied error is detected."""
        text = "PERMISSION_DENIED: User does not have SELECT permission on table catalog.schema.table"

        result = detector.detect(text)

        assert result.artifact_type == ArtifactType.ERROR_MESSAGE

    def test_analysis_exception(self, detector: ArtifactDetector) -> None:
        """AnalysisException is detected as ERROR_MESSAGE."""
        text = "org.apache.spark.sql.AnalysisException: cannot resolve 'nonexistent_column' given input columns"

        result = detector.detect(text)

        assert result.artifact_type == ArtifactType.ERROR_MESSAGE


# =============================================================================
# MIXED CONTENT DETECTION
# =============================================================================


class TestMixedContentDetection:
    """Tests for mixed artifact type detection."""

    def test_logs_with_stack_trace(self, detector: ArtifactDetector) -> None:
        """Logs containing a stack trace are detected as MIXED or most prominent type."""
        text = """2025-12-17 10:15:23 INFO SparkContext: Starting job 1
2025-12-17 10:15:24 INFO DAGScheduler: Submitting 4 missing tasks
2025-12-17 10:15:25 ERROR Executor: Exception in task 0.0
java.lang.OutOfMemoryError: Java heap space
    at java.util.Arrays.copyOf(Arrays.java:3236)
    at java.util.ArrayList.grow(ArrayList.java:265)
Caused by: org.apache.spark.SparkException: Task failed
    at org.apache.spark.executor.Executor.run(Executor.scala:456)
2025-12-17 10:15:26 INFO TaskSetManager: Lost task 0.0"""

        result = detector.detect(text)

        # Should detect as MIXED or as the dominant type (STACK_TRACE or LOGS)
        assert result.artifact_type in (
            ArtifactType.MIXED,
            ArtifactType.STACK_TRACE,
            ArtifactType.LOGS,
        )
        assert result.confidence >= 0.7

    def test_code_with_error_comment(self, detector: ArtifactDetector) -> None:
        """Code with error in comments should still be detected as CODE."""
        text = """# This query is failing with: AnalysisException: cannot resolve 'bad_col'
SELECT
    customer_id,
    bad_col,  -- This column doesn't exist
    SUM(amount)
FROM sales
GROUP BY 1"""

        result = detector.detect(text)

        # Primary content is SQL code
        assert result.artifact_type == ArtifactType.CODE
        assert result.language == CodeLanguage.SQL


# =============================================================================
# EDGE CASES
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_empty_string(self, detector: ArtifactDetector) -> None:
        """Empty string returns low confidence."""
        result = detector.detect("")

        assert result.confidence < 0.5

    def test_whitespace_only(self, detector: ArtifactDetector) -> None:
        """Whitespace-only input returns low confidence."""
        result = detector.detect("   \n\t\n   ")

        assert result.confidence < 0.5

    def test_short_ambiguous_text(self, detector: ArtifactDetector) -> None:
        """Short ambiguous text returns reasonable result."""
        result = detector.detect("Something went wrong")

        # Should still work, but with lower confidence
        assert result.artifact_type is not None
        assert 0.0 <= result.confidence <= 1.0

    def test_very_long_input(self, detector: ArtifactDetector) -> None:
        """Very long input is handled without error."""
        # Generate a long log file
        log_lines = [
            f"2025-12-17 10:15:{i:02d} INFO Processing batch {i}" for i in range(1000)
        ]
        text = "\n".join(log_lines)

        result = detector.detect(text)

        assert result.artifact_type == ArtifactType.LOGS
        assert result.confidence >= 0.8

    def test_binary_looking_content(self, detector: ArtifactDetector) -> None:
        """Content with many special characters is handled."""
        text = "\\x00\\x01\\x02 some binary data \\xff\\xfe"

        result = detector.detect(text)

        # Should not crash, result may vary
        assert result is not None

    def test_unicode_content(self, detector: ArtifactDetector) -> None:
        """Unicode content is handled correctly."""
        text = """2025-12-17 10:15:23 INFO Processing: 日本語テキスト
2025-12-17 10:15:24 ERROR Failed: 中文错误消息
2025-12-17 10:15:25 WARN Warning: Ελληνικά"""

        result = detector.detect(text)

        assert result.artifact_type == ArtifactType.LOGS


# =============================================================================
# CONFIDENCE SCORING
# =============================================================================


class TestConfidenceScoring:
    """Tests for confidence score accuracy."""

    def test_high_confidence_stack_trace(self, detector: ArtifactDetector) -> None:
        """Clear stack trace should have high confidence."""
        text = """Traceback (most recent call last):
  File "main.py", line 10, in <module>
    raise ValueError("test")
ValueError: test"""

        result = detector.detect(text)

        assert result.confidence >= 0.9

    def test_medium_confidence_ambiguous(self, detector: ArtifactDetector) -> None:
        """Ambiguous content should have lower confidence."""
        text = """Error occurred in the system.
Please check the logs for more details.
Contact support if the issue persists."""

        result = detector.detect(text)

        # Not clearly any specific type, so lower confidence
        assert 0.2 <= result.confidence <= 0.6

    def test_signals_populated(self, detector: ArtifactDetector) -> None:
        """Detection signals should be populated."""
        text = """Traceback (most recent call last):
  File "main.py", line 10, in <module>
    raise ValueError("test")
ValueError: test"""

        result = detector.detect(text)

        assert len(result.signals) > 0
        assert all(isinstance(s, str) for s in result.signals)
