# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Phase-2 skill text: the Drive-backed run lifecycle is reachable from prompts (P2-G11).

The skill text is the only interface the host agent sees, so the usual drift failure is prose that
names a flag or subcommand the code no longer has. D-28: this test builds every CLI parser
in-process (no subprocess, no ``--help`` scraping) and checks each command written in the skill
text against it. It also guards the phase-2 lifecycle rules: no ``engagement upload`` and no
advisory warning anywhere, ``--run-folder`` on every Drive-form writer, the publication order
``commit → report → approve → deliver | receipt`` and both storage
modes (Drive run folder vs local run dir).

``command_flag_errors`` / ``iter_commands`` are imported by the internal overlay test too, so keep
them free of starboard-skills-only paths.
"""

from __future__ import annotations

import argparse
import contextlib
import importlib
import re
from collections.abc import Iterator
from functools import cache
from pathlib import Path

import pytest
import yaml

_PKG = Path(__file__).parents[1]
_SKILLS = _PKG / "skills" / "starboard"
_AGENTS = _PKG / "agents"
_SCAFFOLD = _SKILLS / "starboard-engagement"
_ENGAGEMENT = _SCAFFOLD / "SKILL.md"
_CAPABILITY_BIND = _SCAFFOLD / "references" / "capability-bind.md"
_DELIVER = _SKILLS / "starboard-deliver" / "SKILL.md"
_DISCOVERY = _SKILLS / "starboard-discovery" / "SKILL.md"
_FOCUSED = tuple(
    _SKILLS / f"starboard-{n}" / "SKILL.md"
    for n in (
        "analyze",
        "cluster",
        "diagnostic",
        "finops",
        "job",
        "query",
        "uc",
        "warehouse",
        "workload-review",
    )
)
_SCHEDULED = (
    _AGENTS / "starboard-workload-review-auto.yaml",
    _AGENTS / "starboard-cluster-monitor.yaml",
)
# Every prompt surface that sets a run up on its own (owner rule 5: all of them change at once).
#: The phase-4 task entry skills set up their own run like the focused skills.
_TASK_ENTRY = tuple(
    _SKILLS / f"starboard-{n}" / "SKILL.md" for n in ("health-review", "troubleshoot")
)
_STANDALONE = (_DISCOVERY, *_FOCUSED, *_TASK_ENTRY, *_SCHEDULED)
_SKILL_MDS = tuple(sorted(_SKILLS.rglob("*.md")))
_AGENT_YAMLS = tuple(sorted(_AGENTS.glob("*.yaml")))


def _text(path: Path) -> str:
    """Prompt text of a skill file, or the rendered ``body`` (+ description) of an agent YAML."""
    raw = path.read_text(encoding="utf-8")
    if path.suffix == ".yaml":
        data = yaml.safe_load(raw)
        return f"{data.get('description', '')}\n{data.get('body', '')}"
    return raw


def _flat(text: str) -> str:
    return " ".join(text.split())


def _label(path: Path) -> str:
    return path.stem if path.suffix == ".yaml" else f"{path.parent.name}/{path.name}"


# --------------------------------------------------------------------------------------------
# In-process parsers (D-28)
# --------------------------------------------------------------------------------------------


class _Captured(Exception):
    def __init__(self, parser: argparse.ArgumentParser) -> None:
        self.parser = parser


@contextlib.contextmanager
def _capture_parse_args() -> Iterator[None]:
    """Make ``ArgumentParser.parse_args`` raise with the parser, for CLIs that build it in main()."""
    original = argparse.ArgumentParser.parse_args

    def _raise(self, *_a, **_k):  # type: ignore[no-untyped-def]
        raise _Captured(self)

    argparse.ArgumentParser.parse_args = _raise  # type: ignore[method-assign]
    try:
        yield
    finally:
        argparse.ArgumentParser.parse_args = original  # type: ignore[method-assign]


def _parser_from_main(module: str, attr: str = "main") -> argparse.ArgumentParser:
    fn = getattr(importlib.import_module(module), attr)
    with _capture_parse_args():
        try:
            fn([])
        except _Captured as exc:
            return exc.parser
    raise AssertionError(f"{module}.{attr} never called parse_args")


@cache
def parser_for(module: str) -> argparse.ArgumentParser | None:
    """The argparse parser behind ``python -m <module>`` (or a named Starboard CLI)."""
    if module == "starboard":
        return _parser_from_main("starboard.cli.cli.main", "parse_args")
    if module == "starboard review":
        return importlib.import_module("starboard.cli.cli.review_command")._build_parser()
    if module == "starboard auth":
        return importlib.import_module("starboard.cli.cli.auth_commands").build_parser()
    if module == "starboard-helper":
        return importlib.import_module("starboard_skills.helpers.__main__").build_parser()
    try:
        mod = importlib.import_module(f"{module}.__main__")
    except ModuleNotFoundError:
        mod = importlib.import_module(module)
    for attr in ("build_parser", "_build_parser"):
        if hasattr(mod, attr):
            return getattr(mod, attr)()
    return _parser_from_main(mod.__name__)


def _options(parser: argparse.ArgumentParser) -> set[str]:
    return {o for a in parser._actions for o in a.option_strings}


def _choices(parser: argparse.ArgumentParser) -> dict[str, tuple[str, ...]]:
    return {
        o: tuple(str(c) for c in a.choices)
        for a in parser._actions
        if a.choices and not isinstance(a, argparse._SubParsersAction)
        for o in a.option_strings
    }


def _subparsers(parser: argparse.ArgumentParser) -> dict[str, argparse.ArgumentParser]:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return dict(action.choices)
    return {}


# --------------------------------------------------------------------------------------------
# Command extraction
# --------------------------------------------------------------------------------------------

# A command start in prompt text. Group "py" is a ``python -m`` module, "sh" a bundled run.sh.
_COMMAND_START = re.compile(
    r"(?P<helper>(?<![\w./-])starboard-helper(?![\w-]))"
    r"|(?P<cli>(?<![\w./-])starboard(?=\s+(?:--|review\b|auth\b)))"
    r"|python3?\s+-m\s+(?P<py>(?:starboard_x|starboard_internal)\.[a-z_]+)"
    r"|(?P<sh>scripts/run\.sh)(?=\s)"
)
_FLAG = re.compile(r"(?<![\w-])(--[a-zA-Z][\w-]*)")
# A flag followed by a literal value (not a placeholder, variable, quote or alternative).
_FLAG_VALUE = re.compile(r"(?<![\w-])(--[a-zA-Z][\w-]*)[ =]([a-z][\w.-]*)(?![\w|>])")
_RUN_SH_TARGET = re.compile(r"^exec\s+(?:python\s+-m\s+(\S+)|starboard\s+(review))", re.MULTILINE)


def _segment(text: str, start: int) -> str:
    """The command text from ``start`` to the end of the shell command it begins.

    Stops at a backtick, an unescaped newline, a comment, or an unbracketed ``|``/``;``/``&``/``>``/
    ``)``. ``[--a | --b]`` alternatives, ``<a|b>`` placeholders and ``a\\|b`` table escapes stay
    inside the command.
    """
    depth = 0
    angle = 0  # inside a `<placeholder>`
    i = start
    while i < len(text):
        ch = text[i]
        if ch == "\\" and i + 1 < len(text):
            i += 2
            continue
        if ch in "`\n":
            break
        if ch == "<" and text[i + 1 : i + 2] not in ("", " ", "<") and text[i - 1] != "<":
            angle += 1
        elif ch == ">" and angle:
            angle -= 1
        elif ch in "[{":
            depth += 1
        elif ch in "]}":
            depth = max(0, depth - 1)
        elif (depth == 0 and not angle and ch in "|;&>)") or (ch == "#" and text[i - 1] in " \t"):
            break
        i += 1
    return text[start:i]


def _run_sh_module(source: Path) -> str | None:
    """``python -m`` target of the skill's bundled ``scripts/run.sh`` (None outside a skill).

    An agent YAML resolves through its ``skill_ref``.
    """
    if source.suffix == ".yaml":
        ref = yaml.safe_load(source.read_text(encoding="utf-8")).get("skill_ref")
        source = source.parents[1] / "skills" / "starboard" / str(ref) / "SKILL.md"
    for parent in source.parents:
        script = parent / "scripts" / "run.sh"
        if script.is_file():
            m = _RUN_SH_TARGET.search(script.read_text(encoding="utf-8"))
            if m:
                return m.group(1) or "starboard review"
            return None
    return None


def _subcommand_words(cli: str, words: list[str]) -> list[str]:
    """The leading ``words`` that are sub-command names (``engagement case open`` is three).

    Stops at the first leaf parser; an unknown word is kept so the flag check reports it.
    """
    node = parser_for(cli)
    out: list[str] = []
    for word in words:
        subs = _subparsers(node) if node is not None else {}
        if not subs:
            break
        out.append(word)
        node = subs.get(word)
        if node is None:
            break
    return out


def iter_commands(source: Path, text: str) -> Iterator[tuple[str, list[str], str]]:
    """Yield ``(cli, words, segment)`` for each Starboard command written in ``text``.

    ``cli`` keys :func:`parser_for`; ``words`` are the positional words after the program (the
    helper's ``<domain> <sub>``, a ``python -m`` subcommand, ``review`` / ``auth``).
    """
    for m in _COMMAND_START.finditer(text):
        seg = _segment(text, m.end())
        words: list[str] = []
        for tok in seg.replace("\\\n", " ").split():
            if tok.startswith(("-", "<", "$", '"', "'")) or not re.fullmatch(r"[a-z][a-z-]*", tok):
                break
            words.append(tok)
        if m.group("helper"):
            yield "starboard-helper", _subcommand_words("starboard-helper", words), seg
        elif m.group("cli"):
            head = words[:1]
            if head and head[0] in ("review", "auth"):
                yield f"starboard {head[0]}", words[1:2], seg
            else:
                yield "starboard", [], seg
        elif m.group("py"):
            yield m.group("py"), words[:1], seg
        elif m.group("sh"):
            target = _run_sh_module(source)
            if target is None:
                continue
            if target == "starboard review":
                yield "starboard review", [], seg
            else:
                yield target, words[:1], seg


@cache
def _helper_fetch_domains() -> frozenset[str]:
    """The helper domains whose argv carries ``--run-folder`` / ``--stdout`` (any position)."""
    return frozenset(importlib.import_module("starboard_skills.helpers.__main__")._FETCH_DOMAINS)


def command_flag_errors(source: Path, text: str) -> list[str]:
    """Every subcommand/flag in a Starboard command that the real parser does not define."""
    errors: list[str] = []
    for cli, words, seg in iter_commands(source, text):
        parser = parser_for(cli)
        if parser is None:
            continue
        allowed = set(_options(parser))
        choices = dict(_choices(parser))
        if cli == "starboard-helper" and words and words[0] in _helper_fetch_domains():
            # `__main__._extract_run_flags` takes these from anywhere in a fetch command's argv.
            allowed |= {"--run-folder", "--stdout"}
        node = parser
        for word in words:
            subs = _subparsers(node)
            if not subs:
                break
            if word not in subs:
                errors.append(f"{cli} {' '.join(words)}: no subcommand {word!r}")
                node = None  # type: ignore[assignment]
                break
            node = subs[word]
            allowed |= _options(node)
            choices.update(_choices(node))
        if node is None:
            continue
        if _subparsers(node) and cli != "starboard":
            # Placeholder or prose (`starboard-helper <domain> <verb>`): nothing to check.
            continue
        for flag in _FLAG.findall(seg):
            flag = flag.split("=", 1)[0]
            if flag.endswith("-"):
                continue  # a prose wildcard such as `--internal-*`
            if flag not in allowed:
                errors.append(f"{cli} {' '.join(words)}: unknown flag {flag} in {seg.strip()!r}")
        for flag, value in _FLAG_VALUE.findall(seg):
            if flag in choices and value not in choices[flag]:
                errors.append(
                    f"{cli} {' '.join(words)}: {flag} {value!r} is not one of {choices[flag]}"
                )
    return errors


# --------------------------------------------------------------------------------------------
# D-28: every command and flag in the skill text exists
# --------------------------------------------------------------------------------------------


@pytest.mark.unit
class TestEveryNamedFlagExists:
    @pytest.mark.parametrize("path", [*_SKILL_MDS, *_AGENT_YAMLS], ids=_label)
    def test_commands_match_the_real_parsers(self, path: Path) -> None:
        errors = command_flag_errors(path, _text(path))
        assert not errors, "\n".join(errors)

    def test_extractor_sees_the_lifecycle_commands(self) -> None:
        # Guard the guard: the extractor must actually find the engagement commands.
        seen = {
            " ".join(words)
            for cli, words, _ in iter_commands(_ENGAGEMENT, _text(_ENGAGEMENT))
            if cli == "starboard-helper"
        }
        for sub in ("preflight", "verify-identity", "route", "commit", "put", "report", "deliver"):
            assert f"engagement {sub}" in seen, sorted(seen)

    def test_extractor_flags_an_unknown_flag(self) -> None:
        bogus = "`starboard-helper engagement preflight --no-such-flag`"
        assert command_flag_errors(_ENGAGEMENT, bogus)
        assert command_flag_errors(_ENGAGEMENT, "`starboard-helper engagement no-such-sub --x`")
        assert command_flag_errors(_ENGAGEMENT, "`starboard review --no-such-flag`")

    def test_extractor_flags_a_value_outside_the_choices(self) -> None:
        bogus = "`starboard-helper engagement preflight --task review --source-mode bogus_mode`"
        assert command_flag_errors(_ENGAGEMENT, bogus)
        ok = "`starboard-helper engagement preflight --task review --source-mode <mode>`"
        assert not command_flag_errors(_ENGAGEMENT, ok)

    def test_a_heredoc_does_not_swallow_the_piped_command(self) -> None:
        text = "validate --key k <<'EOF' \\\n  | starboard-helper engagement route --run-id r\nEOF\n"
        segs = [seg for _, _, seg in iter_commands(_ENGAGEMENT, "python -m starboard_internal.ticket " + text)]
        assert any(seg.strip().startswith("engagement route") for seg in segs), segs


# --------------------------------------------------------------------------------------------
# Removed phase-1 surface
# --------------------------------------------------------------------------------------------

_REMOVED = (
    re.compile(r"engagement\s+upload\b"),
    re.compile(r"advisory[_ ]warning", re.IGNORECASE),
    re.compile(r"preflight\s+--resume\s+<"),
    re.compile(r"--preflight\s+<"),
    re.compile(r"drive-upload\.json"),
)


@pytest.mark.unit
class TestPhaseOneSurfaceIsGone:
    @pytest.mark.parametrize("path", [*_SKILL_MDS, *_AGENT_YAMLS], ids=_label)
    def test_no_upload_no_advisory(self, path: Path) -> None:
        body = _text(path)
        for pat in _REMOVED:
            assert not pat.search(body), f"{_label(path)} still names {pat.pattern!r}"


# --------------------------------------------------------------------------------------------
# --run-folder on every Drive-form writer; both storage modes taught
# --------------------------------------------------------------------------------------------

# Writers (spec P2-G3): every command that writes run output or reads a run input path.
_WRITERS = {
    ("starboard", ""),
    ("starboard review", ""),
    ("starboard_x.discovery", "run"),
    ("starboard-helper", "verify run"),
    ("starboard-helper", "notebook render"),
    ("starboard-helper", "charts render"),
    ("starboard-helper", "run check"),
    ("starboard-helper", "run recur"),
    ("starboard_internal.sanitize", ""),
}
_OUTPUT_FLAGS = re.compile(
    r"--(?:out|out-dir|output-path|manifest-out|backlog|from-discovery|since|data)[ =]+(\S+)"
)
_LOCAL_ROOT = re.compile(r"""^["']?(?:<run-dir>|<data\.local_run_dir>|\$\{?RUN_DIR\b|<case-root>)""")


def _writer_calls(path: Path) -> list[str]:
    calls = []
    for cli, words, seg in iter_commands(path, _text(path)):
        key = (cli, " ".join(words))
        if key not in _WRITERS:
            continue
        if cli == "starboard" and "--discover" not in seg and "--output-path" not in seg:
            continue
        calls.append(seg.replace("\\\n", " "))
    return calls


def _drive_form_errors(call: str) -> list[str]:
    """A writer is either the Drive form (``--run-folder`` + relpaths) or the local form."""
    paths = _OUTPUT_FLAGS.findall(call)
    if "--run-folder" in call:
        bad = [p for p in paths if _LOCAL_ROOT.match(p) or p.startswith(("/", "~", "./"))]
        return [f"Drive-form writer with a local path {bad}: {call.strip()!r}"] if bad else []
    # Local form: a path is rooted (``<run-dir>/…``, ``$RUN_DIR``, absolute) or a whole placeholder.
    bad = [p for p in paths if re.match(r"[\w.]", p) and not p.startswith("drive:")]
    if bad:
        return [f"writer with relpaths {bad} but no --run-folder: {call.strip()!r}"]
    return []


@pytest.mark.unit
class TestWritersCarryTheRunFolder:
    @pytest.mark.parametrize("path", [*_SKILL_MDS, *_AGENT_YAMLS], ids=_label)
    def test_writer_is_drive_form_or_explicitly_local(self, path: Path) -> None:
        errors = [e for call in _writer_calls(path) for e in _drive_form_errors(call)]
        assert not errors, "\n".join(errors)

    def test_scaffold_beats_use_the_run_folder(self) -> None:
        calls = _writer_calls(_ENGAGEMENT)
        drive = [c for c in calls if "--run-folder" in c]
        # discovery, review, verify, notebook, charts, run check and run recur all appear Drive-form
        for needle in (
            "--discover",
            "--from-discovery",
            "verify run",
            "notebook render",
            "charts render",
            "run check",
            "run recur",
        ):
            hits = [c for c in drive if needle in c]
            assert hits, f"engagement scaffold has no Drive-form `{needle}` writer"

    @pytest.mark.parametrize("path", [_ENGAGEMENT, *_STANDALONE], ids=_label)
    def test_both_storage_modes_are_taught(self, path: Path) -> None:
        body = _flat(_text(path))
        assert "--run-folder" in body, f"{_label(path)} never names --run-folder"
        assert "local_run_dir" in body, f"{_label(path)} never names the local run dir"
        assert "storage_decision" in body, f"{_label(path)} never reads storage_decision"


# --------------------------------------------------------------------------------------------
# Run setup: preflight → verify-identity → route, before the first read; resume by run ID
# --------------------------------------------------------------------------------------------

_ALL_SUBCOMMANDS = (
    "preflight",
    "verify-identity",
    "route",
    "status",
    "commit",
    "put",
    "read",
    "history",
    "report",
    "approve",
    "deliver",
    "receipt",
    "import-local",
    "rebuild-index",
)


@pytest.mark.unit
class TestRunSetup:
    def test_scaffold_names_every_engagement_subcommand(self) -> None:
        body = _text(_ENGAGEMENT)
        for sub in _ALL_SUBCOMMANDS:
            assert f"starboard-helper engagement {sub}" in body, f"scaffold never runs `{sub}`"

    @pytest.mark.parametrize("path", [_ENGAGEMENT, *_STANDALONE], ids=_label)
    def test_setup_order(self, path: Path) -> None:
        body = _text(path)
        pre = body.index("starboard-helper engagement preflight")
        vid = body.index("starboard-helper engagement verify-identity")
        route = body.index("starboard-helper engagement route")
        assert pre < vid < route, _label(path)

    @pytest.mark.parametrize("path", [_ENGAGEMENT, *_STANDALONE], ids=_label)
    def test_setup_passes_the_run_id(self, path: Path) -> None:
        body = _text(path)
        for sub in ("verify-identity", "route"):
            start = body.index(f"starboard-helper engagement {sub}")
            assert "--run-id" in _segment(body, start), f"{_label(path)}: {sub} without --run-id"

    def test_resume_is_by_run_id(self) -> None:
        body = _flat(_text(_ENGAGEMENT))
        assert "--resume-run-id" in body
        assert "starboard-helper engagement status" in body
        assert "quarantined" in body

    @pytest.mark.parametrize("path", [_ENGAGEMENT, *_STANDALONE], ids=_label)
    def test_no_certified_host_gate(self, path: Path) -> None:
        body = _flat(_text(path))
        for gone in ("HOST_NOT_CERTIFIED", "CERTIFIED_HOST", "customer leg is unavailable"):
            assert gone not in body, f"{_label(path)} still names {gone!r}"

    def test_scaffold_names_the_covered_refusals(self) -> None:
        body = _flat(_text(_ENGAGEMENT))
        for token in (
            "LOCAL_STORAGE_REFUSED",
            "--stdout",
            "--log-file",
            "--session",
            "--authorization",
            "drive:<object_id>",
        ):
            assert token in body, f"scaffold never names {token}"
        assert "nothing is written locally" in body

    def test_one_task_per_run_is_kept(self) -> None:
        body = _text(_ENGAGEMENT)
        assert "One task per run" in body
        assert "before the first workspace read" in _flat(body)


# --------------------------------------------------------------------------------------------
# Publication: commit → report → approve → deliver | receipt; only receipts complete a run
# --------------------------------------------------------------------------------------------


@pytest.mark.unit
class TestPublicationOrder:
    @pytest.mark.parametrize("path", [_ENGAGEMENT, _CAPABILITY_BIND, _DELIVER], ids=_label)
    def test_order(self, path: Path) -> None:
        body = _text(path)
        idx = {
            sub: body.find(f"starboard-helper engagement {sub}")
            for sub in ("commit", "report", "approve", "deliver", "receipt")
        }
        missing = [s for s, i in idx.items() if i < 0]
        assert not missing, f"{_label(path)} never runs {missing}"
        assert idx["commit"] < idx["report"] < idx["approve"] < idx["deliver"], idx
        assert idx["approve"] < idx["receipt"], idx

    @pytest.mark.parametrize("path", [_ENGAGEMENT, _CAPABILITY_BIND, _DELIVER], ids=_label)
    def test_receipts_complete_the_run(self, path: Path) -> None:
        body = _flat(_text(path))
        assert "only a verified receipt completes" in body.lower(), _label(path)
        assert "slack receipt never completes" in body.lower(), _label(path)
        assert "can_approve" in body, _label(path)

    def test_recurrence_uses_the_registry(self) -> None:
        body = _flat(_text(_ENGAGEMENT))
        assert "starboard-helper engagement history" in body
        assert "run recur --run-folder" in body
        assert "history_unavailable" in body

    def test_internal_only_local_bridge(self) -> None:
        body = _flat(_text(_ENGAGEMENT))
        assert "--storage local" in body
        assert "starboard-helper engagement import-local" in body
        assert "--confirm" in body


# --------------------------------------------------------------------------------------------
# Host-authored run artifacts reach the run through `engagement put` (never a host Drive tool)
# --------------------------------------------------------------------------------------------

# A Drive-run instruction that has the host create a run artifact with its own Drive tool.
HOST_DRIVE_TOOL = re.compile(
    r"(?:run folder|run's folder)[^.`]{0,40}with the host's (?:google )?drive tool"
    r"|with the host's (?:google )?drive tool[^.`]{0,40}(?:run folder|parent: the run)"
    r"|(?:create|write)s? [^.`]{0,80}with the host's (?:google )?drive tool",
    re.IGNORECASE,
)
PUT = "starboard-helper engagement put --run-folder $RUN_FOLDER --path "


# A README put whose heredoc placeholder carries the ## Delivery lines (filled after deliver).
POST_DELIVERY_README_PUT = re.compile(re.escape(PUT + "README.md") + r" <<'EOF' <[^>]*## Delivery[^>]*>")
CHECK_COMMIT = "starboard-helper engagement commit --run-folder $RUN_FOLDER --stage check"
# A read → edit → put-back instruction (an excerpt put back would replace the whole file).
READ_THEN_PUT_BACK = re.compile(
    r"put (?:it|the (?:whole |finished )?(?:file|narrative)) back|put back", re.IGNORECASE
)


def put_index(body: str, relpath: str) -> int:
    """Index of the `engagement put` of ``relpath`` (``-1`` when absent)."""
    return body.find(PUT + relpath)


@pytest.mark.unit
class TestHostArtifactsArePut:
    @pytest.mark.parametrize("path", [*_SKILL_MDS, *_AGENT_YAMLS], ids=_label)
    def test_no_run_artifact_is_created_with_a_host_drive_tool(self, path: Path) -> None:
        hits = HOST_DRIVE_TOOL.findall(_flat(_text(path)))
        assert not hits, f"{_label(path)} has the host write run artifacts itself: {hits}"

    def test_the_guard_catches_the_old_wording(self) -> None:
        old = "create `README.md` in the run folder with the host's Google Drive tool"
        assert HOST_DRIVE_TOOL.search(old)
        assert not HOST_DRIVE_TOOL.search("build the Google Doc with the host's Docs tool")

    @pytest.mark.parametrize("path", [_ENGAGEMENT, *_STANDALONE], ids=_label)
    def test_the_readme_is_put_before_the_analysis_commit(self, path: Path) -> None:
        body = _flat(_text(path))
        put = put_index(body, "README.md")
        assert put >= 0, f"{_label(path)} never puts README.md"
        commit = body.find(
            "starboard-helper engagement commit --run-folder $RUN_FOLDER --stage analysis", put
        )
        assert commit > put, f"{_label(path)}: no analysis commit after the README put"

    def test_discovery_puts_its_host_files(self) -> None:
        body = _flat(_text(_DISCOVERY))
        for rel in ("discovery/plan.json", "discovery/domains/<domain>.md", "discovery/analysis.md"):
            assert put_index(body, rel) >= 0, f"discovery never puts {rel}"

    def test_backlog_is_put_before_notebooks_and_run_check(self) -> None:
        body = _flat(_text(_ENGAGEMENT))
        put = put_index(body, "analysis/backlog.json")
        assert put >= 0, "the engagement scaffold never puts analysis/backlog.json"
        for cmd in (
            "starboard-helper notebook render --run-folder $RUN_FOLDER",
            "starboard-helper run check --run-folder $RUN_FOLDER",
        ):
            later = body.find(cmd, put)
            assert later > put, f"{cmd} is not after the backlog put"

    @pytest.mark.parametrize("path", [*_SKILL_MDS, *_AGENT_YAMLS], ids=_label)
    def test_every_post_delivery_readme_put_recommits_the_check_stage(self, path: Path) -> None:
        body = _flat(_text(path))
        for hit in POST_DELIVERY_README_PUT.finditer(body):
            after = body[hit.end() : hit.end() + 200]
            assert CHECK_COMMIT in after, (
                f"{_label(path)}: a post-delivery README put is not followed by `{CHECK_COMMIT}`"
            )

    @pytest.mark.parametrize(
        "path",
        [
            _ENGAGEMENT,
            _SKILLS / "starboard-action-plan" / "SKILL.md",
            _DELIVER,
            _AGENTS / "starboard-workload-review-auto.yaml",
        ],
        ids=_label,
    )
    def test_readme_delivery_lines_are_put_and_recommitted(self, path: Path) -> None:
        assert POST_DELIVERY_README_PUT.search(_flat(_text(path))), (
            f"{_label(path)} never puts the README with its ## Delivery lines"
        )

    @pytest.mark.parametrize("path", [*_SKILL_MDS, *_AGENT_YAMLS], ids=_label)
    def test_every_read_then_put_back_checks_truncated(self, path: Path) -> None:
        body = _flat(_text(path))
        for hit in READ_THEN_PUT_BACK.finditer(body):
            window = body[max(0, hit.start() - 400) : hit.end() + 400]
            assert "`truncated`" in window, (
                f"{_label(path)}: {hit.group(0)!r} without the `truncated` check"
            )

    def test_the_truncated_rule_is_reachable(self) -> None:
        hits = sum(
            len(READ_THEN_PUT_BACK.findall(_flat(_text(p)))) for p in (*_SKILL_MDS, *_AGENT_YAMLS)
        )
        assert hits >= 4
        assert not READ_THEN_PUT_BACK.search("put the README into the run folder")

    def test_put_reads_stdin(self) -> None:
        body = _flat(_text(_ENGAGEMENT))
        assert "<<'EOF'" in body and "stdin" in body


# --------------------------------------------------------------------------------------------
# Governance red-lines in public prompt text
# --------------------------------------------------------------------------------------------

_INTERNAL_TOKENS = re.compile(
    r"centralized_system_tables|fin_live_gold|logfood|dbr-doctor|logs-summariser|gtm_|eng_"
    r"|clickhouse|hmr_stack_hash",
    re.IGNORECASE,
)


@pytest.mark.unit
class TestPublicTextHygiene:
    @pytest.mark.parametrize("path", [*_SKILL_MDS, *_AGENT_YAMLS], ids=_label)
    def test_no_internal_namespace(self, path: Path) -> None:
        hits = sorted(set(_INTERNAL_TOKENS.findall(_text(path))))
        assert not hits, f"{_label(path)} names internal tokens {hits}"

    @pytest.mark.parametrize("path", [*_SKILL_MDS, *_AGENT_YAMLS], ids=_label)
    def test_never_auto_selects_a_profile(self, path: Path) -> None:
        body = _flat(_text(path)).lower()
        assert "default profile" not in body, f"{_label(path)} falls back to a default profile"
        assert "pick the first profile" not in body, _label(path)
        assert not re.search(r"(?<!never )auto-select a (?:databricks )?profile\b", body)


# --------------------------------------------------------------------------------------------
# Exit 7: every helper skill that writes to a run folder documents the storage-failure exit
# --------------------------------------------------------------------------------------------

_EXIT_SECTION_RE = re.compile(r"^## Exit codes[^\n]*\n(.*?)(?=^## |\Z)", re.MULTILINE | re.DOTALL)
_EXIT_7_RE = re.compile(r"^- `?7`?\b[^\n]*--run-folder[^\n]*BLOCKED_ACCESS", re.MULTILINE)
_RUN_FOLDER_EXIT_SKILLS = tuple(
    p
    for p in sorted(_SKILLS.rglob("SKILL.md"))
    if "--run-folder" in _text(p) and _EXIT_SECTION_RE.search(_text(p))
)


@pytest.mark.unit
class TestExit7Documented:
    def test_the_helper_skills_are_covered(self) -> None:
        names = {p.parent.name for p in _RUN_FOLDER_EXIT_SKILLS}
        assert {f"starboard-{n}" for n in (
            "uc", "job", "query", "warehouse", "cluster", "finops", "diagnostic",
            "workload-review", "discovery",
        )} <= names, names

    @pytest.mark.parametrize("path", _RUN_FOLDER_EXIT_SKILLS, ids=_label)
    def test_exit_codes_list_the_storage_failure(self, path: Path) -> None:
        section = _EXIT_SECTION_RE.search(_text(path))
        assert section is not None
        assert _EXIT_7_RE.search(section.group(1)), (
            f"{_label(path)} documents --run-folder but its exit codes omit 7 (storage failure)"
        )
