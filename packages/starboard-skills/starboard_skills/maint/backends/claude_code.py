"""Claude Code plugin skills backend for starboard-maint."""
from __future__ import annotations

import filecmp
import shutil
from pathlib import Path

from starboard_skills.maint.state import compute_skills_hash


def install(skills_src: Path, skills_dest: Path) -> dict[str, str]:
    """Vendor *skills_src* tree to *skills_dest*.

    Returns a dict of extra fields to record in maint.json.
    """
    if not skills_src.is_dir():
        raise FileNotFoundError(f"Canonical skills tree not found: {skills_src}")

    # Remove any stale install (symlink or directory).
    if skills_dest.is_symlink() or skills_dest.is_file():
        skills_dest.unlink()
    elif skills_dest.is_dir():
        shutil.rmtree(skills_dest)

    skills_dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(skills_src, skills_dest)

    return {"skills_path": str(skills_dest)}


def remove(skills_dest: Path) -> None:
    """Delete the installed skills directory."""
    if skills_dest.is_symlink() or skills_dest.is_file():
        skills_dest.unlink()
    elif skills_dest.is_dir():
        shutil.rmtree(skills_dest)


def verify(skills_src: Path, skills_dest: Path) -> tuple[bool, str]:
    """Check whether the installed tree is in sync with *skills_src*.

    Returns ``(ok, message)``.
    """
    if not skills_dest.exists():
        return False, f"Not installed: {skills_dest} does not exist"

    src_hash = compute_skills_hash(skills_src)
    dst_hash = compute_skills_hash(skills_dest)
    if src_hash != dst_hash:
        # Show which files differ.
        src_files = {p.relative_to(skills_src).as_posix() for p in skills_src.rglob("*") if p.is_file()}
        dst_files = {p.relative_to(skills_dest).as_posix() for p in skills_dest.rglob("*") if p.is_file()}
        only_src = src_files - dst_files
        only_dst = dst_files - src_files
        differing = {
            rel
            for rel in src_files & dst_files
            if not filecmp.cmp(skills_src / rel, skills_dest / rel, shallow=False)
        }
        parts: list[str] = []
        if only_src:
            parts.append(f"missing from install: {sorted(only_src)}")
        if only_dst:
            parts.append(f"stale in install: {sorted(only_dst)}")
        if differing:
            parts.append(f"content differs: {sorted(differing)}")
        return False, "Drift detected — " + "; ".join(parts)

    return True, f"OK: claude-code skills in sync at {skills_dest}"
