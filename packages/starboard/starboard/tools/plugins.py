# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Entry-point discovery for per-domain tool plugins (Phase-3 B5).

This is the **layered-catalog** half of Starboard's 3-tier model
(kernel -> capability -> experience). The kernel (``starboard-core``) and the
experience tier (``starboard``) ship a fixed, universal tool surface; optional
**per-domain plugins** — distributed as their own thin wheels — extend that
surface at runtime by registering additional tools/analyzers through the
``starboard.mcp_tools`` Python entry-point group. No plugin is required: with
none installed, discovery finds nothing and every built-in capability keeps
working (degrade-cleanly invariant, UNIFIED_PLAN §3.5, applied to the catalog).

**The contract (group ``starboard.mcp_tools``).** Each entry point resolves to a
:class:`ToolPlugin` — an object exposing:

* ``name``: a unique, stable registration key for the tool (used as the catalog
  key; collisions between plugins are rejected);
* ``domain``: the capability domain the tool belongs to (e.g. ``"jobs"``,
  ``"warehouse"``, ``"billing"``), so a host can enable tools by domain;
* ``create()``: a zero-argument factory returning the tool/analyzer instance.

Declared in a distributing package's ``pyproject.toml`` as, e.g.::

    [project.entry-points."starboard.mcp_tools"]
    my_domain_tool = "my_pkg.plugin:my_plugin"

where ``my_plugin`` is a module-level :class:`ToolPlugin` (a :class:`SimpleToolPlugin`
instance is the easy path). See ``packages/starboard-plugin-sample`` for a
complete scaffold.

**Deliberately kernel-light.** Like :mod:`starboard.ports.discovery`, this module
depends on nothing heavier than the stdlib (:mod:`importlib.metadata`,
:mod:`dataclasses`, :mod:`typing`). It never imports the MCP/SDK/model stack, so
loading the discovery machinery is cheap and the *shape* of a tool object is left
entirely to the host — the catalog is agnostic about what ``create()`` returns.
This keeps discovery usable from every tier, including a kernel-only install that
adds the experience tier later.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from importlib import metadata
from typing import Any, Protocol, runtime_checkable

#: The entry-point group name distributing packages register per-domain tools under.
ENTRY_POINT_GROUP = "starboard.mcp_tools"


@runtime_checkable
class ToolPlugin(Protocol):
    """Structural contract every ``starboard.mcp_tools`` entry point satisfies.

    Attributes:
        name: Unique, stable registration key for the tool (the catalog key).
        domain: The capability domain the tool belongs to (e.g. ``"jobs"``).

    Methods:
        create: Zero-argument factory returning the tool/analyzer instance.
    """

    name: str
    domain: str

    def create(self) -> Any:
        """Build and return the tool/analyzer instance for :attr:`name`."""
        ...


@dataclass(frozen=True)
class SimpleToolPlugin:
    """A ready-made :class:`ToolPlugin` backed by a factory callable.

    Distributing packages can expose a module-level instance of this and point
    their entry point at it, instead of hand-rolling a plugin class.

    Args:
        name: Unique registration key (the catalog key).
        domain: The capability domain the tool belongs to.
        factory: Zero-argument callable that builds the tool instance.
    """

    name: str
    domain: str
    factory: Any

    def create(self) -> Any:
        return self.factory()


class _EntryPointLike(Protocol):
    """Structural type for an ``importlib.metadata.EntryPoint`` (test-injectable)."""

    name: str

    def load(self) -> Any: ...


def _iter_entry_points(
    *, group: str, entry_points: Iterable[_EntryPointLike] | None
) -> Iterable[_EntryPointLike]:
    """Yield entry points for ``group`` (or the injected ``entry_points``)."""
    if entry_points is not None:
        return entry_points
    return metadata.entry_points(group=group)


def _validate_plugin(plugin: Any) -> None:
    """Raise ``TypeError``/``ValueError`` if ``plugin`` breaks the contract."""
    if not isinstance(plugin, ToolPlugin):
        raise TypeError(
            f"entry point object {plugin!r} is not a ToolPlugin "
            "(needs 'name', 'domain', and a callable 'create')"
        )
    if not isinstance(plugin.name, str) or not plugin.name:
        raise ValueError(f"tool plugin name must be a non-empty str, got {plugin.name!r}")
    if not isinstance(plugin.domain, str) or not plugin.domain:
        raise ValueError(
            f"tool plugin domain must be a non-empty str, got {plugin.domain!r}"
        )


