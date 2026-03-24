"""
Unit tests for checkpoint system.

Tests file-based checkpointing with mocked filesystem operations.
"""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from pydantic import BaseModel
from starboard_server.infra.rag.checkpoint import (
    is_file_fresh,
    read_checkpoint,
    validate_checkpoint,
    write_checkpoint,
)


class SampleModel(BaseModel):
    """Sample Pydantic model for testing."""

    name: str
    value: int


class TestIsFileFresh:
    """Test is_file_fresh function."""

    def test_file_does_not_exist(self, tmp_path):
        """Should return False if file doesn't exist."""
        nonexistent = tmp_path / "nonexistent.json"
        assert is_file_fresh(nonexistent) is False

    def test_file_is_fresh(self, tmp_path):
        """Should return True if file is fresh (within max_age)."""
        checkpoint_file = tmp_path / "checkpoint.json"
        checkpoint_file.write_text("{}")

        # File was just created, should be fresh
        assert is_file_fresh(checkpoint_file, max_age_minutes=60) is True

    def test_file_is_stale(self, tmp_path):
        """Should return False if file is stale (older than max_age)."""
        checkpoint_file = tmp_path / "checkpoint.json"
        checkpoint_file.write_text("{}")

        # Mock mtime to be 2 hours ago
        two_hours_ago = datetime.now(UTC) - timedelta(hours=2)
        old_timestamp = two_hours_ago.timestamp()

        with patch.object(Path, "stat") as mock_stat:
            mock_stat.return_value = MagicMock(st_mtime=old_timestamp)
            assert is_file_fresh(checkpoint_file, max_age_minutes=60) is False

    def test_file_exactly_at_cutoff(self, tmp_path):
        """Should return False if file is exactly at cutoff age."""
        checkpoint_file = tmp_path / "checkpoint.json"
        checkpoint_file.write_text("{}")

        # Mock mtime to be exactly 60 minutes ago
        exactly_60_min_ago = datetime.now(UTC) - timedelta(minutes=60)
        cutoff_timestamp = exactly_60_min_ago.timestamp()

        with patch.object(Path, "stat") as mock_stat:
            mock_stat.return_value = MagicMock(st_mtime=cutoff_timestamp)
            # At exactly the cutoff, should be considered stale
            assert is_file_fresh(checkpoint_file, max_age_minutes=60) is False

    def test_custom_max_age(self, tmp_path):
        """Should respect custom max_age_minutes."""
        checkpoint_file = tmp_path / "checkpoint.json"
        checkpoint_file.write_text("{}")

        # File just created should be fresh even with short max_age
        assert is_file_fresh(checkpoint_file, max_age_minutes=1) is True


class TestReadCheckpoint:
    """Test read_checkpoint function (async)."""

    @pytest.mark.asyncio
    async def test_checkpoint_exists_and_fresh(self, tmp_path):
        """Should return data if checkpoint exists and is fresh."""
        checkpoint_dir = tmp_path / "checkpoints"
        checkpoint_dir.mkdir()

        checkpoint_file = checkpoint_dir / "test.json"
        test_data = {"tables": [{"name": "table1"}, {"name": "table2"}]}
        checkpoint_file.write_text(json.dumps(test_data))

        result = await read_checkpoint("test", checkpoint_dir)
        assert result == test_data
        assert len(result["tables"]) == 2

    @pytest.mark.asyncio
    async def test_checkpoint_does_not_exist(self, tmp_path):
        """Should return None if checkpoint doesn't exist."""
        checkpoint_dir = tmp_path / "checkpoints"
        checkpoint_dir.mkdir()

        result = await read_checkpoint("nonexistent", checkpoint_dir)
        assert result is None

    @pytest.mark.asyncio
    async def test_checkpoint_is_stale(self, tmp_path):
        """Should return None if checkpoint is stale."""
        checkpoint_dir = tmp_path / "checkpoints"
        checkpoint_dir.mkdir()

        checkpoint_file = checkpoint_dir / "stale.json"
        checkpoint_file.write_text(json.dumps({"data": "old"}))

        # Mock is_file_fresh to return False
        with patch(
            "starboard_server.infra.rag.checkpoint.is_file_fresh", return_value=False
        ):
            result = await read_checkpoint("stale", checkpoint_dir)
            assert result is None

    @pytest.mark.asyncio
    async def test_checkpoint_invalid_json(self, tmp_path):
        """Should return None if checkpoint contains invalid JSON."""
        checkpoint_dir = tmp_path / "checkpoints"
        checkpoint_dir.mkdir()

        checkpoint_file = checkpoint_dir / "invalid.json"
        checkpoint_file.write_text("{invalid json")

        result = await read_checkpoint("invalid", checkpoint_dir)
        assert result is None

    @pytest.mark.asyncio
    async def test_checkpoint_read_permission_error(self, tmp_path):
        """Should return None if unable to read checkpoint."""
        checkpoint_dir = tmp_path / "checkpoints"
        checkpoint_dir.mkdir()

        with (
            patch(
                "starboard_server.infra.rag.checkpoint.is_file_fresh", return_value=True
            ),
            patch(
                "starboard_server.infra.rag.checkpoint.read_json",
                side_effect=PermissionError("Access denied"),
            ),
        ):
            result = await read_checkpoint("test", checkpoint_dir)
            assert result is None


