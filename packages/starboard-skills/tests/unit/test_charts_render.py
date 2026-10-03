"""Unit tests for the charts render helper (Task 2.2).

The renderer dep (vl-convert-python) is mocked so these tests carry no heavy dep.
"""
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from starboard_skills.helpers import charts_render as cr


def test_render_builds_vega_lite_from_spec_and_data(tmp_path, monkeypatch):
    data = [{"billing_origin_product": "VECTOR_SEARCH", "total_dbus": 1660000}]
    dfile = tmp_path / "d.json"
    dfile.write_text(json.dumps(data))
    out = tmp_path / "chart.png"
    fake = MagicMock(return_value=b"\x89PNG\r\n")
    monkeypatch.setattr(cr, "_vegalite_to_png", fake)
    cr.cmd_render(SimpleNamespace(kind="spend-by-product", data=str(dfile), out=str(out), format="png"))
    assert out.read_bytes().startswith(b"\x89PNG")
    vl = fake.call_args[0][0]   # the assembled Vega-Lite dict
    assert vl["data"]["values"] == data
    # spend-by-product is now horizontal: x = measure (total_dbus), y = product
    assert vl["encoding"]["x"]["field"] == "total_dbus"


def test_render_rejects_unknown_kind(tmp_path):
    with pytest.raises(Exception):
        cr.cmd_render(SimpleNamespace(kind="bogus", data=str(tmp_path / "x.json"), out=str(tmp_path / "o.png"), format="png"))


# ---------------------------------------------------------------------------
# FIX A — schema mismatch guard
# ---------------------------------------------------------------------------

def test_render_raises_arg_error_on_schema_mismatch(tmp_path, monkeypatch):
    """Rows that don't contain the encoding field → ArgError, not a blank chart."""
    from starboard_skills.helpers.contract import ArgError

    # Data rows have 'product' but the spend-by-product spec encodes 'total_dbus' on y.
    # Provide a row that is completely missing the required encoding field.
    bad_rows = [{"product": "JOBS", "wrong_field": 42}]
    dfile = tmp_path / "bad.json"
    dfile.write_text(__import__("json").dumps(bad_rows))
    out = tmp_path / "chart.png"

    # Mock renderer so the test never touches vl-convert.
    monkeypatch.setattr(cr, "_vegalite_to_png", MagicMock(return_value=b"\x89PNG"))

    with pytest.raises(ArgError) as exc_info:
        cr.cmd_render(SimpleNamespace(
            kind="spend-by-product",
            data=str(dfile),
            out=str(out),
            format="png",
        ))

    msg = str(exc_info.value)
    # Error must name at least one missing field and mention what was found.
    assert "total_dbus" in msg or "billing_origin_product" in msg
    assert "wrong_field" in msg or "product" in msg
    # Regression (dedupe): spend-by-product drives billing_origin_product on two
    # encoding channels; the missing-field list must NOT repeat it.
    assert "'billing_origin_product', 'billing_origin_product'" not in msg
    # The error teaches the full expected schema for the kind, so the user need
    # not trigger repeated failures to discover it.
    assert "total_dbus" in msg and "billing_origin_product" in msg


def test_render_allows_empty_rows(tmp_path, monkeypatch):
    """Empty rows list is allowed (intentional no-data chart) — must not raise."""
    dfile = tmp_path / "empty.json"
    dfile.write_text("[]")
    out = tmp_path / "chart.png"
    monkeypatch.setattr(cr, "_vegalite_to_png", MagicMock(return_value=b"\x89PNG"))
    # Should not raise — empty dataset is a valid render case.
    result = cr.cmd_render(SimpleNamespace(
        kind="spend-by-product",
        data=str(dfile),
        out=str(out),
        format="png",
    ))
    assert result["kind"] == "spend-by-product"


# ---------------------------------------------------------------------------
# FIX B — sort preservation, chart title, mark options, mkdir out-dir
# ---------------------------------------------------------------------------


def test_render_preserves_sort_on_encoding(tmp_path, monkeypatch):
    # spend-by-product is now horizontal: y=product with sort="-x" (largest first).
    data = [{"billing_origin_product": "JOBS", "total_dbus": 10}]
    dfile = tmp_path / "d.json"
    dfile.write_text(json.dumps(data))
    fake = MagicMock(return_value=b"\x89PNG")
    monkeypatch.setattr(cr, "_vegalite_to_png", fake)
    cr.cmd_render(SimpleNamespace(kind="spend-by-product", data=str(dfile),
                                  out=str(tmp_path / "c.png"), format="png"))
    vl = fake.call_args[0][0]
    assert vl["encoding"]["y"]["sort"] == "-x"


def test_render_sets_chart_title(tmp_path, monkeypatch):
    data = [{"billing_origin_product": "JOBS", "total_dbus": 10}]
    dfile = tmp_path / "d.json"
    dfile.write_text(json.dumps(data))
    fake = MagicMock(return_value=b"\x89PNG")
    monkeypatch.setattr(cr, "_vegalite_to_png", fake)
    cr.cmd_render(SimpleNamespace(kind="spend-by-product", data=str(dfile),
                                  out=str(tmp_path / "c.png"), format="png"))
    vl = fake.call_args[0][0]
    # title carries the spec's precise DBU/list-price labeling
    assert "DBU" in vl["title"]["text"]


