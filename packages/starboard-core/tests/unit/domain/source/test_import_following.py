# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for import_following — extract_imports and resolve_candidates.

TDD: these tests were written before the implementation.
"""

from starboard_core.domain.source.import_following import (
    ImportRef,
    extract_imports,
    resolve_candidates,
)


class TestExtractImports:
    """Tests for extract_imports."""

    # ------------------------------------------------------------------
    # Plain absolute imports
    # ------------------------------------------------------------------

    def test_plain_import_single(self):
        source = "import a"
        assert extract_imports(source) == [ImportRef("a", 0, ())]

    def test_plain_import_dotted(self):
        source = "import a.b.c"
        assert extract_imports(source) == [ImportRef("a.b.c", 0, ())]

    def test_plain_import_two_names(self):
        """import a, b → two separate ImportRef items."""
        source = "import a, b"
        refs = extract_imports(source)
        assert ImportRef("a", 0, ()) in refs
        assert ImportRef("b", 0, ()) in refs

    # ------------------------------------------------------------------
    # from … import …
    # ------------------------------------------------------------------

    def test_from_import_single_name(self):
        source = "from a.b import c"
        assert extract_imports(source) == [ImportRef("a.b", 0, ("c",))]

    def test_from_import_multiple_names(self):
        source = "from a.b import c, d"
        assert extract_imports(source) == [ImportRef("a.b", 0, ("c", "d"))]

    def test_from_import_module_only(self):
        """from pkg import something — module is pkg."""
        source = "from pkg import something"
        assert extract_imports(source) == [ImportRef("pkg", 0, ("something",))]

    # ------------------------------------------------------------------
    # Relative imports
    # ------------------------------------------------------------------

    def test_relative_from_dot_import_x(self):
        """from . import x → level=1, module=""."""
        source = "from . import x"
        assert extract_imports(source) == [ImportRef("", 1, ("x",))]

    def test_relative_from_dot_mod_import_y(self):
        """from .mod import y → level=1, module="mod"."""
        source = "from .mod import y"
        assert extract_imports(source) == [ImportRef("mod", 1, ("y",))]

    def test_relative_two_levels(self):
        """from ..pkg import z → level=2, module="pkg"."""
        source = "from ..pkg import z"
        assert extract_imports(source) == [ImportRef("pkg", 2, ("z",))]

    def test_relative_module_empty_for_dot_import(self):
        """module is empty string for bare-dot relative import."""
        source = "from . import foo, bar"
        refs = extract_imports(source)
        assert len(refs) == 1
        assert refs[0].module == ""
        assert refs[0].level == 1
        assert refs[0].names == ("foo", "bar")

    # ------------------------------------------------------------------
    # Order
    # ------------------------------------------------------------------

    def test_lineno_ascending_order(self):
        """Imports returned in lineno-ascending order."""
        source = "import b\nimport a"
        refs = extract_imports(source)
        assert refs == [ImportRef("b", 0, ()), ImportRef("a", 0, ())]

    def test_multiple_import_types_ordered(self):
        source = "import os\nfrom . import helper\nfrom sys import argv"
        refs = extract_imports(source)
        assert refs[0] == ImportRef("os", 0, ())
        assert refs[1] == ImportRef("", 1, ("helper",))
        assert refs[2] == ImportRef("sys", 0, ("argv",))

    # ------------------------------------------------------------------
    # Import inside function / class
    # ------------------------------------------------------------------

    def test_import_inside_function_captured(self):
        source = "def foo():\n    import os\n    return os.getcwd()"
        refs = extract_imports(source)
        assert ImportRef("os", 0, ()) in refs

    def test_import_inside_class_captured(self):
        source = "class Foo:\n    def bar(self):\n        from sys import argv"
        refs = extract_imports(source)
        assert ImportRef("sys", 0, ("argv",)) in refs

    # ------------------------------------------------------------------
    # SyntaxError → []
    # ------------------------------------------------------------------

    def test_syntax_error_returns_empty(self):
        refs = extract_imports("def broken(:")
        assert refs == []

    def test_empty_source_returns_empty(self):
        refs = extract_imports("")
        assert refs == []

    def test_no_imports_returns_empty(self):
        source = "x = 1\ny = x + 2"
        assert extract_imports(source) == []

    def test_comment_only_returns_empty(self):
        source = "# import os\n# from sys import argv"
        assert extract_imports(source) == []


class TestResolveCandidates:
    """Tests for resolve_candidates."""

    # ------------------------------------------------------------------
    # Absolute — plain import
    # ------------------------------------------------------------------

    def test_absolute_simple_module_candidates(self):
        """import a → root/a.py then root/a/__init__.py."""
        ref = ImportRef("a", 0, ())
        candidates = resolve_candidates(ref, "/project/file.py", ["/R"])
        assert candidates == ["/R/a.py", "/R/a/__init__.py"]

    def test_absolute_dotted_module_candidates(self):
        """import a.b.c → root/a/b/c.py, root/a/b/c/__init__.py."""
        ref = ImportRef("a.b.c", 0, ())
        candidates = resolve_candidates(ref, "/project/file.py", ["/R"])
        assert candidates == ["/R/a/b/c.py", "/R/a/b/c/__init__.py"]

    # ------------------------------------------------------------------
    # Absolute — from … import …
    # ------------------------------------------------------------------

    def test_absolute_from_import_names_before_module(self):
        """from a.b import c, d: per-name candidates come before the package."""
        ref = ImportRef("a.b", 0, ("c", "d"))
        candidates = resolve_candidates(ref, "/project/file.py", ["/R"])
        c_idx = candidates.index("/R/a/b/c.py")
        d_idx = candidates.index("/R/a/b/d.py")
        mod_idx = candidates.index("/R/a/b.py")
        assert c_idx < mod_idx
        assert d_idx < mod_idx

    def test_absolute_from_import_all_candidates_present(self):
        """from a.b import c, d — full expected candidate set."""
        ref = ImportRef("a.b", 0, ("c", "d"))
        candidates = resolve_candidates(ref, "/project/file.py", ["/R"])
        assert "/R/a/b/c.py" in candidates
        assert "/R/a/b/c/__init__.py" in candidates
        assert "/R/a/b/d.py" in candidates
        assert "/R/a/b/d/__init__.py" in candidates
        assert "/R/a/b.py" in candidates
        assert "/R/a/b/__init__.py" in candidates

    def test_absolute_from_single_name_submodule_and_package(self):
        """from pkg import mod → pkg/mod.py, pkg/mod/__init__.py, pkg.py, pkg/__init__.py."""
        ref = ImportRef("pkg", 0, ("mod",))
        candidates = resolve_candidates(ref, "/project/file.py", ["/R"])
        assert "/R/pkg/mod.py" in candidates
        assert "/R/pkg/mod/__init__.py" in candidates
        assert "/R/pkg.py" in candidates
        assert "/R/pkg/__init__.py" in candidates
        # Submodule file before package
        assert candidates.index("/R/pkg/mod.py") < candidates.index("/R/pkg.py")

    # ------------------------------------------------------------------
    # Relative — from . import x
    # ------------------------------------------------------------------

    def test_relative_level1_dot_import_per_name_only(self):
        """from . import x: only per-name candidates; no module-dir candidates."""
        ref = ImportRef("", 1, ("x",))
        candidates = resolve_candidates(ref, "/project/pkg/file.py", [])
        assert "/project/pkg/x.py" in candidates
        assert "/project/pkg/x/__init__.py" in candidates
        # No module → no base.py / base/__init__.py
        assert "/project/pkg.py" not in candidates
        assert "/project/pkg/__init__.py" not in candidates

    def test_relative_level1_dot_import_exact_set(self):
        """from . import x → exactly [pkg/x.py, pkg/x/__init__.py]."""
        ref = ImportRef("", 1, ("x",))
        candidates = resolve_candidates(ref, "/project/pkg/file.py", [])
        assert candidates == ["/project/pkg/x.py", "/project/pkg/x/__init__.py"]

    # ------------------------------------------------------------------
    # Relative — from .mod import y
    # ------------------------------------------------------------------

    def test_relative_level1_with_module(self):
        """from .mod import y: per-name under mod, then mod itself."""
        ref = ImportRef("mod", 1, ("y",))
        candidates = resolve_candidates(ref, "/project/pkg/file.py", [])
        assert "/project/pkg/mod/y.py" in candidates
        assert "/project/pkg/mod/y/__init__.py" in candidates
        assert "/project/pkg/mod.py" in candidates
        assert "/project/pkg/mod/__init__.py" in candidates

    def test_relative_level1_module_package_candidates_after_names(self):
        """from .mod import y: submodule candidate before package candidate."""
        ref = ImportRef("mod", 1, ("y",))
        candidates = resolve_candidates(ref, "/project/pkg/file.py", [])
        assert candidates.index("/project/pkg/mod/y.py") < candidates.index(
            "/project/pkg/mod.py"
        )

    # ------------------------------------------------------------------
    # Relative — from ..pkg import z
    # ------------------------------------------------------------------

    def test_relative_level2(self):
        """from ..pkg import z: go up 1 level from dirname, then extend by pkg."""
        ref = ImportRef("pkg", 2, ("z",))
        candidates = resolve_candidates(ref, "/project/sub/file.py", [])
        assert "/project/pkg/z.py" in candidates
        assert "/project/pkg/z/__init__.py" in candidates
        assert "/project/pkg.py" in candidates
        assert "/project/pkg/__init__.py" in candidates

    def test_relative_level2_base_correct(self):
        """/project/sub/file.py level=2 → go up to /project."""
        ref = ImportRef("pkg", 2, ("z",))
        candidates = resolve_candidates(ref, "/project/sub/file.py", [])
        # base after going up = /project, extended by "pkg" = /project/pkg
        assert "/project/pkg/z.py" in candidates
        # Depth-2 should NOT produce /sub-relative paths
        assert "/project/sub/pkg/z.py" not in candidates

    # ------------------------------------------------------------------
    # Multi-root ordering
    # ------------------------------------------------------------------

    def test_multi_root_earlier_root_first(self):
        """With [R1, R2], R1 candidates appear before R2 candidates."""
        ref = ImportRef("a", 0, ())
        candidates = resolve_candidates(ref, "/project/file.py", ["/R1", "/R2"])
        assert candidates.index("/R1/a.py") < candidates.index("/R2/a.py")

    def test_multi_root_all_candidates_present(self):
        ref = ImportRef("a", 0, ())
        candidates = resolve_candidates(ref, "/project/file.py", ["/R1", "/R2"])
        assert "/R1/a.py" in candidates
        assert "/R1/a/__init__.py" in candidates
        assert "/R2/a.py" in candidates
        assert "/R2/a/__init__.py" in candidates

    # ------------------------------------------------------------------
    # Deduplication
    # ------------------------------------------------------------------

    def test_no_duplicates_repeated_root(self):
        """Duplicate roots do not produce duplicate candidates."""
        ref = ImportRef("a", 0, ())
        candidates = resolve_candidates(ref, "/project/file.py", ["/R", "/R"])
        assert candidates.count("/R/a.py") == 1

    # ------------------------------------------------------------------
    # normpath applied
    # ------------------------------------------------------------------

    def test_normpath_applied_to_all_candidates(self):
        """All returned candidates are normpath-normalised (no //)."""
        ref = ImportRef("a.b", 0, ("c",))
        candidates = resolve_candidates(ref, "/project//file.py", ["/R"])
        for c in candidates:
            assert "//" not in c
            assert c == c.rstrip("/")

    # ------------------------------------------------------------------
    # Relative with empty roots (relative paths don't use roots)
    # ------------------------------------------------------------------

    def test_relative_ignores_roots_parameter(self):
        """Relative imports resolve against dirname(current_file), ignoring roots."""
        ref = ImportRef("", 1, ("helper",))
        candidates_no_root = resolve_candidates(ref, "/project/pkg/f.py", [])
        candidates_with_root = resolve_candidates(ref, "/project/pkg/f.py", ["/R"])
        assert candidates_no_root == candidates_with_root