class TestWriteCheckpoint:
    """Test write_checkpoint function (async)."""

    @pytest.mark.asyncio
    async def test_write_checkpoint_success(self, tmp_path):
        """Should write checkpoint successfully."""
        checkpoint_dir = tmp_path / "checkpoints"
        test_data = {"tables": [{"name": "table1", "count": 5}]}

        await write_checkpoint("test", test_data, checkpoint_dir)

        # Verify file exists
        checkpoint_file = checkpoint_dir / "test.json"
        assert checkpoint_file.exists()

        # Verify content
        with checkpoint_file.open("r") as f:
            loaded = json.load(f)
        assert loaded == test_data

    @pytest.mark.asyncio
    async def test_write_checkpoint_creates_directory(self, tmp_path):
        """Should create checkpoint directory if it doesn't exist."""
        checkpoint_dir = tmp_path / "nested" / "checkpoints"
        assert not checkpoint_dir.exists()

        test_data = {"data": "value"}
        await write_checkpoint("test", test_data, checkpoint_dir)

        assert checkpoint_dir.exists()
        assert (checkpoint_dir / "test.json").exists()

    @pytest.mark.asyncio
    async def test_write_checkpoint_overwrites_existing(self, tmp_path):
        """Should overwrite existing checkpoint."""
        checkpoint_dir = tmp_path / "checkpoints"
        checkpoint_dir.mkdir()

        # Write initial data
        initial_data = {"version": 1}
        await write_checkpoint("test", initial_data, checkpoint_dir)

        # Overwrite with new data
        new_data = {"version": 2}
        await write_checkpoint("test", new_data, checkpoint_dir)

        # Verify new data
        checkpoint_file = checkpoint_dir / "test.json"
        with checkpoint_file.open("r") as f:
            loaded = json.load(f)
        assert loaded == new_data
        assert loaded["version"] == 2

    @pytest.mark.asyncio
    async def test_write_checkpoint_with_datetime(self, tmp_path):
        """Should handle datetime objects using default=str."""
        checkpoint_dir = tmp_path / "checkpoints"
        test_data = {
            "timestamp": datetime.now(UTC),
            "tables": [{"name": "table1"}],
        }

        # Should not raise due to default=str
        await write_checkpoint("test", test_data, checkpoint_dir)

        checkpoint_file = checkpoint_dir / "test.json"
        assert checkpoint_file.exists()

    @pytest.mark.asyncio
    async def test_write_checkpoint_permission_error(self, tmp_path):
        """Should raise OSError if unable to write checkpoint."""
        checkpoint_dir = tmp_path / "checkpoints"
        checkpoint_dir.mkdir()

        # Patch write_json to raise permission error
        with (
            patch(
                "starboard_server.infra.rag.checkpoint.write_json",
                side_effect=PermissionError("Access denied"),
            ),
            pytest.raises(PermissionError),
        ):
            await write_checkpoint("test", {"data": "value"}, checkpoint_dir)