def test_render_applies_line_options(tmp_path, monkeypatch):
    data = [{"usage_date": "2026-09-01", "list_cost_usd": 5.0}]
    dfile = tmp_path / "d.json"
    dfile.write_text(json.dumps(data))
    fake = MagicMock(return_value=b"\x89PNG")
    monkeypatch.setattr(cr, "_vegalite_to_png", fake)
    cr.cmd_render(SimpleNamespace(kind="cost-trend", data=str(dfile),
                                  out=str(tmp_path / "c.png"), format="png"))
    vl = fake.call_args[0][0]
    assert isinstance(vl["mark"], dict) and vl["mark"]["type"] == "line"
    assert vl["mark"].get("point") is True


def test_render_creates_missing_out_dir(tmp_path, monkeypatch):
    data = [{"billing_origin_product": "JOBS", "total_dbus": 10}]
    dfile = tmp_path / "d.json"
    dfile.write_text(json.dumps(data))
    monkeypatch.setattr(cr, "_vegalite_to_png", MagicMock(return_value=b"\x89PNG"))
    nested = tmp_path / "does" / "not" / "exist" / "c.png"
    result = cr.cmd_render(SimpleNamespace(kind="spend-by-product", data=str(dfile),
                                           out=str(nested), format="png"))
    assert nested.exists()
    assert result["out_path"] == str(nested.resolve())


# ---------------------------------------------------------------------------
# Bootstrap auto-install wiring
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# CLI path — global ``--out`` must NOT shadow ``charts render --out``
# ---------------------------------------------------------------------------


def test_cli_charts_render_out_is_image_path_not_envelope(tmp_path, monkeypatch, capsys):
    """`starboard-helper charts render ... --out chart.png` writes a real PNG.

    Regression: the global ``--out`` envelope-redirect used to steal the flag,
    starving the required charts ``--out`` (argparse error) and, when present,
    writing the JSON envelope over the image path. The ``charts`` domain owns
    its ``--out``.
    """
    from starboard_skills.helpers import __main__ as cli

    data = [{"billing_origin_product": "VECTOR_SEARCH", "total_dbus": 1660000}]
    dfile = tmp_path / "rows.json"
    dfile.write_text(json.dumps(data))
    out = tmp_path / "spend.png"
    monkeypatch.setattr(cr, "_vegalite_to_png", MagicMock(return_value=b"\x89PNG\r\n\x1a\n"))

    with pytest.raises(SystemExit) as exc:
        cli.main(["charts", "render", "--kind", "spend-by-product",
                  "--data", str(dfile), "--out", str(out)])
    assert exc.value.code == 0

    # The image path holds PNG bytes, NOT a JSON envelope.
    assert out.read_bytes().startswith(b"\x89PNG")
    # stdout carries the success envelope describing the render.
    env = json.loads(capsys.readouterr().out)
    assert env["ok"] is True
    assert env["data"]["out_path"].endswith("spend.png")
    assert env["data"]["bytes_written"] > 0


def test_extract_out_skips_charts_domain():
    """The charts domain keeps its own ``--out`` — global extraction is skipped."""
    from starboard_skills.helpers import __main__ as cli

    argv = ["charts", "render", "--kind", "spend-by-product",
            "--data", "d.json", "--out", "c.png"]
    assert cli._extract_out(argv) == (None, argv)
    # even when a global --out precedes the charts domain, it is left intact
    argv2 = ["--out", "e.json", "charts", "render", "--out", "c.png"]
    assert cli._extract_out(argv2) == (None, argv2)
    # non-charts domains are unaffected
    assert cli._extract_out(["job", "list", "--out", "f"]) == ("f", ["job", "list"])


def test_vegalite_to_png_raises_helper_error_with_render_spec_when_disabled(monkeypatch):
    """With auto-install disabled and vl_convert absent, HelperError surfaces the render spec."""
    from unittest.mock import patch  # noqa: PLC0415

    import starboard_x._bootstrap as _bstrap  # noqa: PLC0415
    from starboard_skills.helpers.contract import HelperError  # noqa: PLC0415

    monkeypatch.setenv("STARBOARD_NO_AUTO_INSTALL", "1")

    with (
        pytest.raises(HelperError) as exc_info,
        patch.object(_bstrap.importlib, "import_module", side_effect=ImportError("absent")),
    ):
        cr._vegalite_to_png({"mark": "bar", "data": {"values": []}, "encoding": {}})

    assert "starboard-skills[render]" in str(exc_info.value)
    assert "pip install" in str(exc_info.value)


