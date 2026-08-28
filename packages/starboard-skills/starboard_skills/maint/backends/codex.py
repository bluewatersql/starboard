"""Codex AGENTS.md backend for starboard-maint."""
from __future__ import annotations

from pathlib import Path

_SECTION_START = "<!-- starboard-maint:start -->"
_SECTION_END = "<!-- starboard-maint:end -->"


def _section_body(skills_src: Path) -> str:
    """Generate the AGENTS.md section body listing available skills."""
    skill_names = sorted(
        d.name
        for d in skills_src.iterdir()
        if d.is_dir() and d.name.startswith("starboard-")
    ) if skills_src.is_dir() else []

    skills_list = "\n".join(f"- `{s}`" for s in skill_names) if skill_names else "- (no skills found)"

    return f"""{_SECTION_START}
## Starboard Skills

Starboard provides AI-powered Databricks workload analysis via `starboard-helper`.

### Available skills
{skills_list}

### Usage
```bash
starboard-helper <domain> <command> [options]
# e.g.:
starboard-helper warehouse list
starboard-helper job list --limit 20
python -m starboard_x.warehouse list
```

See `starboard-helper --help` for full command reference.
{_SECTION_END}"""


def install(agents_md: Path, skills_src: Path) -> dict[str, str]:
    """Add (or update) the Starboard section in *agents_md*.

    Creates *agents_md* if it does not exist.
    Returns extra fields to record in maint.json.
    """
    section = _section_body(skills_src)

    if agents_md.is_file():
        content = agents_md.read_text()
        # Replace existing section if present.
        if _SECTION_START in content:
            start = content.index(_SECTION_START)
            end = content.index(_SECTION_END) + len(_SECTION_END)
            content = content[:start] + section + content[end:]
        else:
            content = content.rstrip("\n") + "\n\n" + section + "\n"
    else:
        agents_md.parent.mkdir(parents=True, exist_ok=True)
        content = section + "\n"

    agents_md.write_text(content)
    return {"agents_md_path": str(agents_md)}


def remove(agents_md: Path) -> None:
    """Remove the Starboard section from *agents_md* (leaves other content)."""
    if not agents_md.is_file():
        return
    content = agents_md.read_text()
    if _SECTION_START not in content:
        return
    start = content.index(_SECTION_START)
    end = content.index(_SECTION_END) + len(_SECTION_END)
    # Strip a leading blank line if it exists before the section.
    prefix = content[:start].rstrip("\n")
    suffix = content[end:].lstrip("\n")
    new_content = (prefix + "\n" + suffix).strip()
    agents_md.write_text(new_content + "\n" if new_content else "")


def verify(agents_md: Path) -> tuple[bool, str]:
    """Check whether the Starboard section is present in *agents_md*.

    Returns ``(ok, message)``.
    """
    if not agents_md.is_file():
        return False, f"Not installed: {agents_md} does not exist"
    content = agents_md.read_text()
    if _SECTION_START not in content:
        return False, f"Starboard section missing from {agents_md}"
    return True, f"OK: Starboard section present in {agents_md}"
