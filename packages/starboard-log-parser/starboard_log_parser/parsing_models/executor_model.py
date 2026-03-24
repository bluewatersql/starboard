from __future__ import annotations


class ExecutorModel:
    """
    Model for a Spark Executor (i.e. worker node)
    """

    id: str | None = None
    host: str | None = None
    cores: int | None = None
    start_time: int | None = None
    end_time: int | None = None
    removed_reason: str = ""