def test_vegalite_to_svg_raises_helper_error_with_render_spec_when_disabled(monkeypatch):
    """Same contract for the SVG path."""
    from unittest.mock import patch  # noqa: PLC0415

    import starboard_x._bootstrap as _bstrap  # noqa: PLC0415
    from starboard_skills.helpers.contract import HelperError  # noqa: PLC0415

    monkeypatch.setenv("STARBOARD_NO_AUTO_INSTALL", "1")

    with (
        pytest.raises(HelperError) as exc_info,
        patch.object(_bstrap.importlib, "import_module", side_effect=ImportError("absent")),
    ):
        cr._vegalite_to_svg({"mark": "bar", "data": {"values": []}, "encoding": {}})

    assert "starboard-skills[render]" in str(exc_info.value)
    assert "pip install" in str(exc_info.value)


# ---------------------------------------------------------------------------
# NDJSON input (glm #5)
# ---------------------------------------------------------------------------


def test_render_accepts_ndjson(tmp_path, monkeypatch):
    """charts render --data accepts NDJSON (newline-delimited JSON, e.g. jq .[] -c output)."""
    ndjson = "\n".join([
        json.dumps({"billing_origin_product": "JOBS", "total_dbus": 1000}),
        json.dumps({"billing_origin_product": "SQL", "total_dbus": 500}),
    ])
    dfile = tmp_path / "rows.ndjson"
    dfile.write_text(ndjson)
    out = tmp_path / "chart.png"
    fake = MagicMock(return_value=b"\x89PNG")
    monkeypatch.setattr(cr, "_vegalite_to_png", fake)
    result = cr.cmd_render(
        SimpleNamespace(kind="spend-by-product", data=str(dfile), out=str(out), format="png")
    )
    assert result["kind"] == "spend-by-product"
    vl = fake.call_args[0][0]
    assert len(vl["data"]["values"]) == 2
    assert vl["data"]["values"][0]["billing_origin_product"] == "JOBS"


def test_render_ndjson_with_trailing_newline(tmp_path, monkeypatch):
    """NDJSON with trailing blank line is handled correctly."""
    ndjson = (
        json.dumps({"billing_origin_product": "JOBS", "total_dbus": 100}) + "\n"
        + json.dumps({"billing_origin_product": "SQL", "total_dbus": 50}) + "\n"
        + "\n"  # trailing blank line
    )
    dfile = tmp_path / "rows.ndjson"
    dfile.write_text(ndjson)
    fake = MagicMock(return_value=b"\x89PNG")
    monkeypatch.setattr(cr, "_vegalite_to_png", fake)
    result = cr.cmd_render(
        SimpleNamespace(
            kind="spend-by-product", data=str(dfile),
            out=str(tmp_path / "c.png"), format="png",
        )
    )
    assert result is not None
    vl = fake.call_args[0][0]
    assert len(vl["data"]["values"]) == 2


def test_render_ndjson_bad_line_names_expected_shapes(tmp_path):
    """When a line in NDJSON is not valid JSON, the error names both expected shapes."""
    from starboard_skills.helpers.contract import ArgError

    bad = tmp_path / "bad.ndjson"
    bad.write_text("this is not json\nalso not json")
    with pytest.raises(ArgError) as exc_info:
        cr.cmd_render(
            SimpleNamespace(
                kind="spend-by-product", data=str(bad),
                out=str(tmp_path / "o.png"), format="png",
            )
        )
    msg = str(exc_info.value)
    assert "JSON array" in msg or "NDJSON" in msg
    assert "line 1" in msg


def test_render_ndjson_non_object_line_gives_clear_error(tmp_path):
    """An NDJSON line that is not a JSON object → clear error naming the type."""
    from starboard_skills.helpers.contract import ArgError

    bad = tmp_path / "bad.ndjson"
    bad.write_text('"hello"\n"world"\n')  # strings, not objects
    with pytest.raises(ArgError) as exc_info:
        cr.cmd_render(
            SimpleNamespace(
                kind="spend-by-product", data=str(bad),
                out=str(tmp_path / "o.png"), format="png",
            )
        )
    msg = str(exc_info.value)
    assert "str" in msg or "object" in msg.lower()


def test_render_non_list_json_names_expected_shapes(tmp_path):
    """A JSON file that parses but is not an array → error names both expected shapes."""
    from starboard_skills.helpers.contract import ArgError

    single_obj = tmp_path / "obj.json"
    single_obj.write_text(json.dumps({"billing_origin_product": "JOBS", "total_dbus": 1}))
    with pytest.raises(ArgError) as exc_info:
        cr.cmd_render(
            SimpleNamespace(
                kind="spend-by-product", data=str(single_obj),
                out=str(tmp_path / "o.png"), format="png",
            )
        )
    msg = str(exc_info.value)
    assert "JSON array" in msg and "NDJSON" in msg


def test_helper_charts_render_help_lists_required_fields_per_kind(capsys):
    """F23: `starboard-helper charts render --help` shows per-kind required columns."""
    import pytest
    from starboard_skills.helpers.__main__ import build_parser
    from starboard_x.charts import CHART_KINDS, REQUIRED_FIELDS

    with pytest.raises(SystemExit):
        build_parser().parse_args(["charts", "render", "--help"])
    out = capsys.readouterr().out
    assert "Required input columns per chart kind" in out
    for kind in CHART_KINDS:
        assert kind in out
        for field in REQUIRED_FIELDS[kind]:
            assert field in out
