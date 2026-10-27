# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Runtime local-write guard for covered runs.

On a covered run (``StoragePolicy.DRIVE_REQUIRED``) customer bytes must only reach the
run's Drive folder through the artifact sink. Code-path review cannot prove that every
library honours this, so the guard enforces it at runtime with a
:pep:`578` audit hook:

* While a guard is armed, any audited operation that would create, modify, rename,
  delete or change the metadata (``chmod``, ``chown``, ``utime``, ``chflags``, xattrs) of
  a local filesystem entry raises :class:`LocalWriteRefused`. The operation does not
  run. Reads are untouched.
* Child processes are refused unless the program resolves (``realpath``) to an
  allowlisted executable. Bare allowlist names (``gcloud`` / ``databricks`` by default)
  are resolved with :func:`shutil.which` on ``PATH`` when the guard is armed; absolute
  entries (``sys.executable`` included) must be named explicitly. A lookalike elsewhere
  (``/tmp/x/databricks``) or a ``PATH`` shadow added after arming is refused. Allowlisted
  CLIs may only run their allowlisted subcommands (``databricks auth token`` /
  ``databricks version``, ``gcloud auth print-access-token``), so a child cannot run a
  file-writing subcommand such as ``databricks fs cp``. ``os.system`` and
  ``shell=True`` always run ``/bin/sh`` and so are always refused.
* ``os.fork`` / ``os.forkpty`` are refused while armed: a forked child would run
  arbitrary code outside the guard. ``multiprocessing``'s ``spawn`` start method calls
  ``_posixsubprocess.fork_exec`` directly and raises no audit event, so :func:`install`
  wraps that function with the same executable check.
* ``sys.dont_write_bytecode`` is forced on while armed so imports do not drop ``.pyc``
  files.

Design notes:

* ``sys.addaudithook`` cannot be undone, so :func:`install` adds the hook once per
  process. With no guard armed the hook returns at the first check.
* The armed policy lives in a process-global, lock-protected stack rather than a
  ``ContextVar``. Worker threads (``threading.Thread``, ``ThreadPoolExecutor``) do not
  inherit context variables, so a context-local guard would silently miss writes made on
  a worker thread. A process-wide guard is the fail-closed choice. The innermost
  :func:`guarded` block's policy applies.
* Refusals are recorded process-wide, each tagged with the tokens of the
  :func:`guarded` entries in scope where it happened (a ``ContextVar``). A caller
  checking one entry (:func:`refused_in_scope`) sees only its own refusals, so a
  concurrent entry's refusal does not fail it. A refusal with no entry in scope (made
  on a worker thread that did not inherit the context) is untagged and counts against
  every entry: fail closed. Tokens of entries that have already exited are dropped
  when the refusal is recorded, so a late write from a task started inside an exited
  entry is untagged too.
* Paths are resolved with ``realpath`` before the allowlist check, so ``..`` and symlink
  escapes are refused. Writes through an already-open integer descriptor (pipes,
  stdout) are allowed: they create no new local file. A relative path paired with a
  ``dir_fd`` cannot be resolved without opening files from inside the hook, so it is
  refused.
* ``allow_files`` entries allow writes to one directory's direct children whose name
  fully matches a pattern. The default policy uses it for the databricks-sdk OAuth token
  cache: only ``<sha256-hex>.json`` there is writable, not arbitrary files.
* ``sqlite3.connect`` is allowed only for ``":memory:"``. URI databases are refused
  because the audit event does not say whether ``uri=True`` was passed.

