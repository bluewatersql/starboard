# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for the runtime local-write guard (phase-2 spec P2-G1)."""

from __future__ import annotations

import contextvars
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from starboard_core.engagement import write_guard
from starboard_core.engagement.write_guard import (
    DATABRICKS_SDK_TOKEN_CACHE,
    GuardPolicy,
    LocalWriteRefused,
    active,
    default_policy,
    guarded,
    install,
    refused_events,
    refused_in_scope,
    sandbox_diff,
    sandbox_snapshot,
    spawned_executables,
)

NO_ALLOW = GuardPolicy(allow_prefixes=())


@pytest.fixture(autouse=True)
def _never_leave_guard_active() -> Iterator[None]:
    assert not active()
    yield
    assert not active(), "a test left the write guard active"


@pytest.fixture
def existing(tmp_path: Path) -> Path:
    target = tmp_path / "existing.txt"
    target.write_text("seed")
    return target


# --- inactive / reads ------------------------------------------------------------


def test_inactive_guard_is_a_no_op(tmp_path: Path) -> None:
    install()
    (tmp_path / "free.txt").write_text("ok")
    os.mkdir(tmp_path / "d")
    assert (tmp_path / "free.txt").read_text() == "ok"


def test_reads_pass_while_active(existing: Path) -> None:
    with guarded(NO_ALLOW):
        assert existing.read_text() == "seed"
        with open(existing, "rb") as fh:
            assert fh.read() == b"seed"
        fd = os.open(existing, os.O_RDONLY)
        os.close(fd)
        assert os.listdir(existing.parent)
        assert existing.exists()


# --- each write event is refused ------------------------------------------------------


def _open_modes() -> list[str]:
    return ["w", "wb", "a", "ab", "x", "r+", "rb+", "w+"]


@pytest.mark.parametrize("mode", _open_modes())
def test_write_mode_open_refused(existing: Path, mode: str) -> None:
    target = existing if "x" not in mode else existing.with_name("new.txt")
    with guarded(NO_ALLOW), pytest.raises(LocalWriteRefused) as info:
        open(target, mode)  # noqa: SIM115 - the open itself is under test
    assert info.value.event == "open"
    assert info.value.path == os.path.realpath(target)
    assert existing.read_text() == "seed"


@pytest.mark.parametrize(
    "flags",
    [
        os.O_WRONLY,
        os.O_RDWR,
        os.O_RDONLY | os.O_CREAT,
        os.O_RDONLY | os.O_APPEND,
        os.O_RDONLY | os.O_TRUNC,
    ],
)
def test_write_flag_os_open_refused(existing: Path, flags: int) -> None:
    with guarded(NO_ALLOW), pytest.raises(LocalWriteRefused):
        os.open(existing, flags)


def _cases(tmp: Path, existing: Path) -> dict[str, Callable[[], object]]:
    folder = tmp / "folder"
    return {
        "path.write_text": lambda: (tmp / "p.txt").write_text("x"),
        "path.touch": lambda: (tmp / "t.txt").touch(),
        "os.rename": lambda: os.rename(existing, tmp / "renamed"),
        "os.replace": lambda: os.replace(existing, tmp / "replaced"),
        "os.remove": lambda: os.remove(existing),
        "os.unlink": lambda: os.unlink(existing),
        "os.rmdir": lambda: os.rmdir(folder),
        "os.mkdir": lambda: os.mkdir(tmp / "new-dir"),
        "os.makedirs": lambda: os.makedirs(tmp / "a" / "b"),
        "os.symlink": lambda: os.symlink(existing, tmp / "sym"),
        "os.link": lambda: os.link(existing, tmp / "hard"),
        "os.truncate": lambda: os.truncate(existing, 0),
        "shutil.copyfile": lambda: shutil.copyfile(existing, tmp / "copy"),
        "shutil.copy": lambda: shutil.copy(existing, tmp / "copy2"),
        "shutil.move": lambda: shutil.move(existing, tmp / "moved"),
        "shutil.rmtree": lambda: shutil.rmtree(folder),
        "shutil.copytree": lambda: shutil.copytree(folder, tmp / "tree"),
        "tempfile.mkstemp": lambda: tempfile.mkstemp(dir=tmp),
        "tempfile.mkdtemp": lambda: tempfile.mkdtemp(dir=tmp),
        "tempfile.NamedTemporaryFile": lambda: tempfile.NamedTemporaryFile(dir=tmp),
        "sqlite3.connect": lambda: sqlite3.connect(tmp / "db.sqlite"),
        "sqlite3.connect-empty": lambda: sqlite3.connect(""),
        "os.chmod": lambda: os.chmod(existing, 0o600),
        "os.utime": lambda: os.utime(existing),
        "os.chown": lambda: os.chown(existing, os.getuid(), -1),
        "shutil.chown": lambda: shutil.chown(existing, user=os.getuid()),
        "shutil.copystat": lambda: shutil.copystat(existing, existing),
        "shutil.copymode": lambda: shutil.copymode(existing, existing),
        "path.chmod": lambda: existing.chmod(0o600),
    }


