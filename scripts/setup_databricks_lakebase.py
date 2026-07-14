#!/usr/bin/env python3
# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Setup script for Databricks Lakebase database tables.

This script ensures a Lakebase instance exists (creating it if necessary) and sets up
all necessary database objects for the Starboard state management system on a
Databricks Lakebase PostgreSQL instance.

The script performs the following steps:
    1. Check if the Lakebase instance exists
    2. If not found, create a new instance with:
       - Capacity: CU_1
       - Nodes: 1
       - Readable secondaries: False
       - Retention window: 7 days
    3. Add the current user as superadmin
    4. Wait for instance to become available
    5. Run database migrations to create tables and indexes

Usage:
    python scripts/setup_databricks_lakebase.py

Environment Variables:
    LAKEBASE_INSTANCE_NAME: Lakebase instance name (required)
    LAKEBASE_DATABASE_NAME: Database name (required)
    DATABRICKS_CLIENT_ID: OAuth client ID (optional)

Example:
    export LAKEBASE_INSTANCE_NAME="my-lakebase"
    export LAKEBASE_DATABASE_NAME="starboard_db"
    python scripts/setup_databricks_lakebase.py

References:
    https://docs.databricks.com/aws/en/oltp/instances/create/?language=Python+SDK
    https://apps-cookbook.dev/docs/fastapi/building_endpoints/lakebase/lakebase_resources_create
    https://apps-cookbook.dev/docs/fastapi/getting_started/lakebase_connection
