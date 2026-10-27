"""The ``starboard`` package uses the public ``starboard_x`` surfaces, not private modules."""

from __future__ import annotations

import re
from pathlib import Path

import starboard
from starboard_x import _cli, cli
from starboard_x.discovery import _authorization, _serialize, authorization, serialize

#: A private ``starboard_x`` module (a ``_x`` segment; ``__main__`` is not private)
#: reached by ``import starboard_x[.pkg]._x``, ``from starboard_x[.pkg]._x import``
#: or ``from starboard_x[.pkg] import _x`` (lower-case: a private module or helper;
#: an upper-case private constant re-exported for a shim is not plumbing).
_PRIVATE = re.compile(
    r"^\s*(?:"
    r"import\s+starboard_x(?:\.\w+)*\._(?!_)\w*"
    r"|from\s+starboard_x(?:\.\w+)*\._(?!_)\w*(?:\.\w+)*\s+import\b"
    r"|from\s+starboard_x(?:\.\w+)*\s+import\s+\(?\s*_[a-z]"
    r")",
    re.M,
)

_SOURCE_ROOT = Path(str(starboard.__file__)).parent


def test_public_modules_re_export_the_private_implementations() -> None:
    for public, private in (
        (cli, _cli),
        (authorization, _authorization),
        (serialize, _serialize),
    ):
        assert public.__all__
        for name in public.__all__:
            assert getattr(public, name) is getattr(private, name), name


def test_the_scan_catches_every_private_import_form() -> None:
    for line in (
        "import starboard_x._cli",
        "    import starboard_x.discovery._serialize as s",
        "from starboard_x._cli import RefusedError",
        "    from starboard_x.discovery._serialize import write_result_files",
        "from starboard_x import _cli",
        "from starboard_x.discovery import _authorization",
    ):
        assert _PRIVATE.search(line), line
    for line in (
        "from starboard_x.cli import RefusedError",
        "from starboard_x.discovery.serialize import write_result_files",
        "from starboard_x.review.__main__ import render_markdown",
        "import starboard_x.contract",
        "from starboard_x.diagnostic.models import (\n    _PATTERN_TO_SYMPTOM,",
    ):
        assert not _PRIVATE.search(line), line


def test_starboard_package_does_not_import_private_starboard_x_plumbing() -> None:
    offenders = [
        f"{path.relative_to(_SOURCE_ROOT)}:{source.count(chr(10), 0, m.start()) + 1}"
        for path in sorted(_SOURCE_ROOT.rglob("*.py"))
        for source in (path.read_text(encoding="utf-8"),)
        for m in _PRIVATE.finditer(source)
    ]
    assert not offenders, offenders