CASE_NAMES = sorted(_cases(Path("/unused"), Path("/unused/x")))


@pytest.mark.parametrize("case", CASE_NAMES)
def test_each_write_event_refused(tmp_path: Path, existing: Path, case: str) -> None:
    (tmp_path / "folder").mkdir()
    action = _cases(tmp_path, existing)[case]
    before = sandbox_snapshot([tmp_path])
    with guarded(NO_ALLOW), pytest.raises(LocalWriteRefused) as info:
        action()
    assert info.value.code == "LOCAL_STORAGE_REFUSED"
    assert isinstance(info.value, PermissionError)
    assert sandbox_diff(before, sandbox_snapshot([tmp_path])) == []


@pytest.mark.skipif(not hasattr(os, "setxattr"), reason="no os.setxattr here")
def test_xattr_writes_refused(existing: Path) -> None:
    with guarded(NO_ALLOW):
        with pytest.raises(LocalWriteRefused):
            os.setxattr(existing, "user.k", b"v")
        with pytest.raises(LocalWriteRefused):
            os.removexattr(existing, "user.k")


@pytest.mark.skipif(not hasattr(os, "chflags"), reason="no os.chflags here")
def test_chflags_refused(existing: Path) -> None:
    with guarded(NO_ALLOW), pytest.raises(LocalWriteRefused):
        os.chflags(existing, 0)


def test_sqlite_memory_allowed() -> None:
    with guarded(NO_ALLOW):
        conn = sqlite3.connect(":memory:")
        conn.execute("select 1")
        conn.close()


def test_refusal_is_recorded(existing: Path) -> None:
    with guarded(NO_ALLOW):
        with pytest.raises(LocalWriteRefused):
            existing.write_text("x")
        events = refused_events()
    assert events == (("open", os.path.realpath(existing)),)


def test_refused_events_reset_on_outermost_entry(existing: Path) -> None:
    with guarded(NO_ALLOW), pytest.raises(LocalWriteRefused):
        existing.write_text("x")
    with guarded(NO_ALLOW):
        assert refused_events() == ()


# --- allowlist --------------------------------------------------------------------------


