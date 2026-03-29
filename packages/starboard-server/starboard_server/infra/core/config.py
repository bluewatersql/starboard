"""Application configuration using Pydantic BaseSettings.

Environment variables are loaded automatically by Pydantic. The .env file
is also supported. Field names map to uppercase env var names (e.g.,
``databricks_host`` reads ``DATABRICKS_HOST``).
"""

from __future__ import annotations

import atexit
import json
import os
from typing import Any, ClassVar, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class EnvConfig(BaseSettings):
    """
    Environment configuration for Databricks and LLM settings.

    This is the main configuration used by agents, tools, and LLM clients.
    Loaded from environment variables with sensible defaults.

    Uses Pydantic BaseSettings for automatic type coercion, validation,
    and .env file support.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        # No prefix — existing env vars don't use one
    )

    # Databricks Configuration
    databricks_host: str | None = None
    databricks_token: str | None = None
    databricks_warehouse_id: str | None = None
    default_catalog: str = "main"
    default_schema: str = "default"

    # Warehouse Auto-Creation
    autocreate_dbx_dw: bool = True
    """When True and DATABRICKS_WAREHOUSE_ID is not set, auto-create a
    serverless SQL warehouse on startup. Env var: AUTOCREATE_DBX_DW"""

    databricks_warehouse_name: str = "STARBOARD_AGENT_DW"
    """Name for the auto-created warehouse. Env var: DATABRICKS_WAREHOUSE_NAME"""

    databricks_warehouse_size: str = "X-Large"
    """T-shirt size for the auto-created warehouse. Env var: DATABRICKS_WAREHOUSE_SIZE"""

    # Databricks Support Mode
    is_dbx_support: bool = False
    """When True, execute system catalog grants for the Databricks
    support principal before any workloads. Env var: IS_DBX_SUPPORT"""

    # LLM Configuration
    llm_provider: str = "openai"
    llm_api_key: str | None = None
    llm_model: str = "databricks-claude-sonnet-4-5"
    llm_base_url: str = ""
    llm_temperature: float = 0.4
    llm_max_tokens: int = 75000
    llm_seed: int | None = None

    embedding_model: str = "databricks-bge-large-en"
    embedding_base_url: str = ""
    embedding_cache_ttl: int = 86400  # 24 hours

    # Specialized LLM models for different operations
    llm_planning_model: str | None = None
    llm_planning_temperature: float | None = None
    llm_judge_model: str | None = None
    llm_judge_temperature: float | None = None
    llm_review_model: str | None = None
    llm_review_temperature: float | None = None
    llm_synth_model: str | None = None
    llm_synth_temperature: float | None = None

    # Multi-Agent Configuration
    disabled_agent_domains: list[str] | None = None
    """
    List of domains to completely disable from routing.
    These domains will never be selected by the router.
    Example: ["diagnostic", "table", "compute"]
    """

    # Multi-Agent Model Configuration (Per-Domain Overrides)
    domain_model_overrides: dict[str, str] | None = None
    """
    Per-domain model overrides for multi-agent system.
    Maps domain names to model identifiers.
    Example: {"router": "gpt-4o-mini", "query": "gpt-4o", "diagnostic": "o1-preview"}
    """

    domain_temperature_overrides: dict[str, float] | None = None
    """
    Per-domain temperature overrides for multi-agent system.
    Maps domain names to temperature values (0.0-2.0).
    Example: {"router": 0.2, "query": 0.3, "diagnostic": 0.7}
    """

    # Agent Configuration
    tool_parallelism: int = 4

    # Analytics Configuration
    max_analysis_result_rows: int = Field(
        default=50,
        description=("Maximum number of rows to return from analytics queries."),
    )

    # Server Configuration
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False
    log_level: str = "INFO"
    log_json: bool = False

    # Environment
    environment: Literal["dev", "test", "staging", "production"] = "dev"

    # Database Backend
    database_backend: Literal["postgres", "databricks", "sqlite"] = "sqlite"
    database_url: str | None = None
    sqlite_state_path: str = "./dev_data/starboard_state.db"
    sqlite_memory_path: str = "./dev_data/starboard_memory.db"
    sqlite_vector_path: str = "./dev_data/starboard_vectors.db"
    sqlite_reflexion_path: str = "./dev_data/starboard_reflexion.db"

    # Connection Pools
    postgres_min_pool_size: int = 5
    postgres_max_pool_size: int = 20
    postgres_command_timeout: int = 60

    # Cache Backend
    cache_backend: Literal["memory", "redis", "postgres"] = "memory"
    cache_ttl: int = 300  # 5 minutes default

    # Vector Store Backend
    vector_backend: Literal["sqlite", "chroma", "databricks", "postgres"] = "sqlite"
    embedding_dimension: int = 1024
    vector_metadata_llm_model: str = "databricks-gpt-5-mini"
    vector_metadata_llm_temperature: float = 1.0
    vector_metadata_llm_max_tokens: int = 5000

    # Semantic Cache Configuration
    semantic_cache_threshold: float = 0.95  # Minimum similarity for cache hit

    # Memory Consolidation
    memory_consolidation_enabled: bool = False
    memory_consolidation_interval: int = 3600  # 1 hour

    # Rate Limiting
    rate_limit_enabled: bool = True
    rate_limit_storage: str = "memory://"  # memory:// or redis://...
    rate_limit_default: str = "100/minute"  # Default limit for unprotected routes
    max_request_size: int = 10 * 1024 * 1024  # 10MB default

    # Optional Features
    redis_url: str | None = None
    safe_mode: bool = False
    offline_mode: bool = False
    mock_llm: bool = False
    enable_caching: bool = True
    enable_observability: bool = True
    enable_pii_redaction: bool = True
    enable_reflexion: bool = False
    enable_semantic_cache: bool = True

    # Discovery Configuration
    discovery_lookback_days: int = 30
    discovery_max_parallelism: int = 4
    discovery_domains: list[str] | None = None
    """
    Domains to analyze. None = auto-detect from platform audit.
    Example: ["billing", "jobs", "compute", "query_performance"]
    """
    discovery_data_only: bool = False
    """Skip LLM analysis and only collect raw query data."""
    discovery_output_dir: str = "./discovery_output"
    discovery_llm_model: str | None = None
    """LLM model override for discovery analysis. Falls back to llm_model."""
    discovery_llm_temperature: float = 0.3

    # --- Field validators ---

    _VALID_WAREHOUSE_SIZES: ClassVar[frozenset[str]] = frozenset({
        "2X-Small", "X-Small", "Small", "Medium", "Large", "X-Large",
        "2X-Large", "3X-Large", "4X-Large",
    })

    @field_validator("databricks_warehouse_size", mode="before")
    @classmethod
    def _validate_warehouse_size(cls, v: Any) -> str:
        """Validate warehouse size is a recognized Databricks T-shirt size."""
        normalized = str(v).strip()
        size_map = {s.lower(): s for s in cls._VALID_WAREHOUSE_SIZES}
        canonical = size_map.get(normalized.lower())
        if canonical is None:
            raise ValueError(
                f"Invalid warehouse size '{normalized}'. "
                f"Must be one of: {', '.join(sorted(cls._VALID_WAREHOUSE_SIZES))}"
            )
        return canonical

    @field_validator("databricks_warehouse_name", mode="before")
    @classmethod
    def _validate_warehouse_name(cls, v: Any) -> str:
        """Validate warehouse name is not empty."""
        name = str(v).strip()
        if not name:
            raise ValueError("Warehouse name cannot be empty")
        return name

    @field_validator("disabled_agent_domains", mode="before")
    @classmethod
    def _parse_disabled_domains(cls, v: Any) -> list[str] | None:
        """Parse comma-separated string into list."""
        if isinstance(v, str):
            items = [d.strip() for d in v.split(",") if d.strip()]
            return items if items else None
        return v

    @field_validator("discovery_domains", mode="before")
    @classmethod
    def _parse_discovery_domains(cls, v: Any) -> list[str] | None:
        """Parse comma-separated string into list."""
        if isinstance(v, str):
            items = [d.strip() for d in v.split(",") if d.strip()]
            return items if items else None
        return v

    @field_validator("domain_model_overrides", mode="before")
    @classmethod
    def _parse_domain_model_overrides(cls, v: Any) -> dict[str, str] | None:
        """Parse JSON string into dict."""
        if isinstance(v, str):
            try:
                parsed = json.loads(v)
                if isinstance(parsed, dict):
                    return {k: str(val) for k, val in parsed.items()}
            except (json.JSONDecodeError, ValueError, TypeError):
                pass
            return None
        return v

    @field_validator("domain_temperature_overrides", mode="before")
    @classmethod
    def _parse_domain_temp_overrides(cls, v: Any) -> dict[str, float] | None:
        """Parse JSON string into dict."""
        if isinstance(v, str):
            try:
                parsed = json.loads(v)
                if isinstance(parsed, dict):
                    return {k: float(val) for k, val in parsed.items()}
            except (json.JSONDecodeError, ValueError, TypeError):
                pass
            return None
        return v

    # --- Derived properties ---

    def _strip_http_scheme(self, url: str) -> str:
        if url.startswith(("http://", "https://")):
            return url.split("://", 1)[1]
        return url

    @property
    def databricks_host_no_scheme(self) -> str | None:
        if not self.databricks_host:
            return None
        return self._strip_http_scheme(self.databricks_host)

    @property
    def databricks_http_path(self) -> str | None:
        if not self.databricks_warehouse_id:
            return None
        return f"/sql/1.0/warehouses/{self.databricks_warehouse_id}"

    # --- Cross-field validation (same as original validate_config()) ---

    def validate_config(self) -> None:
        """
        Validate configuration (cross-field rules).

        Raises:
            ValueError: If configuration is invalid
        """
        errors = []

        # Validate required fields in non-offline mode
        if not self.offline_mode:
            if not self.databricks_host:
                errors.append("DATABRICKS_HOST required (unless OFFLINE_MODE=true)")
            if not self.databricks_token:
                errors.append("DATABRICKS_TOKEN required (unless OFFLINE_MODE=true)")
            if not self.llm_api_key:
                errors.append("LLM_API_KEY required (unless OFFLINE_MODE=true)")

        # Validate database configuration
        if (
            self.database_backend in ("postgres", "databricks")
            and not self.database_url
        ):
            errors.append(
                f"DATABASE_URL required for database_backend={self.database_backend}"
            )

        # Validate cache configuration
        if self.cache_backend == "redis" and not self.redis_url:
            errors.append("REDIS_URL required for cache_backend=redis")

        # Validate production environment
        if (
            self.environment in ("staging", "production")
            and self.database_backend == "sqlite"
        ):
            errors.append(
                "SQLite backend not recommended for staging/production "
                "(use postgres or databricks)"
            )

        # Validate pool sizes
        if self.postgres_min_pool_size > self.postgres_max_pool_size:
            errors.append(
                f"postgres_min_pool_size ({self.postgres_min_pool_size}) must be "
                f"<= postgres_max_pool_size ({self.postgres_max_pool_size})"
            )

        # Validate TTL values
        if self.cache_ttl < 0:
            errors.append(f"cache_ttl must be non-negative, got {self.cache_ttl}")
        if self.embedding_cache_ttl < 0:
            errors.append(
                f"embedding_cache_ttl must be non-negative, got {self.embedding_cache_ttl}"
            )

        # Validate memory consolidation interval
        if self.memory_consolidation_interval < 0:
            errors.append(
                f"memory_consolidation_interval must be non-negative, "
                f"got {self.memory_consolidation_interval}"
            )

        # Validate request size
        if self.max_request_size <= 0:
            errors.append(
                f"max_request_size must be positive, got {self.max_request_size}"
            )

        # Validate discovery configuration
        if self.discovery_lookback_days not in (30, 60, 90):
            errors.append(
                f"discovery_lookback_days must be 30, 60, or 90, "
                f"got {self.discovery_lookback_days}"
            )
        if self.discovery_max_parallelism < 1 or self.discovery_max_parallelism > 16:
            errors.append(
                f"discovery_max_parallelism must be 1-16, "
                f"got {self.discovery_max_parallelism}"
            )

        if errors:
            raise ValueError(
                "Configuration validation failed:\n"
                + "\n".join(f"  - {e}" for e in errors)
            )

    # --- Backward-compatible class methods ---

    @staticmethod
    def _parse_json_dict(
        env_value: str | None, value_type: type = str
    ) -> dict[str, Any] | None:
        """
        Parse JSON dictionary from environment variable.

        Args:
            env_value: Raw environment variable value (JSON string)
            value_type: Expected type for dictionary values (str or float)

        Returns:
            Parsed dictionary or None if not set or invalid
        """
        if not env_value:
            return None

        try:
            parsed = json.loads(env_value)
            if not isinstance(parsed, dict):
                return None

            if value_type is float:
                return {k: float(v) for k, v in parsed.items()}
            else:
                return {k: str(v) for k, v in parsed.items()}
        except (json.JSONDecodeError, ValueError, TypeError):
            return None

    @classmethod
    def from_env(cls) -> EnvConfig:
        """
        Load configuration from environment variables.

        Pydantic BaseSettings handles env var loading automatically.
        This method also checks for OPENAI_API_KEY as fallback for llm_api_key.

        Returns:
            EnvConfig instance with values from environment
        """
        config = cls()

        # Fallback: OPENAI_API_KEY -> llm_api_key (backward compat)
        if config.llm_api_key is None:
            openai_key = os.getenv("OPENAI_API_KEY")
            if openai_key:
                config = config.model_copy(update={"llm_api_key": openai_key})

        return config

    def sync_to_env(self) -> None:
        """
        Sync configuration values to runtime environment variables.

        This enables services like Databricks SDK that read directly from
        environment variables to pick up configuration from config files or CLI args.

        Only syncs non-None values to avoid overwriting existing environment
        variables with defaults.

        Security Note:
            This method writes secrets (DATABRICKS_TOKEN, LLM_API_KEY, etc.)
            to ``os.environ``. This is **intentional and load-bearing** — the
            Databricks SDK reads credentials from environment variables at
            runtime. Do NOT remove this method.

            Credentials in log output are protected by the ``redact_credentials``
            structlog processor in ``infra/observability/logging.py``, which
            strips tokens, passwords, and API keys from all structured log events.
        """
        # Databricks Configuration
        if self.databricks_host is not None:
            os.environ["DATABRICKS_HOST"] = self.databricks_host
        if self.databricks_token is not None:
            os.environ["DATABRICKS_TOKEN"] = self.databricks_token
        if self.databricks_warehouse_id is not None:
            os.environ["DATABRICKS_WAREHOUSE_ID"] = self.databricks_warehouse_id
        if self.default_catalog is not None:
            os.environ["DEFAULT_CATALOG"] = self.default_catalog
        if self.default_schema is not None:
            os.environ["DEFAULT_SCHEMA"] = self.default_schema

        # LLM Configuration
        if self.llm_provider is not None:
            os.environ["LLM_PROVIDER"] = self.llm_provider
        if self.llm_api_key is not None:
            os.environ["LLM_API_KEY"] = self.llm_api_key
            # Also set OPENAI_API_KEY for backward compatibility
            if self.llm_provider == "openai":
                os.environ["OPENAI_API_KEY"] = self.llm_api_key
        if self.llm_model is not None:
            os.environ["LLM_MODEL"] = self.llm_model
        if self.llm_base_url is not None:
            os.environ["LLM_BASE_URL"] = self.llm_base_url
        if self.llm_temperature is not None:
            os.environ["LLM_TEMPERATURE"] = str(self.llm_temperature)
        if self.llm_max_tokens is not None:
            os.environ["LLM_MAX_TOKENS"] = str(self.llm_max_tokens)
        if self.llm_seed is not None:
            os.environ["LLM_SEED"] = str(self.llm_seed)
        if self.embedding_model is not None:
            os.environ["EMBEDDING_MODEL"] = self.embedding_model
        if self.embedding_base_url:
            os.environ["EMBEDDING_BASE_URL"] = self.embedding_base_url
        os.environ["EMBEDDING_CACHE_TTL"] = str(self.embedding_cache_ttl)

        # Specialized LLM models
        if self.llm_planning_model is not None:
            os.environ["LLM_PLANNING_MODEL"] = self.llm_planning_model
        if self.llm_planning_temperature is not None:
            os.environ["LLM_PLANNING_TEMPERATURE"] = str(self.llm_planning_temperature)
        if self.llm_judge_model is not None:
            os.environ["LLM_JUDGE_MODEL"] = self.llm_judge_model
        if self.llm_judge_temperature is not None:
            os.environ["LLM_JUDGE_TEMPERATURE"] = str(self.llm_judge_temperature)
        if self.llm_review_model is not None:
            os.environ["LLM_REVIEW_MODEL"] = self.llm_review_model
        if self.llm_review_temperature is not None:
            os.environ["LLM_REVIEW_TEMPERATURE"] = str(self.llm_review_temperature)
        if self.llm_synth_model is not None:
            os.environ["LLM_SYNTH_MODEL"] = self.llm_synth_model
        if self.llm_synth_temperature is not None:
            os.environ["LLM_SYNTH_TEMPERATURE"] = str(self.llm_synth_temperature)

        # Multi-Agent Configuration
        if self.disabled_agent_domains is not None:
            os.environ["DISABLED_AGENT_DOMAINS"] = ",".join(self.disabled_agent_domains)

        # Multi-Agent Model Configuration
        if self.domain_model_overrides is not None:
            os.environ["DOMAIN_MODEL_OVERRIDES"] = json.dumps(
                self.domain_model_overrides
            )
        if self.domain_temperature_overrides is not None:
            os.environ["DOMAIN_TEMPERATURE_OVERRIDES"] = json.dumps(
                self.domain_temperature_overrides
            )

        # Agent Configuration
        os.environ["TOOL_PARALLELISM"] = str(self.tool_parallelism)

        # Analytics Configuration
        os.environ["MAX_ANALYSIS_RESULT_ROWS"] = str(self.max_analysis_result_rows)

        # Server Configuration
        os.environ["HOST"] = self.host
        os.environ["PORT"] = str(self.port)
        os.environ["DEBUG"] = str(self.debug).lower()
        os.environ["LOG_LEVEL"] = self.log_level
        os.environ["LOG_JSON"] = str(self.log_json).lower()

        # Environment
        os.environ["ENVIRONMENT"] = self.environment

        # Database Backend
        os.environ["DATABASE_BACKEND"] = self.database_backend
        if self.database_url is not None:
            os.environ["DATABASE_URL"] = self.database_url
        os.environ["SQLITE_STATE_PATH"] = self.sqlite_state_path
        os.environ["SQLITE_MEMORY_PATH"] = self.sqlite_memory_path
        os.environ["SQLITE_VECTOR_PATH"] = self.sqlite_vector_path
        os.environ["SQLITE_REFLEXION_PATH"] = self.sqlite_reflexion_path

        # Connection Pools
        os.environ["POSTGRES_MIN_POOL_SIZE"] = str(self.postgres_min_pool_size)
        os.environ["POSTGRES_MAX_POOL_SIZE"] = str(self.postgres_max_pool_size)
        os.environ["POSTGRES_COMMAND_TIMEOUT"] = str(self.postgres_command_timeout)

        # Cache Backend
        os.environ["CACHE_BACKEND"] = self.cache_backend
        os.environ["CACHE_TTL"] = str(self.cache_ttl)

        # Vector Store Backend
        os.environ["VECTOR_BACKEND"] = self.vector_backend
        os.environ["EMBEDDING_DIMENSION"] = str(self.embedding_dimension)

        # Semantic Cache
        os.environ["SEMANTIC_CACHE_THRESHOLD"] = str(self.semantic_cache_threshold)

        # Memory Consolidation
        os.environ["MEMORY_CONSOLIDATION_ENABLED"] = str(
            self.memory_consolidation_enabled
        ).lower()
        os.environ["MEMORY_CONSOLIDATION_INTERVAL"] = str(
            self.memory_consolidation_interval
        )

        # Rate Limiting
        os.environ["RATE_LIMIT_ENABLED"] = str(self.rate_limit_enabled).lower()
        os.environ["RATE_LIMIT_STORAGE"] = self.rate_limit_storage
        os.environ["RATE_LIMIT_DEFAULT"] = self.rate_limit_default
        os.environ["MAX_REQUEST_SIZE"] = str(self.max_request_size)

        # Optional Features
        if self.redis_url is not None:
            os.environ["REDIS_URL"] = self.redis_url
        os.environ["SAFE_MODE"] = str(self.safe_mode).lower()
        os.environ["OFFLINE_MODE"] = str(self.offline_mode).lower()
        os.environ["MOCK_LLM"] = str(self.mock_llm).lower()
        os.environ["ENABLE_CACHING"] = str(self.enable_caching).lower()
        os.environ["ENABLE_OBSERVABILITY"] = str(self.enable_observability).lower()
        os.environ["ENABLE_PII_REDACTION"] = str(self.enable_pii_redaction).lower()
        os.environ["ENABLE_REFLEXION"] = str(self.enable_reflexion).lower()
        os.environ["ENABLE_SEMANTIC_CACHE"] = str(self.enable_semantic_cache).lower()

        # Warehouse Auto-Creation
        os.environ["AUTOCREATE_DBX_DW"] = str(self.autocreate_dbx_dw).lower()
        os.environ["DATABRICKS_WAREHOUSE_NAME"] = self.databricks_warehouse_name
        os.environ["DATABRICKS_WAREHOUSE_SIZE"] = self.databricks_warehouse_size

        # Databricks Support Mode
        os.environ["IS_DBX_SUPPORT"] = str(self.is_dbx_support).lower()

        # Discovery Configuration
        os.environ["DISCOVERY_LOOKBACK_DAYS"] = str(self.discovery_lookback_days)
        os.environ["DISCOVERY_MAX_PARALLELISM"] = str(self.discovery_max_parallelism)
        if self.discovery_domains is not None:
            os.environ["DISCOVERY_DOMAINS"] = ",".join(self.discovery_domains)
        os.environ["DISCOVERY_DATA_ONLY"] = str(self.discovery_data_only).lower()
        os.environ["DISCOVERY_OUTPUT_DIR"] = self.discovery_output_dir
        if self.discovery_llm_model is not None:
            os.environ["DISCOVERY_LLM_MODEL"] = self.discovery_llm_model
        os.environ["DISCOVERY_LLM_TEMPERATURE"] = str(self.discovery_llm_temperature)

        # Register cleanup handler to remove sensitive env vars on process exit.
        # This limits the window in which secrets are exposed in the process environment.
        _sensitive_env_keys = [
            "DATABRICKS_TOKEN",
            "LLM_API_KEY",
            "OPENAI_API_KEY",
        ]

        def _cleanup_sensitive_env_vars() -> None:
            for key in _sensitive_env_keys:
                os.environ.pop(key, None)

        atexit.register(_cleanup_sensitive_env_vars)


# Global singleton instance
_env_config: EnvConfig | None = None


def get_config() -> EnvConfig:
    """
    Get the global EnvConfig singleton.

    Returns:
        EnvConfig instance loaded from environment variables
    """
    global _env_config
    if _env_config is None:
        _env_config = EnvConfig.from_env()
    return _env_config


def set_config(config: EnvConfig, *, sync_to_env: bool = True) -> None:
    """
    Set the global EnvConfig singleton.

    Args:
        config: EnvConfig instance to set as global singleton
        sync_to_env: If True, sync config values to runtime environment variables.
    """
    global _env_config
    _env_config = config
    if sync_to_env:
        config.sync_to_env()