class TestValidateCheckpoint:
    """Test validate_checkpoint function."""

    def test_validate_single_dict(self):
        """Should validate single dict wrapped in list."""
        data = {"name": "test", "value": 42}

        result = validate_checkpoint(data, SampleModel)

        assert result is not None
        assert len(result) == 1
        assert result[0].name == "test"
        assert result[0].value == 42

    def test_validate_list_of_dicts(self):
        """Should validate list of dicts."""
        data = [
            {"name": "test1", "value": 1},
            {"name": "test2", "value": 2},
            {"name": "test3", "value": 3},
        ]

        result = validate_checkpoint(data, SampleModel)

        assert result is not None
        assert len(result) == 3
        assert result[0].name == "test1"
        assert result[2].value == 3

    def test_validate_invalid_data(self):
        """Should return None if validation fails."""
        data = [
            {"name": "test1", "value": 1},
            {"name": "test2", "value": "not_an_int"},  # Invalid
        ]

        result = validate_checkpoint(data, SampleModel)

        assert result is None

    def test_validate_missing_required_field(self):
        """Should return None if required field is missing."""
        data = [
            {"name": "test1"},  # Missing 'value'
        ]

        result = validate_checkpoint(data, SampleModel)

        assert result is None

    def test_validate_empty_list(self):
        """Should return empty list for empty input."""
        data: list[dict] = []

        result = validate_checkpoint(data, SampleModel)

        assert result is not None
        assert len(result) == 0

    def test_validate_unexpected_error(self):
        """Should return None on unexpected validation error."""
        # Pass something that will cause an unexpected error
        data = "not a dict or list"  # type: ignore

        result = validate_checkpoint(data, SampleModel)  # type: ignore

        assert result is None


class TestCheckpointIntegration:
    """Integration tests for checkpoint workflow."""

    @pytest.mark.asyncio
    async def test_full_checkpoint_workflow(self, tmp_path):
        """Test complete checkpoint save/load/validate workflow."""
        checkpoint_dir = tmp_path / "checkpoints"

        # Step 1: Write checkpoint
        original_data = [
            {"name": "model1", "value": 10},
            {"name": "model2", "value": 20},
        ]
        await write_checkpoint("test_workflow", original_data, checkpoint_dir)

        # Step 2: Read checkpoint
        loaded_data = await read_checkpoint("test_workflow", checkpoint_dir)
        assert loaded_data is not None
        assert len(loaded_data) == 2

        # Step 3: Validate checkpoint
        validated = validate_checkpoint(loaded_data, SampleModel)
        assert validated is not None
        assert len(validated) == 2
        assert validated[0].name == "model1"
        assert validated[1].value == 20

    @pytest.mark.asyncio
    async def test_stale_checkpoint_workflow(self, tmp_path):
        """Test that stale checkpoints are not loaded."""
        checkpoint_dir = tmp_path / "checkpoints"

        # Write checkpoint
        await write_checkpoint("stale_test", {"data": "old"}, checkpoint_dir)

        # Mock is_file_fresh to simulate staleness
        with patch(
            "starboard_server.infra.rag.checkpoint.is_file_fresh", return_value=False
        ):
            loaded = await read_checkpoint("stale_test", checkpoint_dir)
            assert loaded is None

    @pytest.mark.asyncio
    async def test_invalid_checkpoint_workflow(self, tmp_path):
        """Test that invalid checkpoints return None during validation."""
        checkpoint_dir = tmp_path / "checkpoints"

        # Write invalid data
        invalid_data = [{"name": "test", "value": "not_an_int"}]
        await write_checkpoint("invalid_test", invalid_data, checkpoint_dir)

        # Load and attempt validation
        loaded = await read_checkpoint("invalid_test", checkpoint_dir)
        assert loaded is not None  # Loads fine

        validated = validate_checkpoint(loaded, SampleModel)
        assert validated is None  # Validation fails
