"""maint.json state round-trip and skills-tree hashing."""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "1.0"


def _utcnow() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def compute_skills_hash(skills_root: Path) -> str:
    """SHA-256 over sorted (relative-path, content) pairs in *skills_root*.

    Returns ``"sha256:<hex>"`` or ``"sha256:empty"`` when the tree is absent.
    """
    if not skills_root.is_dir():
        return "sha256:empty"
    h = hashlib.sha256()
    for p in sorted(skills_root.rglob("*")):
        if p.is_file():
            rel = p.relative_to(skills_root).as_posix()
            h.update(rel.encode())
            h.update(b"\x00")
            h.update(p.read_bytes())
            h.update(b"\x00")
    return f"sha256:{h.hexdigest()}"


def load(maint_json: Path) -> dict[str, Any]:
    """Load state from *maint_json*; return a default skeleton if absent."""
    if maint_json.is_file():
        try:
            data = json.loads(maint_json.read_text())
            if isinstance(data, dict):
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return {
        "schema_version": SCHEMA_VERSION,
        "starboard_version": None,
        "scope": None,
        "installed_at": None,
        "updated_at": None,
        "skills_hash": None,
        "platforms": {},
    }


def save(state: dict[str, Any], maint_json: Path) -> None:
    """Atomically persist *state* to *maint_json* (creates parents)."""
    maint_json.parent.mkdir(parents=True, exist_ok=True)
    tmp = maint_json.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2) + "\n")
    tmp.replace(maint_json)


def mark_installed(
    state: dict[str, Any],
    *,
    platform: str,
    scope: str,
    skills_hash: str,
    extra: dict[str, Any] | None = None,
) -> None:
    """Mutate *state* in-place to record a platform install."""
    now = _utcnow()
    if state.get("installed_at") is None:
        state["installed_at"] = now
    state["updated_at"] = now
    state["scope"] = scope
    state["skills_hash"] = skills_hash
    state.setdefault("platforms", {})[platform] = {
        "status": "installed",
        "installed_at": now,
        **(extra or {}),
    }


def mark_removed(state: dict[str, Any], *, platform: str) -> None:
    """Mutate *state* in-place to record platform removal."""
    state.setdefault("platforms", {}).pop(platform, None)
    state["updated_at"] = _utcnow()