def test_allow_prefix_permits_writes_beneath(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    policy = GuardPolicy(allow_prefixes=(str(cache),))
    with guarded(policy):
        os.makedirs(cache / "nested")
        (cache / "nested" / "token.json").write_text("{}")
        os.replace(cache / "nested" / "token.json", cache / "token.json")
    assert (cache / "token.json").read_text() == "{}"


def test_allow_prefix_permits_creating_its_ancestors_only_as_dirs(
    tmp_path: Path,
) -> None:
    cache = tmp_path / "home" / ".config" / "tool" / "oauth"
    policy = GuardPolicy(allow_prefixes=(str(cache),))
    with guarded(policy):
        os.makedirs(cache)
        with pytest.raises(LocalWriteRefused):
            (tmp_path / "home" / ".config" / "leak.json").write_text("x")
    assert cache.is_dir()


def test_allow_prefix_is_not_a_string_prefix(tmp_path: Path) -> None:
    policy = GuardPolicy(allow_prefixes=(str(tmp_path / "ok"),))
    with guarded(policy), pytest.raises(LocalWriteRefused):
        (tmp_path / "ok-sibling.txt").write_text("x")


def test_allow_prefix_dotdot_escape_refused(tmp_path: Path) -> None:
    (tmp_path / "ok").mkdir()
    policy = GuardPolicy(allow_prefixes=(str(tmp_path / "ok"),))
    with guarded(policy), pytest.raises(LocalWriteRefused):
        open(os.path.join(str(tmp_path / "ok"), "..", "out.txt"), "w")  # noqa: SIM115


def test_allow_prefix_symlink_escape_refused(tmp_path: Path) -> None:
    allowed = tmp_path / "ok"
    allowed.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (allowed / "link").symlink_to(outside)
    policy = GuardPolicy(allow_prefixes=(str(allowed),))
    with guarded(policy), pytest.raises(LocalWriteRefused):
        (allowed / "link" / "x.txt").write_text("x")


def test_rename_needs_both_ends_allowed(tmp_path: Path) -> None:
    allowed = tmp_path / "ok"
    allowed.mkdir()
    (allowed / "f").write_text("x")
    policy = GuardPolicy(allow_prefixes=(str(allowed),))
    with guarded(policy), pytest.raises(LocalWriteRefused):
        os.rename(allowed / "f", tmp_path / "out")


def test_prefixes_are_resolved_absolute(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    (tmp_path / "alias").symlink_to(real)
    policy = GuardPolicy(allow_prefixes=(str(tmp_path / "alias"),))
    assert policy.allow_prefixes == (os.path.realpath(real),)


@pytest.mark.parametrize("bad", ["", "relative/dir", "./x", "/"])
def test_relative_or_empty_prefix_rejected(bad: str) -> None:
    with pytest.raises(ValueError):
        GuardPolicy(allow_prefixes=(bad,))


def test_devices_allowed() -> None:
    with guarded(NO_ALLOW), open(os.devnull, "w") as fh:
        fh.write("discarded")


def test_inherited_fd_writes_allowed() -> None:
    # Writes to an already-open descriptor (pipes, stdout) are not new local files.
    read_fd, write_fd = os.pipe()
    try:
        with guarded(NO_ALLOW), open(write_fd, "wb", closefd=False) as fh:
            fh.write(b"x")
    finally:
        os.close(read_fd)
        os.close(write_fd)


# --- executables ------------------------------------------------------------------------


def test_subprocess_refused_unless_allowlisted() -> None:
    with guarded(NO_ALLOW), pytest.raises(LocalWriteRefused) as info:
        subprocess.run([sys.executable, "-c", "pass"], check=True)
    assert info.value.event == "subprocess.Popen"
    assert info.value.path == sys.executable


def test_allowlisted_executable_runs_and_is_recorded_by_name() -> None:
    name = os.path.basename(sys.executable)
    policy = GuardPolicy(allow_prefixes=(), allow_executables=(sys.executable,))
    with guarded(policy):
        out = subprocess.run(
            [sys.executable, "-c", "print('hi')"],
            check=True,
            capture_output=True,
        )
        assert spawned_executables() == (name,)
    assert out.stdout.strip() == b"hi"


def test_shell_is_refused_even_for_allowlisted_command() -> None:
    policy = GuardPolicy(allow_prefixes=(), allow_executables=("gcloud",))
    with guarded(policy), pytest.raises(LocalWriteRefused):
        subprocess.run("gcloud --version", shell=True, check=False)
    with guarded(policy), pytest.raises(LocalWriteRefused):
        os.system("gcloud --version")  # noqa: S605


def test_default_executables() -> None:
    assert GuardPolicy(allow_prefixes=()).allow_executables == ("gcloud", "databricks")


def _fake_cli(directory: Path, name: str) -> Path:
    """An executable shell script named ``name`` that prints its argv."""
    directory.mkdir(parents=True, exist_ok=True)
    script = directory / name
    script.write_text('#!/bin/sh\necho "$0 $*"\n')
    script.chmod(0o755)
    return script


@pytest.fixture
def cli_on_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Fake ``databricks`` and ``gcloud`` CLIs, the only entries on ``PATH``."""
    bin_dir = tmp_path / "bin"
    _fake_cli(bin_dir, "databricks")
    _fake_cli(bin_dir, "gcloud")
    monkeypatch.setenv("PATH", str(bin_dir))
    return bin_dir


def test_basename_lookalike_is_refused(cli_on_path: Path, tmp_path: Path) -> None:
    fake = _fake_cli(tmp_path / "x", "databricks")
    with guarded(GuardPolicy(allow_prefixes=())), pytest.raises(LocalWriteRefused):
        subprocess.run([str(fake), "auth", "token"], check=False)


def test_path_shadowing_after_arming_is_refused(
    cli_on_path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shadow = _fake_cli(tmp_path / "shadow", "databricks").parent
    with guarded(GuardPolicy(allow_prefixes=())):
        monkeypatch.setenv("PATH", f"{shadow}{os.pathsep}{cli_on_path}")
        with pytest.raises(LocalWriteRefused):
            subprocess.run(["databricks", "auth", "token"], check=False)


def test_unresolvable_allowlisted_name_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    fake = _fake_cli(tmp_path / "x", "gcloud")
    with guarded(GuardPolicy(allow_prefixes=())), pytest.raises(LocalWriteRefused):
        subprocess.run([str(fake), "auth", "print-access-token"], check=False)


@pytest.mark.parametrize(
    "argv",
    [
        ["databricks", "auth", "token", "--host", "https://h"],
        ["databricks", "auth", "token", "--profile", "p", "--force-refresh"],
        ["databricks", "version", "--output", "json"],
        ["gcloud", "auth", "print-access-token"],
        ["gcloud", "auth", "application-default", "print-access-token"],
    ],
)
def test_allowlisted_cli_subcommands_run(cli_on_path: Path, argv: list[str]) -> None:
    with guarded(GuardPolicy(allow_prefixes=())):
        out = subprocess.run(argv, check=True, capture_output=True, text=True)
        assert spawned_executables() == (argv[0],)
    assert out.stdout.split()[1:] == argv[1:]


@pytest.mark.parametrize(
    "argv",
    [
        ["databricks", "fs", "cp", "dbfs:/rows.csv", "/tmp/rows.csv"],
        ["databricks", "workspace", "export", "/Users/x/nb", "--file", "/tmp/nb"],
        ["databricks", "--profile", "p", "fs", "cp", "dbfs:/a", "/tmp/a"],
        ["databricks", "auth"],
        ["databricks"],
        ["gcloud", "storage", "cp", "gs://b/rows.csv", "/tmp/rows.csv"],
        ["gcloud", "auth", "login"],
    ],
)
def test_file_writing_cli_subcommands_refused(
    cli_on_path: Path, argv: list[str]
) -> None:
    with guarded(GuardPolicy(allow_prefixes=())), pytest.raises(LocalWriteRefused):
        subprocess.run(argv, check=False)


def test_executable_kwarg_is_the_program_checked(cli_on_path: Path) -> None:
    with guarded(GuardPolicy(allow_prefixes=())), pytest.raises(LocalWriteRefused):
        subprocess.run(
            ["databricks", "auth", "token"], executable=sys.executable, check=False
        )


def test_relative_allowlist_entry_rejected() -> None:
    with pytest.raises(ValueError):
        GuardPolicy(allow_prefixes=(), allow_executables=("bin/databricks",))


def test_sys_executable_is_not_allowlisted_by_default() -> None:
    with guarded(default_policy()), pytest.raises(LocalWriteRefused):
        subprocess.run([sys.executable, "-c", "pass"], check=False)


# --- process creation that bypasses subprocess.Popen -----------------------------------


def _child() -> None:  # pragma: no cover - runs in a child process if it ever starts
    Path(os.environ.get("TMPDIR", "/tmp"), "child-ran").write_text("x")


@pytest.mark.parametrize("method", ["spawn", "fork", "forkserver"])
def test_multiprocessing_start_refused(method: str, tmp_path: Path) -> None:
    import multiprocessing

    if method not in multiprocessing.get_all_start_methods():
        pytest.skip(f"{method} start method unavailable")
    ctx = multiprocessing.get_context(method)
    process = ctx.Process(target=_child)
    with guarded(NO_ALLOW), pytest.raises(LocalWriteRefused):
        process.start()


def test_os_fork_refused() -> None:
    if not hasattr(os, "fork"):
        pytest.skip("no os.fork")
    with guarded(NO_ALLOW), pytest.raises(LocalWriteRefused) as info:
        os.fork()
    assert info.value.event == "os.fork"


def test_os_forkpty_refused() -> None:
    if not hasattr(os, "forkpty"):
        pytest.skip("no os.forkpty")
    with guarded(NO_ALLOW), pytest.raises(LocalWriteRefused) as info:
        os.forkpty()
    assert info.value.event == "os.forkpty"


def test_posixsubprocess_fork_exec_refused_unless_allowlisted(
    cli_on_path: Path,
) -> None:
    import multiprocessing.util

    pytest.importorskip("_posixsubprocess")
    python = os.fsencode(sys.executable)  # multiprocessing passes bytes paths
    with guarded(NO_ALLOW), pytest.raises(LocalWriteRefused) as info:
        multiprocessing.util.spawnv_passfds(python, [python], ())
    assert info.value.event == "_posixsubprocess.fork_exec"
    databricks = os.fsencode(cli_on_path / "databricks")
    with guarded(NO_ALLOW):
        pid = multiprocessing.util.spawnv_passfds(
            databricks, [databricks, "auth", "token"], ()
        )
        os.waitpid(pid, 0)
        with pytest.raises(LocalWriteRefused):
            multiprocessing.util.spawnv_passfds(
                databricks, [databricks, "fs", "cp", "a", "b"], ()
            )


def test_fork_exec_checks_only_the_first_existing_path_candidate(
    cli_on_path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A bare name is expanded to one candidate per PATH entry; missing ones are skipped."""
    import _posixsubprocess

    install()
    # Route subprocess through the wrapped fork_exec (it bound the C function at import).
    monkeypatch.setattr(subprocess, "_fork_exec", _posixsubprocess.fork_exec)
    missing = tmp_path / "missing-bin"
    shadow = _fake_cli(tmp_path / "shadow", "databricks").parent
    monkeypatch.setenv("PATH", os.pathsep.join([str(missing), str(cli_on_path)]))
    with guarded(NO_ALLOW):
        done = subprocess.run(["databricks", "version"], check=False)
        assert done.returncode == 0
        # The first existing candidate is the one checked: a shadow is refused.
        monkeypatch.setenv("PATH", os.pathsep.join([str(missing), str(shadow)]))
        with pytest.raises(LocalWriteRefused):
            subprocess.run(["databricks", "version"], check=False)


def test_fork_exec_with_no_existing_candidate_falls_through_to_enoent(
    tmp_path: Path,
) -> None:
    import multiprocessing.util

    pytest.importorskip("_posixsubprocess")
    nowhere = os.fsencode(tmp_path / "nowhere" / "prog")
    with guarded(NO_ALLOW):
        pid = multiprocessing.util.spawnv_passfds(nowhere, [nowhere], ())
    _, status = os.waitpid(pid, 0)
    assert os.waitstatus_to_exitcode(status) != 0  # exec failed in the child


def test_posix_spawn_checks_the_allowlist(cli_on_path: Path) -> None:
    if not hasattr(os, "posix_spawn"):
        pytest.skip("no os.posix_spawn")
    with guarded(NO_ALLOW):
        with pytest.raises(LocalWriteRefused):
            os.posix_spawn(sys.executable, [sys.executable, "-c", "pass"], {})
        with pytest.raises(LocalWriteRefused):
            os.posix_spawnp("databricks", ["databricks", "fs", "cp", "a", "b"], {})
        pid = os.posix_spawnp("databricks", ["databricks", "version"], dict(os.environ))
        os.waitpid(pid, 0)


# --- state handling ---------------------------------------------------------------------


def test_dont_write_bytecode_while_active() -> None:
    before = sys.dont_write_bytecode
    with guarded(NO_ALLOW):
        assert sys.dont_write_bytecode is True
        assert active()
    assert sys.dont_write_bytecode is before


def test_nested_contexts_restore(tmp_path: Path) -> None:
    inner_ok = tmp_path / "inner"
    inner_ok.mkdir()
    with guarded(NO_ALLOW):
        with guarded(GuardPolicy(allow_prefixes=(str(inner_ok),))):
            (inner_ok / "a.txt").write_text("x")
        assert active()
        with pytest.raises(LocalWriteRefused):
            (inner_ok / "b.txt").write_text("x")
    assert not active()
    (inner_ok / "c.txt").write_text("free again")


def test_exception_inside_guard_releases_it() -> None:
    with pytest.raises(RuntimeError), guarded(NO_ALLOW):
        raise RuntimeError("boom")
    assert not active()


def test_guard_covers_worker_threads(tmp_path: Path) -> None:
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            (tmp_path / "from-thread.txt").write_text("x")
        except BaseException as exc:  # noqa: BLE001 - captured for the assertion
            errors.append(exc)

    with guarded(NO_ALLOW):
        thread = threading.Thread(target=worker)
        thread.start()
        thread.join()
    assert len(errors) == 1
    assert isinstance(errors[0], LocalWriteRefused)
    assert not (tmp_path / "from-thread.txt").exists()


def test_late_write_from_an_exited_entry_fails_the_live_entry(tmp_path: Path) -> None:
    """A task started in entry A that writes after A exits (B armed) fails B."""
    with guarded(NO_ALLOW) as a:
        late = contextvars.copy_context()  # carries A's scope, like a task / thread
    assert late.run(write_guard._SCOPE.get) == (a,)
    with guarded(NO_ALLOW) as b:
        since = len(refused_events())
        with pytest.raises(LocalWriteRefused):
            late.run((tmp_path / "late.txt").write_text, "x")
        assert refused_in_scope(b, since) == (
            ("open", os.path.realpath(tmp_path / "late.txt")),
        )
    assert not (tmp_path / "late.txt").exists()


def test_refusal_keeps_only_live_scope_tokens(tmp_path: Path) -> None:
    with guarded(NO_ALLOW) as b:
        with guarded(NO_ALLOW) as a:
            pass
        ctx = contextvars.copy_context()
        ctx.run(write_guard._SCOPE.set, (a, b))
        since = len(refused_events())
        with pytest.raises(LocalWriteRefused):
            ctx.run((tmp_path / "x.txt").write_text, "x")
        assert len(refused_in_scope(b, since)) == 1
        assert write_guard._REFUSED_SCOPES[-1] == (b,)


def test_install_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    install()
    calls: list[object] = []
    monkeypatch.setattr(sys, "addaudithook", calls.append)
    install(NO_ALLOW)
    install()
    assert calls == []


def test_guarded_rejects_non_policy() -> None:
    with pytest.raises(TypeError), guarded("nope"):  # type: ignore[arg-type]
        pass


# --- default policy ---------------------------------------------------------------------


def test_default_policy_allows_only_the_sdk_token_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    policy = default_policy()
    expected = os.path.realpath(os.path.expanduser(DATABRICKS_SDK_TOKEN_CACHE))
    assert policy.allow_prefixes == ()
    assert [d for d, _ in policy.allow_files] == [expected]
    assert expected.startswith(os.path.realpath(tmp_path))
    assert policy.allow_executables == ("gcloud", "databricks")


def test_token_cache_allows_only_the_sdk_token_file_pattern(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    cache = Path(os.path.expanduser(DATABRICKS_SDK_TOKEN_CACHE))
    cache.mkdir(parents=True)
    (cache / "seed.json").write_text("{}")
    with guarded(default_policy()):
        for name in ("rows.json", "abc.json", "A" * 64 + ".json", "0" * 64 + ".csv"):
            with pytest.raises(LocalWriteRefused):
                (cache / name).write_text("[]")
        with pytest.raises(LocalWriteRefused):
            os.mkdir(cache / "sub")
        with pytest.raises(LocalWriteRefused):
            os.remove(cache / "seed.json")
        with pytest.raises(LocalWriteRefused):
            os.rename(cache / "seed.json", cache / ("1" * 64 + ".json"))
        with pytest.raises(LocalWriteRefused):
            os.chmod(cache / "seed.json", 0o600)
    assert sorted(p.name for p in cache.iterdir()) == ["seed.json"]


def test_allow_files_pattern_must_compile() -> None:
    with pytest.raises(ValueError):
        GuardPolicy(allow_prefixes=(), allow_files=(("/tmp/x", "("),))


def test_non_pathlike_target_is_refused() -> None:
    from starboard_core.engagement.write_guard import _check_path

    with guarded(NO_ALLOW), pytest.raises(LocalWriteRefused) as info:
        _check_path("open", object(), NO_ALLOW)
    assert info.value.path.startswith("<object object")


def test_default_policy_lets_the_sdk_token_cache_be_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mirror databricks-sdk ``TokenCache.save`` (makedirs, open "w", chmod)."""
    monkeypatch.setenv("HOME", str(tmp_path))
    policy = default_policy()
    target = os.path.expanduser(
        os.path.join(DATABRICKS_SDK_TOKEN_CACHE, "ab" * 32 + ".json")
    )
    with guarded(policy):
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w") as fh:
            fh.write('{"token": "t"}')
        os.chmod(target, 0o600)
        # Nothing else under HOME is writable: no customer bytes can go next to it.
        with pytest.raises(LocalWriteRefused):
            (tmp_path / ".config" / "rows.json").write_text("[]")
        with pytest.raises(LocalWriteRefused):
            (tmp_path / ".config" / "databricks-sdk-py" / "rows.json").write_text("[]")


# --- sandbox snapshot/diff --------------------------------------------------------------


def test_sandbox_diff_reports_created_deleted_and_modified(tmp_path: Path) -> None:
    (tmp_path / "keep.txt").write_text("a")
    (tmp_path / "gone.txt").write_text("b")
    (tmp_path / "edit.txt").write_text("c")
    before = sandbox_snapshot([tmp_path])
    (tmp_path / "gone.txt").unlink()
    (tmp_path / "edit.txt").write_text("cc")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "new.txt").write_text("d")
    after = sandbox_snapshot([tmp_path])
    diff = sandbox_diff(before, after)
    root = str(tmp_path)
    assert f"+ {root}/sub/new.txt" in diff
    assert f"+ {root}/sub" in diff
    assert f"- {root}/gone.txt" in diff
    assert f"~ {root}/edit.txt" in diff
    assert not any(line.endswith("keep.txt") for line in diff)
    assert diff == sorted(diff, key=lambda line: line[2:])


def test_sandbox_snapshot_unchanged_is_empty(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("a")
    assert (
        sandbox_diff(sandbox_snapshot([tmp_path]), sandbox_snapshot([tmp_path])) == []
    )


def test_sandbox_snapshot_missing_root_is_empty(tmp_path: Path) -> None:
    assert sandbox_snapshot([tmp_path / "absent"]) == {}


def test_sandbox_snapshot_does_not_follow_symlinks(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "x.txt").write_text("x")
    root = tmp_path / "root"
    root.mkdir()
    (root / "link").symlink_to(outside)
    snap = sandbox_snapshot([root])
    assert str(root / "link") in snap
    assert str(root / "link" / "x.txt") not in snap


def test_module_does_not_import_heavy_deps() -> None:
    assert write_guard.__name__ == "starboard_core.engagement.write_guard"