"""

import asyncio
import sys
import time
import uuid
from pathlib import Path

import asyncpg
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.database import (
    DatabaseInstance,
    DatabaseInstanceRole,
    DatabaseInstanceRoleAttributes,
    DatabaseInstanceRoleIdentityType,
    DatabaseInstanceRoleMembershipRole,
)

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from starboard.adapters.state.databricks.config import DatabricksLakebaseConfig
from starboard.infra.logging import get_logger, setup_structured_logging

# Setup logging
setup_structured_logging()
logger = get_logger(__name__)


def check_instance_exists(sdk_client: WorkspaceClient, instance_name: str) -> bool:
    """
    Check if a Lakebase instance exists.

    Args:
        sdk_client: Databricks workspace client
        instance_name: Name of the instance to check

    Returns:
        True if instance exists, False otherwise
    """
    try:
        sdk_client.database.get_database_instance(name=instance_name)
        logger.info("Database instance exists", instance=instance_name)
        return True
    except Exception as e:
        # Instance not found or other error
        logger.info(
            "Database instance does not exist",
            instance=instance_name,
            error=str(e),
        )
        return False


def create_database_instance(
    sdk_client: WorkspaceClient,
    instance_name: str,
    capacity: str = "CU_1",
    node_count: int = 1,
    enable_readable_secondaries: bool = False,
    retention_window_in_days: int = 7,
) -> DatabaseInstance:
    """
    Create a new Lakebase database instance.

    Args:
        sdk_client: Databricks workspace client
        instance_name: Name for the new instance
        capacity: Compute capacity (default: CU_1)
        node_count: Number of nodes (default: 1)
        enable_readable_secondaries: Enable readable secondary nodes (default: False)
        retention_window_in_days: Point-in-time recovery window (default: 7)

    Returns:
        Created database instance

    Raises:
        Exception: If instance creation fails
    """
    logger.info(
        "Creating database instance",
        instance=instance_name,
        capacity=capacity,
        nodes=node_count,
        readable_secondaries=enable_readable_secondaries,
        retention_window=retention_window_in_days,
    )

    try:
        instance = sdk_client.database.create_database_instance(
            DatabaseInstance(
                name=instance_name,
                capacity=capacity,
                node_count=node_count,
                enable_readable_secondaries=enable_readable_secondaries,
                retention_window_in_days=retention_window_in_days,
            )
        )
        logger.info(
            "Database instance created successfully",
            instance=instance.name,
            dns=instance.read_write_dns,
            status=instance.state,
        )
        return instance
    except Exception as e:
        logger.error(
            "Failed to create database instance",
            instance=instance_name,
            error=str(e),
            error_type=type(e).__name__,
            exc_info=True,
        )
        raise


def add_superadmin_role(
    sdk_client: WorkspaceClient, instance_name: str, user_id: str
) -> None:
    """
    Add the current user as a superadmin to the database instance.

    Args:
        sdk_client: Databricks workspace client
        instance_name: Name of the database instance
        user_id: User ID to grant superadmin role

    Raises:
        Exception: If role creation fails
    """
    logger.info(
        "Adding superadmin role",
        instance=instance_name,
        user_id=user_id,
    )

    try:
        new_role = DatabaseInstanceRole(
            database_instance_name=instance_name,
            role_attributes=DatabaseInstanceRoleAttributes(
                role_membership_role=DatabaseInstanceRoleMembershipRole.DATABRICKS_SUPERUSER
            ),
            identity_type=DatabaseInstanceRoleIdentityType.USER,
            identity_id=user_id,
        )
        sdk_client.database.create_database_instance_role(new_role)
        logger.info(
            "Superadmin role added successfully",
            instance=instance_name,
            user_id=user_id,
        )
    except Exception as e:
        logger.error(
            "Failed to add superadmin role",
            instance=instance_name,
            user_id=user_id,
            error=str(e),
            error_type=type(e).__name__,
            exc_info=True,
        )
        raise


def ensure_database_instance(config: DatabricksLakebaseConfig) -> None:
    """
    Ensure the database instance exists, creating it if necessary.

    Args:
        config: Databricks Lakebase configuration

    Raises:
        Exception: If instance creation or configuration fails
    """
    logger.info(
        "Ensuring database instance exists",
        instance=config.instance_name,
    )

    sdk_client = WorkspaceClient()

    # Check if instance exists
    if check_instance_exists(sdk_client, config.instance_name):
        logger.info(
            "Database instance already exists, skipping creation",
            instance=config.instance_name,
        )
        return

    # Get current user ID
    try:
        current_user = sdk_client.current_user.me()
        user_id = current_user.id
        logger.info(
            "Retrieved current user", user_id=user_id, email=current_user.user_name
        )
    except Exception as e:
        logger.error(
            "Failed to get current user",
            error=str(e),
            error_type=type(e).__name__,
            exc_info=True,
        )
        raise

    # Create instance
    instance = create_database_instance(
        sdk_client=sdk_client,
        instance_name=config.instance_name,
        capacity="CU_1",
        node_count=1,
        enable_readable_secondaries=False,
        retention_window_in_days=7,
    )

    # Wait for instance to be available
    logger.info("Waiting for instance to become available", instance=instance.name)
    try:
        # Poll for instance status
        max_wait_time = 600  # 10 minutes
        poll_interval = 10  # 10 seconds
        elapsed_time = 0

        while elapsed_time < max_wait_time:
            current_instance = sdk_client.database.get_database_instance(
                name=config.instance_name
            )
            if current_instance.state == "AVAILABLE":
                logger.info(
                    "Database instance is available",
                    instance=config.instance_name,
                )
                break
            elif current_instance.state in ["FAILED", "DELETED"]:
                raise RuntimeError(
                    f"Instance entered terminal state: {current_instance.state}"
                )

            logger.info(
                "Instance not ready yet",
                instance=config.instance_name,
                state=current_instance.state,
                elapsed_seconds=elapsed_time,
            )
            time.sleep(poll_interval)
            elapsed_time += poll_interval
        else:
            raise TimeoutError(
                f"Instance did not become available within {max_wait_time} seconds"
            )
    except Exception as e:
        logger.error(
            "Error waiting for instance availability",
            instance=config.instance_name,
            error=str(e),
            error_type=type(e).__name__,
            exc_info=True,
        )
        raise

    # Add superadmin role
    add_superadmin_role(sdk_client, config.instance_name, user_id)

    logger.info(
        "Database instance configured successfully",
        instance=config.instance_name,
    )


async def get_lakebase_connection(
    config: DatabricksLakebaseConfig,
) -> asyncpg.Connection:
    """
    Create a connection to Lakebase using Databricks SDK credentials.

    Args:
        config: Databricks Lakebase configuration

    Returns:
        Active PostgreSQL connection
    """
    logger.info("Connecting to Lakebase instance", instance=config.instance_name)

    # Initialize Databricks SDK client
    sdk_client = WorkspaceClient()

    # Get database instance details
    database_instance = sdk_client.database.get_database_instance(
        name=config.instance_name
    )

    logger.info(
        "Retrieved database instance details",
        hostname=database_instance.read_write_dns,
        name=database_instance.name,
    )

    # Generate OAuth credentials
    cred = sdk_client.database.generate_database_credential(
        request_id=str(uuid.uuid4()),
        instance_names=[database_instance.name],
    )

    # Build connection string
    username = cred.username
    password = cred.token

    connection_string = (
        f"postgresql://{username}:{password}"
        f"@{database_instance.read_write_dns}:{config.port}"
        f"/{config.database_name}"
        f"?ssl=require"
    )

    # Connect to database
    conn = await asyncpg.connect(connection_string)
    logger.info("Connected to Lakebase successfully")

    return conn


async def run_migration(conn: asyncpg.Connection, migration_file: Path) -> None:
    """
    Run a SQL migration file.

    Args:
        conn: Active database connection
        migration_file: Path to migration SQL file
    """
    logger.info("Running migration", file=migration_file.name)

    sql = migration_file.read_text()

    try:
        await conn.execute(sql)
        logger.info("Migration completed successfully", file=migration_file.name)
    except Exception as e:
        logger.error(
            "Migration failed",
            file=migration_file.name,
            error=str(e),
            error_type=type(e).__name__,
            exc_info=True,
        )
        raise


async def setup_database() -> None:
    """
    Main setup function to create all database objects.

    Steps:
        1. Load configuration from environment
        2. Connect to Lakebase instance
        3. Run migrations in order:
           - 001_initial.sql (conversations table)
           - 002_memory.sql (episodes, facts, profiles with pgvector)
           - 003_indexes.sql (performance indexes)
    """
    logger.info("Starting Databricks Lakebase database setup")

    # Load configuration
    try:
        config = DatabricksLakebaseConfig.from_env()
        logger.info(
            "Configuration loaded",
            instance=config.instance_name,
            database=config.database_name,
        )
    except ValueError as e:
        logger.error("Configuration error", error=str(e))
        sys.exit(1)

    # Ensure database instance exists (create if needed)
    try:
        ensure_database_instance(config)
    except Exception as e:
        logger.error(
            "Failed to ensure database instance exists",
            error=str(e),
            error_type=type(e).__name__,
            exc_info=True,
        )
        sys.exit(1)

    # Get migration files
    migrations_dir = (
        Path(__file__).parent.parent
        / "packages"
        / "starboard-server"
        / "starboard"
        / "adapters"
        / "state"
        / "postgres"
        / "migrations"
    )

    if not migrations_dir.exists():
        logger.error("Migrations directory not found", path=str(migrations_dir))
        sys.exit(1)

    migration_files = sorted(migrations_dir.glob("*.sql"))

    if not migration_files:
        logger.error("No migration files found", path=str(migrations_dir))
        sys.exit(1)

    logger.info("Found migrations", count=len(migration_files))

    # Connect to database
    conn = None
    try:
        conn = await get_lakebase_connection(config)

        # Run migrations in order
        for migration_file in migration_files:
            await run_migration(conn, migration_file)

        # Verify tables were created
        tables = await conn.fetch(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
            AND table_type = 'BASE TABLE'
            ORDER BY table_name
            """
        )

        table_names = [row["table_name"] for row in tables]
        logger.info("Database setup complete", tables=table_names)

        # Verify pgvector extension
        vector_check = await conn.fetchval(
            "SELECT COUNT(*) FROM pg_extension WHERE extname = 'vector'"
        )

        if vector_check > 0:
            logger.info("pgvector extension is installed")
        else:
            logger.warning("pgvector extension not found - vector search will not work")

    except Exception as e:
        logger.error(
            "Database setup failed",
            error=str(e),
            error_type=type(e).__name__,
            exc_info=True,
        )
        sys.exit(1)
    finally:
        if conn:
            await conn.close()
            logger.info("Database connection closed")


def main() -> None:
    """Entry point for the setup script."""
    try:
        asyncio.run(setup_database())
    except KeyboardInterrupt:
        logger.info("Setup interrupted by user")
        sys.exit(130)
    except Exception as e:
        logger.error(
            "Unexpected error",
            error=str(e),
            error_type=type(e).__name__,
            exc_info=True,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
