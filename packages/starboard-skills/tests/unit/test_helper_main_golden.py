"""Public (no-overlay) golden bytes for the helper writers.

Phase 2 routes every helper writer through the artifact sink. On a public install
without ``--run-folder`` the stdout and every written file must stay byte-for-byte
what the pre-sink helpers produced. The golden files were captured from the
pre-change code; set ``STARBOARD_UPDATE_HELPER_GOLDEN=1`` to re-capture (only when an
intended public output change lands).
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from starboard_skills.helpers import __main__ as cli
from starboard_skills.helpers import charts_render
from starboard_skills.helpers import query as q
from starboard_skills.helpers import run as run_mod

from .test_notebook_helper import run_dir  # noqa: F401  (fixture)
from .test_run_check import _make_run
from .test_run_recur import _case, _make_run_dir, _rid
from .test_verify_helper import _TEMPLATES

GOLDEN = Path(__file__).parent / "golden_helpers"
_UPDATE = os.environ.get("STARBOARD_UPDATE_HELPER_GOLDEN") == "1"


_PKG = str(Path(cli.__file__).resolve().parents[2])


def _norm(text: str, root: Path) -> str:
    for p in sorted({str(root.resolve()), str(root)}, key=len, reverse=True):
        text = text.replace(p, "<TMP>")
    return text.replace(_PKG, "<PKG>")


def _files(root: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        data = p.read_bytes()
        try:
            out[p.relative_to(root).as_posix()] = _norm(data.decode("utf-8"), root)
        except UnicodeDecodeError:
            out[p.relative_to(root).as_posix()] = "base64:" + base64.b64encode(data).decode()
    return out


def _main(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str]:
    with pytest.raises(SystemExit) as exc:
        cli.main(argv)
    code = exc.value.code if isinstance(exc.value.code, int) else 1
    return code, capsys.readouterr().out


def _check(name: str, root: Path, code: int, stdout: str, *, before: dict[str, str]) -> None:
    after = _files(root)
    got = {
        "exit": code,
        "stdout": _norm(stdout, root),
        "files": {k: v for k, v in after.items() if before.get(k) != v},
    }
    path = GOLDEN / f"{name}.json"
    if _UPDATE:
        GOLDEN.mkdir(exist_ok=True)
        path.write_text(json.dumps(got, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    want = json.loads(path.read_text(encoding="utf-8"))
    assert got == want


def _without_profile_keys(text: str) -> str:
    """``text`` (an indented ``run check`` envelope) without the phase-4 profile keys."""
    doc = json.loads(text)
    data = doc["data"]
    for key in ("profile", "profile_source", "skipped_by_profile"):
        data.pop(key)
    data["warnings"] = data["warnings"][1:]
    return json.dumps(doc, indent=2) + "\n"


def _client(n: int = 2) -> MagicMock:
    c = MagicMock()
    c.jobs.list.return_value = iter(
        [SimpleNamespace(job_id=i, settings=SimpleNamespace(name=f"job-{i}")) for i in range(n)]
    )
    return c


@pytest.fixture
def work(tmp_path: Path) -> Path:
    w = tmp_path / "w"
    w.mkdir()
    return w


@pytest.fixture
def fake_sql(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        q,
        "cmd_sql",
        lambda args: {"columns": ["a"], "rows": [["1"]], "row_count": 1,
                      "limit_reached": False, "state": "SUCCEEDED", "read_only": True},
    )


@pytest.mark.unit
class TestPublicGolden:
    def test_fetch_out(self, work, monkeypatch, capsys):
        monkeypatch.setattr("databricks.sdk.WorkspaceClient", lambda *a, **k: _client())
        before = _files(work)
        code, out = _main(["job", "list", "--out", str(work / "jobs.json")], capsys)
        _check("fetch_out", work, code, out, before=before)

    def test_fetch_stdout(self, work, monkeypatch, capsys):
        monkeypatch.setattr("databricks.sdk.WorkspaceClient", lambda *a, **k: _client())
        before = _files(work)
        code, out = _main(["job", "list"], capsys)
        _check("fetch_stdout", work, code, out, before=before)

    def test_verify_run(self, work, fake_sql, capsys):
        (work / "verify-sql.md").write_text(_TEMPLATES, encoding="utf-8")
        before = _files(work)
        code, out = _main(
            ["verify", "run", "vt-product-totals", "--templates", str(work / "verify-sql.md"),
             "--ws", "123", "--start", "2026-09-01", "--end", "2026-09-30",
             "--warehouse-id", "wh-1", "--out", str(work / "analysis" / "verify")],
            capsys,
        )
        _check("verify_run", work, code, out, before=before)

    def test_verify_run_failure(self, work, fake_sql, capsys):
        (work / "verify-sql.md").write_text(_TEMPLATES, encoding="utf-8")
        before = _files(work)
        code, out = _main(
            ["verify", "run", "vt-job-run-tail", "--templates", str(work / "verify-sql.md"),
             "--ws", "123", "--start", "2026-09-01", "--end", "2026-09-30",
             "--warehouse-id", "wh-1", "--out", str(work / "analysis" / "verify")],
            capsys,
        )
        _check("verify_run_failure", work, code, out, before=before)

    @pytest.mark.parametrize("fmt", ["png", "svg"])
    def test_charts_render(self, work, monkeypatch, capsys, fmt):
        monkeypatch.setattr(charts_render, "_vegalite_to_png", lambda vl: b"\x89PNG-fake")
        monkeypatch.setattr(charts_render, "_vegalite_to_svg", lambda vl: b"<svg>fake</svg>")
        (work / "d.json").write_text(
            json.dumps([{"billing_origin_product": "JOBS", "total_dbus": 10}])
        )
        before = _files(work)
        code, out = _main(
            ["charts", "render", "--kind", "spend-by-product", "--data", str(work / "d.json"),
             "--out", str(work / "deliverables" / "charts" / f"spend.{fmt}"), "--format", fmt],
            capsys,
        )
        _check(f"charts_render_{fmt}", work, code, out, before=before)

    def test_notebook_render(self, run_dir, capsys):  # noqa: F811
        before = _files(run_dir)
        code, out = _main(
            ["notebook", "render", "--backlog", str(run_dir / "analysis" / "backlog.json"),
             "--all", "--out", str(run_dir / "deliverables" / "notebooks"),
             "--source-templates", str(run_dir / "source.md")],
            capsys,
        )
        _check("notebook_render", run_dir, code, out, before=before)

    def test_run_check(self, tmp_path, capsys):
        rd = _make_run(tmp_path)
        before = _files(tmp_path)
        code, out = _main(
            ["run", "check", str(rd), "--out", str(rd / "analysis" / "run-check.json")], capsys
        )
        # A run dir with no run authorization is today's checklist plus the profile
        # keys (phase 4 §B3); the golden stays the pre-profile envelope.
        record = rd / "analysis" / "run-check.json"
        for text in (out, record.read_text()):
            data = json.loads(text)["data"]
            assert (data["profile"], data["profile_source"]) == ("action_plan", "default")
            assert data["warnings"][0] == "no run authorization: using the action_plan checklist"
            assert data["skipped_by_profile"] == [
                "health_present", "plays_present", "health_report",
                "case_linked", "focused_report", "review_json",
            ]
        out = _without_profile_keys(out)
        record.write_text(_without_profile_keys(record.read_text()))
        _check("run_check", tmp_path, code, out, before=before)

    def test_run_recur_baseline(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(run_mod, "_render_available", lambda: True)
        monkeypatch.setattr(charts_render, "_vegalite_to_png", lambda vl: b"\x89PNG-fake")
        case = _case(tmp_path)
        rd = _make_run_dir(case, _rid("2026-10-01"), "2026-10-01")
        before = _files(tmp_path)
        code, out = _main(["run", "recur", str(rd), "--workspace-root", str(case)], capsys)
        _check("run_recur_baseline", tmp_path, code, out, before=before)

    def test_run_recur_prior(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(run_mod, "_render_available", lambda: True)
        monkeypatch.setattr(charts_render, "_vegalite_to_png", lambda vl: b"\x89PNG-fake")
        case = _case(tmp_path)
        _make_run_dir(case, _rid("2026-09-01"), "2026-09-01")
        rd = _make_run_dir(case, _rid("2026-10-01", 1), "2026-10-01")
        before = _files(tmp_path)
        code, out = _main(["run", "recur", str(rd), "--workspace-root", str(case)], capsys)
        _check("run_recur_prior", tmp_path, code, out, before=before)