def discover_tool_plugins(
    *,
    group: str = ENTRY_POINT_GROUP,
    entry_points: Iterable[_EntryPointLike] | None = None,
    strict: bool = False,
) -> list[ToolPlugin]:
    """Load and validate every plugin registered under ``group``.

    Args:
        group: Entry-point group name (defaults to :data:`ENTRY_POINT_GROUP`).
        entry_points: Optional pre-collected entry points (for tests); when
            ``None``, they are read from installed distributions.
        strict: When ``True``, an invalid entry point raises; otherwise it is
            skipped so one bad plugin cannot break discovery for the rest.

    Returns:
        The validated plugins, in discovery order. Empty when no plugins are
        installed (the degrade-cleanly path).
    """
    plugins: list[ToolPlugin] = []
    for ep in _iter_entry_points(group=group, entry_points=entry_points):
        try:
            plugin = ep.load()
            _validate_plugin(plugin)
        except Exception:
            if strict:
                raise
            continue
        plugins.append(plugin)
    return plugins


class ToolCatalog:
    """A name-keyed registry of discovered per-domain :class:`ToolPlugin` objects.

    The catalog holds plugins (not yet-built tools); call :meth:`create` /
    :meth:`create_all` to instantiate on demand. Names are unique: registering a
    second plugin under an existing name raises unless ``replace=True``.
    """

    def __init__(self) -> None:
        self._plugins: dict[str, ToolPlugin] = {}

    def register(self, plugin: ToolPlugin, *, replace: bool = False) -> None:
        """Register ``plugin`` under its :attr:`ToolPlugin.name`.

        Raises:
            ValueError: if a plugin is already registered under that name and
                ``replace`` is ``False``.
        """
        name = plugin.name
        if not replace and name in self._plugins:
            raise ValueError(f"a tool plugin named {name!r} is already registered")
        self._plugins[name] = plugin

    def has(self, name: str) -> bool:
        """Whether a plugin is registered under ``name``."""
        return name in self._plugins

    def get(self, name: str) -> ToolPlugin:
        """Return the plugin registered under ``name`` (raises ``KeyError``)."""
        return self._plugins[name]

    def names(self) -> list[str]:
        """The registered plugin names, in registration order."""
        return list(self._plugins)

    def domains(self) -> list[str]:
        """The distinct domains present, in first-seen order."""
        seen: dict[str, None] = {}
        for plugin in self._plugins.values():
            seen.setdefault(plugin.domain, None)
        return list(seen)

    def by_domain(self, domain: str) -> list[ToolPlugin]:
        """The registered plugins whose :attr:`ToolPlugin.domain` equals ``domain``."""
        return [p for p in self._plugins.values() if p.domain == domain]

    def create(self, name: str) -> Any:
        """Instantiate the tool for the plugin registered under ``name``."""
        return self._plugins[name].create()

    def create_all(self) -> dict[str, Any]:
        """Instantiate every registered tool, keyed by plugin name."""
        return {name: plugin.create() for name, plugin in self._plugins.items()}

    def __len__(self) -> int:
        return len(self._plugins)

    def __contains__(self, name: object) -> bool:
        return name in self._plugins


def register_tool_plugins(
    catalog: ToolCatalog,
    plugins: Iterable[ToolPlugin],
    *,
    strict: bool = False,
) -> ToolCatalog:
    """Register each plugin into ``catalog`` (keyed by name). Returns ``catalog``.

    On a duplicate name, ``strict=True`` raises; otherwise the later plugin is
    skipped (first registration wins) so a conflicting plugin cannot displace an
    already-registered one silently.
    """
    for plugin in plugins:
        try:
            catalog.register(plugin)
        except ValueError:
            if strict:
                raise
            continue
    return catalog


def install_entry_point_tools(
    catalog: ToolCatalog | None = None,
    *,
    group: str = ENTRY_POINT_GROUP,
    entry_points: Iterable[_EntryPointLike] | None = None,
    strict: bool = False,
) -> ToolCatalog:
    """Discover ``group`` plugins and register them onto (or into a new) ``catalog``.

    This is the single call a host makes to layer discovered per-domain tools on
    top of its built-in surface. Additive by construction: with no plugin package
    installed, discovery finds nothing, the catalog stays empty, and every
    built-in tool keeps working unchanged.
    """
    if catalog is None:
        catalog = ToolCatalog()
    plugins = discover_tool_plugins(
        group=group, entry_points=entry_points, strict=strict
    )
    return register_tool_plugins(catalog, plugins, strict=strict)