Out of scope for the audit hook: native-code writers (Polars, pyarrow, other Rust/C
extensions) that write through raw ``open(2)`` without raising an audit event; operations
CPython raises no audit event for (``os.mkfifo``, ``os.mknod``); a ``multiprocessing``
fork server started before the guard was armed; and anything an allowlisted child CLI
writes itself (its own credential cache). The ``sandbox_snapshot`` / ``sandbox_diff``
helpers check the filesystem directly and cover these in the exit tests.
"""

from __future__ import annotations

import contextvars
import functools
import os
import re
import shutil
import sys
import threading
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field

__all__ = [
    "DATABRICKS_SDK_TOKEN_CACHE",
    "DATABRICKS_SDK_TOKEN_FILE",
    "GuardPolicy",
    "LocalWriteRefused",
    "active",
    "default_policy",
    "guarded",
    "install",
    "refused_events",
    "refused_in_scope",
    "sandbox_diff",
    "sandbox_snapshot",
    "spawned_executables",
]

#: Where databricks-sdk keeps its OAuth token cache (``TokenCache.BASE_PATH``).
#: ``TokenCache.save`` runs ``os.makedirs`` / ``open(..., "w")`` / ``os.chmod`` there
#: whenever a U2M token is refreshed. That happens mid-run on a covered run.
DATABRICKS_SDK_TOKEN_CACHE = "~/.config/databricks-sdk-py/oauth"

#: Name of a databricks-sdk token cache file (``TokenCache.filename``).
DATABRICKS_SDK_TOKEN_FILE = r"[0-9a-f]{64}\.json"

_DEFAULT_EXECUTABLES: tuple[str, ...] = ("gcloud", "databricks")
#: ``(executable, *argv-prefix)``: the only subcommands the default CLIs may run.
#: ``databricks auth token`` / ``databricks version`` are what databricks-sdk's CLI
#: credential provider runs; ``gcloud auth [application-default] print-access-token``
#: mints the Drive token. None of them takes an output-file argument.
_DEFAULT_COMMANDS: tuple[tuple[str, ...], ...] = (
    ("databricks", "auth", "token"),
    ("databricks", "version"),
    ("gcloud", "auth", "print-access-token"),
    ("gcloud", "auth", "application-default", "print-access-token"),
)
_DEFAULT_DEVICES: tuple[str, ...] = (
    "/dev/null",
    "/dev/stdout",
    "/dev/stderr",
    "/dev/tty",
)
_WRITE_FLAGS = (
    os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC | os.O_EXCL
)
_WRITE_MODE_CHARS = frozenset("wax+")


class LocalWriteRefused(PermissionError):
    """A local filesystem write or process spawn was refused on a covered run."""

    code = "LOCAL_STORAGE_REFUSED"

    def __init__(self, event: str, path: str) -> None:
        self.event = event
        self.path = path
        super().__init__(
            f"{self.code}: {event} on {path!r} refused; this run's artifacts must go "
            "through the run sink to Drive, not to local disk"
        )


@dataclass(frozen=True)
class GuardPolicy:
    """What a covered run may still touch locally.

    ``allow_prefixes`` are absolute directories; ``~`` is expanded and each is stored
    ``realpath``-resolved. Writes are allowed at or below a prefix.

    ``allow_files`` are ``(directory, pattern)`` pairs: a write is allowed to a direct
    child of ``directory`` whose name fully matches the regular expression ``pattern``.
    Nothing else in that directory is writable.

    ``os.mkdir`` is also allowed on a prefix's (or ``allow_files`` directory's)
    ancestors so the first ``makedirs`` succeeds. Nothing else in those ancestors is
    writable.

    ``allow_executables`` are bare names (resolved on ``PATH`` when the guard is armed)
    or absolute paths. ``allow_commands`` are ``(name, *argv-prefix)`` tuples keyed by
    the executable's basename: when a name has any entry, its ``argv[1:]`` must start
    with one of them. A name with no entry may run with any arguments.
    """

    allow_prefixes: tuple[str, ...]
    allow_executables: tuple[str, ...] = _DEFAULT_EXECUTABLES
    allow_devices: tuple[str, ...] = field(default=_DEFAULT_DEVICES)
    allow_files: tuple[tuple[str, str], ...] = ()
    allow_commands: tuple[tuple[str, ...], ...] = _DEFAULT_COMMANDS

    def __post_init__(self) -> None:
        resolved = tuple(_resolve_dir(p, "allow prefix") for p in self.allow_prefixes)
        object.__setattr__(self, "allow_prefixes", resolved)
        files: list[tuple[str, str]] = []
        for directory, pattern in self.allow_files:
            try:
                re.compile(pattern)
            except (re.error, TypeError) as exc:
                raise ValueError(
                    f"allow_files pattern is invalid: {pattern!r}"
                ) from exc
            files.append((_resolve_dir(directory, "allow_files directory"), pattern))
        object.__setattr__(self, "allow_files", tuple(files))
        executables = tuple(self.allow_executables)
        for name in executables:
            if not isinstance(name, str) or not name:
                raise ValueError("allow_executables entries must be non-empty strings")
            if os.sep in name and not os.path.isabs(name):
                raise ValueError(
                    f"allow_executables entry must be a bare name or absolute: {name!r}"
                )
        object.__setattr__(self, "allow_executables", executables)
        commands = tuple(tuple(c) for c in self.allow_commands)
        if any(not c or not all(isinstance(part, str) for part in c) for c in commands):
            raise ValueError("allow_commands entries must be non-empty string tuples")
        object.__setattr__(self, "allow_commands", commands)
        object.__setattr__(
            self,
            "allow_devices",
            tuple(os.path.normpath(d) for d in self.allow_devices),
        )


def _resolve_dir(prefix: object, label: str) -> str:
    if not isinstance(prefix, str) or not prefix:
        raise ValueError(f"{label} entries must be non-empty strings")
    expanded = os.path.expanduser(prefix)
    if not os.path.isabs(expanded):
        raise ValueError(f"{label} must be absolute: {prefix!r}")
    real = os.path.realpath(expanded)
    if real == os.path.dirname(real):
        raise ValueError(f"{label} must not be a filesystem root: {prefix!r}")
    return real


def default_policy() -> GuardPolicy:
    """The guard policy for covered runs.

    Allowlists only the databricks-sdk OAuth token cache files
    (:data:`DATABRICKS_SDK_TOKEN_FILE` directly under
    :data:`DATABRICKS_SDK_TOKEN_CACHE`). The SDK rewrites them on token refresh, and
    refusing that write would break authentication mid-run. They hold credentials, never
    customer data. ``HOME`` is read at call time.
    """
    return GuardPolicy(
        allow_prefixes=(),
        allow_files=((DATABRICKS_SDK_TOKEN_CACHE, DATABRICKS_SDK_TOKEN_FILE),),
    )


# --- process-global state -------------------------------------------------------------


@dataclass(frozen=True)
class _Armed:
    """An armed policy plus its executables resolved at arm time (realpath -> name)."""

    token: object
    policy: GuardPolicy
    executables: dict[str, str]


def _resolve_executables(policy: GuardPolicy) -> dict[str, str]:
    resolved: dict[str, str] = {}
    for entry in policy.allow_executables:
        found = entry if os.path.isabs(entry) else shutil.which(entry)
        if found:
            resolved.setdefault(os.path.realpath(found), os.path.basename(entry))
    return resolved


_LOCK = threading.Lock()
_ENTRIES: list[_Armed] = []
_REFUSED: list[tuple[str, str]] = []
#: The entry tokens in scope for each ``_REFUSED`` event (same index).
_REFUSED_SCOPES: list[tuple[object, ...]] = []
#: Tokens of the :func:`guarded` entries enclosing the current context.
_SCOPE: contextvars.ContextVar[tuple[object, ...]] = contextvars.ContextVar(
    "starboard_write_guard_scope", default=()
)
_SPAWNED: list[str] = []
_SAVED_BYTECODE: list[bool] = []
_LOCAL = threading.local()
_INSTALLED = False


def install(policy: GuardPolicy | None = None) -> None:
    """Add the audit hook (and wrap ``_posixsubprocess.fork_exec``) once. Idempotent.

    Installing does not arm anything: the hook is inert until :func:`guarded` is
    entered. ``policy`` is accepted to match the fixed interface and is type-checked
    only. Arming is always scoped through :func:`guarded`.
    """
    global _INSTALLED
    if policy is not None and not isinstance(policy, GuardPolicy):
        raise TypeError("policy must be a GuardPolicy")
    with _LOCK:
        if _INSTALLED:
            return
        sys.addaudithook(_hook)
        _wrap_fork_exec()
        _INSTALLED = True


def active() -> bool:
    """Whether a guard is currently armed (process-wide)."""
    return bool(_ENTRIES)


def refused_events() -> tuple[tuple[str, str], ...]:
    """``(event, path)`` pairs refused since the outermost guard was entered."""
    with _LOCK:
        return tuple(_REFUSED)


def refused_in_scope(token: object, since: int = 0) -> tuple[tuple[str, str], ...]:
    """Refusals after index ``since`` that count against the entry ``token``.

    That is every refusal made inside the entry (its token was in scope), plus every
    refusal made with no entry in scope at all (fail closed). ``since`` is a
    :func:`refused_events` count; ``token`` is what :func:`guarded` yields.
    """
    with _LOCK:
        return tuple(
            event
            for event, scope in zip(
                _REFUSED[since:], _REFUSED_SCOPES[since:], strict=True
            )
            if not scope or token in scope
        )


def spawned_executables() -> tuple[str, ...]:
    """Distinct allowlisted executable names spawned since the outermost entry."""
    with _LOCK:
        return tuple(_SPAWNED)


@contextmanager
def guarded(policy: GuardPolicy) -> Iterator[object]:
    """Arm ``policy`` for the duration of the block. Re-entrant; always disarms.

    Yields the entry's token (see :func:`refused_in_scope`).
    """
    if not isinstance(policy, GuardPolicy):
        raise TypeError("policy must be a GuardPolicy")
    install()
    token = object()
    armed = _Armed(token, policy, _resolve_executables(policy))
    with _LOCK:
        if not _ENTRIES:
            _REFUSED.clear()
            _REFUSED_SCOPES.clear()
            _SPAWNED.clear()
            _SAVED_BYTECODE.append(sys.dont_write_bytecode)
            sys.dont_write_bytecode = True
        _ENTRIES.append(armed)
    scope = _SCOPE.set((*_SCOPE.get(), token))
    try:
        yield token
    finally:
        with suppress(ValueError):  # exited from another context
            _SCOPE.reset(scope)
        with _LOCK:
            for index in range(len(_ENTRIES) - 1, -1, -1):
                if _ENTRIES[index].token is token:
                    del _ENTRIES[index]
                    break
            if not _ENTRIES and _SAVED_BYTECODE:
                sys.dont_write_bytecode = _SAVED_BYTECODE.pop()


# --- the hook -------------------------------------------------------------------------


def _hook(event: str, args: tuple[object, ...]) -> None:
    if not _ENTRIES:
        return
    handler = _HANDLERS.get(event)
    spawn = event in _SPAWN_EVENTS
    if (handler is None and not spawn) or getattr(_LOCAL, "busy", False):
        return
    entries = _ENTRIES
    if not entries:
        return
    armed = entries[-1]
    _LOCAL.busy = True
    try:
        if handler is not None:
            handler(event, args, armed.policy)
        else:
            _on_spawn(event, args, armed)
    finally:
        _LOCAL.busy = False


def _refuse(event: str, path: str) -> None:
    scope = _SCOPE.get()
    with _LOCK:
        # A task / thread started inside an entry that has since exited still carries
        # its token. Keep only live entries' tokens; with none left the refusal is
        # untagged and fails every live entry (fail closed).
        scope = tuple(t for t in scope if any(e.token is t for e in _ENTRIES))
        _REFUSED.append((event, path))
        _REFUSED_SCOPES.append(scope)
    raise LocalWriteRefused(event, path)


def _as_text(path: object) -> str | None:
    if not isinstance(path, (str, bytes, os.PathLike)):
        return None
    try:
        return os.fsdecode(path)
    except TypeError:  # a PathLike whose __fspath__ returns neither str nor bytes
        return None


def _within(real: str, prefix: str) -> bool:
    return real == prefix or real.startswith(prefix + os.sep)


def _check_path(
    event: str, path: object, policy: GuardPolicy, *, dir_fd: object = None
) -> None:
    """Refuse unless ``path`` resolves inside an allow prefix or is an allowed device."""
    if isinstance(path, int):
        return  # an already-open descriptor: no new local file
    text = _as_text(path)
    if text is None:
        _refuse(event, repr(path))
        return
    if isinstance(dir_fd, int) and dir_fd >= 0 and not os.path.isabs(text):
        _refuse(event, text)
        return
    try:
        absolute = os.path.abspath(text)
        real = os.path.realpath(absolute)
    except (OSError, ValueError):
        _refuse(event, text)
        return
    if absolute in policy.allow_devices:
        return
    if any(_within(real, prefix) for prefix in policy.allow_prefixes):
        return
    if event in _CREATE_FILE_EVENTS:
        parent, name = os.path.split(real)
        if any(
            parent == directory and re.fullmatch(pattern, name)
            for directory, pattern in policy.allow_files
        ):
            return
    if event == "os.mkdir" and any(
        _within(prefix, real)
        for prefix in (*policy.allow_prefixes, *(d for d, _ in policy.allow_files))
    ):
        return  # creating an allowed directory or one of its ancestors
    _refuse(event, real)


#: Events an ``allow_files`` pattern admits: write a matching file, set its mode/times.
_CREATE_FILE_EVENTS = frozenset({"open", "os.chmod", "os.utime"})


def _arg(args: tuple[object, ...], index: int) -> object:
    return args[index] if len(args) > index else None


def _on_open(event: str, args: tuple[object, ...], policy: GuardPolicy) -> None:
    mode = _arg(args, 1)
    flags = _arg(args, 2)
    writes = isinstance(mode, str) and bool(_WRITE_MODE_CHARS.intersection(mode))
    if isinstance(flags, int) and flags & _WRITE_FLAGS:
        writes = True
    if writes:
        _check_path(event, _arg(args, 0), policy)


#: Argument index of the ``dir_fd`` an event's target path is relative to.
_DIR_FD_INDEX = {
    "os.remove": 1,
    "os.rmdir": 1,
    "os.mkdir": 2,
    "shutil.rmtree": 1,
    "os.symlink": 2,
    "os.link": 3,
    "os.chmod": 2,
    "os.chown": 3,
    "os.utime": 3,
}


def _on_first(event: str, args: tuple[object, ...], policy: GuardPolicy) -> None:
    # os.remove / rmdir / mkdir / truncate / chmod / chown / chflags / utime / xattrs,
    # shutil.rmtree / chown / make_archive, tempfile.*
    index = _DIR_FD_INDEX.get(event)
    dir_fd = _arg(args, index) if index is not None else None
    _check_path(event, _arg(args, 0), policy, dir_fd=dir_fd)


def _on_second(event: str, args: tuple[object, ...], policy: GuardPolicy) -> None:
    # os.symlink / os.link / shutil.copyfile / copymode / copystat / copytree
    index = _DIR_FD_INDEX.get(event)
    dir_fd = _arg(args, index) if index is not None else None
    _check_path(event, _arg(args, 1), policy, dir_fd=dir_fd)


def _on_both(event: str, args: tuple[object, ...], policy: GuardPolicy) -> None:
    # os.rename (also raised by os.replace) / shutil.move
    _check_path(event, _arg(args, 0), policy, dir_fd=_arg(args, 2))
    _check_path(event, _arg(args, 1), policy, dir_fd=_arg(args, 3))


def _on_unpack(event: str, args: tuple[object, ...], policy: GuardPolicy) -> None:
    target = _arg(args, 1)
    _check_path(event, os.getcwd() if target is None else target, policy)


def _on_sqlite(event: str, args: tuple[object, ...], policy: GuardPolicy) -> None:
    database = _arg(args, 0)
    if _as_text(database) == ":memory:":
        return
    _check_path(
        event, database if database not in ("", b"") else "<sqlite-temp>", policy
    )


def _on_dbm(event: str, args: tuple[object, ...], policy: GuardPolicy) -> None:
    flag = _arg(args, 1)
    if isinstance(flag, str) and not set(flag) & set("wcn"):
        return
    _check_path(event, _arg(args, 0), policy)


def _on_spawn(event: str, args: tuple[object, ...], armed: _Armed) -> None:
    if event in ("os.system", "os.fork", "os.forkpty"):
        _refuse(event, str(_arg(args, 0)) if event == "os.system" else "<fork>")
        return
    cwd: object = None
    env: object = None
    if event == "subprocess.Popen":
        executable, argv, cwd, env = (_arg(args, i) for i in range(4))
        if isinstance(argv, (str, bytes)):
            argv = [argv]
        if executable is None and isinstance(argv, (list, tuple)) and argv:
            executable = argv[0]
    elif event == "os.spawn":
        executable, argv, env = _arg(args, 1), _arg(args, 2), _arg(args, 3)
    else:  # os.exec / os.posix_spawn
        executable, argv, env = _arg(args, 0), _arg(args, 1), _arg(args, 2)
    _check_exec(event, executable, argv, armed, cwd=cwd, env=env)


def _resolve_program(program: str, *, cwd: object, env: object) -> str | None:
    """The real path ``program`` would execute as, or ``None`` when it is not found."""
    if os.sep not in program:
        search = os.get_exec_path(env if isinstance(env, dict) else None)
        found = shutil.which(program, path=os.pathsep.join(search))
        return os.path.realpath(found) if found else None
    base = _as_text(cwd)
    if base and not os.path.isabs(program):
        program = os.path.join(base, program)
    return os.path.realpath(program)


def _argv_tail(argv: object) -> tuple[str, ...] | None:
    if not isinstance(argv, (list, tuple)):
        return None
    tail = tuple(_as_text(a) for a in argv[1:])
    return (
        None
        if any(a is None for a in tail)
        else tuple(a for a in tail if a is not None)
    )


def _check_exec(
    event: str,
    executable: object,
    argv: object,
    armed: _Armed,
    *,
    cwd: object = None,
    env: object = None,
) -> None:
    """Refuse unless ``executable`` is an arm-time allowlisted program running an
    allowlisted subcommand."""
    text = _as_text(executable) if executable is not None else None
    if not text:
        _refuse(event, repr(executable))
        return
    real = _resolve_program(text, cwd=cwd, env=env)
    name = armed.executables.get(real) if real else None
    if name is None:
        _refuse(event, text)
        return
    commands = [c[1:] for c in armed.policy.allow_commands if c[0] == name]
    if commands:
        tail = _argv_tail(argv)
        if tail is None or not any(tail[: len(c)] == c for c in commands):
            _refuse(event, f"{name} {' '.join(tail or ())}".rstrip())
            return
    with _LOCK:
        if name not in _SPAWNED:
            _SPAWNED.append(name)


def _first_executable(programs: list[object] | tuple[object, ...], *, cwd: object) -> object:
    """The candidate ``fork_exec`` will actually run: the first existing executable.

    ``subprocess`` expands a bare name to one candidate per ``PATH`` entry and the
    child execs the first that works, so missing candidates are skipped (checked
    after ``realpath``). A candidate that is not text is returned as-is, so the check
    refuses it. ``None`` when no candidate exists: the exec fails with ``ENOENT`` in
    the child and nothing runs.
    """
    base = _as_text(cwd)
    for program in programs:
        text = _as_text(program)
        if not text:
            return program
        if base and not os.path.isabs(text):
            text = os.path.join(base, text)
        real = os.path.realpath(text)
        if os.path.isfile(real) and os.access(real, os.X_OK):
            return program
    return None


def _wrap_fork_exec() -> None:
    """Check ``_posixsubprocess.fork_exec`` callers that bypass ``subprocess.Popen``.

    ``multiprocessing`` (``spawn`` start method, resource tracker, fork server) calls
    it directly and CPython raises no audit event for it. ``subprocess`` bound its own
    reference at import and is covered by the ``subprocess.Popen`` event instead.
    """
    try:
        import _posixsubprocess
    except ImportError:  # pragma: no cover - not POSIX
        return
    real: Callable[..., object] = _posixsubprocess.fork_exec
    if getattr(real, "__wrapped__", None) is not None:
        return

    def fork_exec(*args: object, **kwargs: object) -> object:
        entries = _ENTRIES
        if entries and not getattr(_LOCAL, "busy", False):
            armed = entries[-1]
            _LOCAL.busy = True
            try:
                programs = _arg(args, 1)
                if not isinstance(programs, (list, tuple)) or not programs:
                    _refuse("_posixsubprocess.fork_exec", repr(programs))
                else:
                    program = _first_executable(programs, cwd=_arg(args, 4))
                    if program is not None:
                        _check_exec(
                            "_posixsubprocess.fork_exec",
                            program,
                            _arg(args, 0),
                            armed,
                            cwd=_arg(args, 4),
                        )
            finally:
                _LOCAL.busy = False
        return real(*args, **kwargs)

    functools.update_wrapper(fork_exec, real)  # also sets __wrapped__
    setattr(_posixsubprocess, "fork_exec", fork_exec)  # noqa: B010 - typeshed pins the C signature


_HANDLERS = {
    "open": _on_open,
    "os.remove": _on_first,
    "os.rmdir": _on_first,
    "os.mkdir": _on_first,
    "os.truncate": _on_first,
    "os.chmod": _on_first,
    "os.chown": _on_first,
    "os.chflags": _on_first,
    "os.lchflags": _on_first,
    "os.utime": _on_first,
    "os.setxattr": _on_first,
    "os.removexattr": _on_first,
    "shutil.chown": _on_first,
    "shutil.rmtree": _on_first,
    "shutil.make_archive": _on_first,
    "tempfile.mkstemp": _on_first,
    "tempfile.mkdtemp": _on_first,
    "os.rename": _on_both,
    "shutil.move": _on_both,
    "os.symlink": _on_second,
    "os.link": _on_second,
    "shutil.copyfile": _on_second,
    "shutil.copymode": _on_second,
    "shutil.copystat": _on_second,
    "shutil.copytree": _on_second,
    "shutil.unpack_archive": _on_unpack,
    "sqlite3.connect": _on_sqlite,
    "dbm.open": _on_dbm,
}

#: Process-creation events, checked by :func:`_on_spawn` against the armed allowlist.
_SPAWN_EVENTS = frozenset(
    {
        "subprocess.Popen",
        "os.posix_spawn",
        "os.exec",
        "os.spawn",
        "os.system",
        "os.fork",
        "os.forkpty",
    }
)


# --- sandbox inspection (tests / exit criteria) ---------------------------------------


def sandbox_snapshot(
    roots: Iterable[str | os.PathLike[str]],
) -> dict[str, tuple[int, int]]:
    """Map every entry under ``roots`` to ``(size, mtime_ns)``.

    Symlinks are recorded but not followed. Directories are recorded as ``(-1, 0)``:
    their mtime changes whenever a child changes, so only their presence is compared.
    Missing roots contribute nothing.
    """
    snapshot: dict[str, tuple[int, int]] = {}
    for root in roots:
        top = os.fspath(root)
        if not os.path.lexists(top):
            continue
        for dirpath, dirnames, filenames in os.walk(top, followlinks=False):
            for name in (*dirnames, *filenames):
                full = os.path.join(dirpath, name)
                try:
                    st = os.lstat(full)
                except OSError:
                    continue
                if os.path.isdir(full) and not os.path.islink(full):
                    snapshot[full] = (-1, 0)
                else:
                    snapshot[full] = (st.st_size, st.st_mtime_ns)
    return snapshot


def sandbox_diff(
    before: dict[str, tuple[int, int]], after: dict[str, tuple[int, int]]
) -> list[str]:
    """``"+ path"`` created, ``"- path"`` removed, ``"~ path"`` changed; sorted by path."""
    lines: list[tuple[str, str]] = []
    for path in before.keys() | after.keys():
        if path not in before:
            lines.append((path, "+"))
        elif path not in after:
            lines.append((path, "-"))
        elif before[path] != after[path]:
            lines.append((path, "~"))
    return [f"{mark} {path}" for path, mark in sorted(lines)]
