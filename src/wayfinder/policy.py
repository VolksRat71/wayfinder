"""Which sources an MCP server may touch.

The operator fixes the policy when the server starts (`wayfinder mcp --allow NAME`, or
`[mcp] allow = [...]` in the config). Tool arguments can only pick among allowed sources by
name; they can never add one. Restricted is the default: with no allowlist the server refuses to
start, and only an explicit --unrestricted opens it up. It never falls back: an invalid allowlist
stops the server from starting, and a source that has gone missing or moved fails that call.

This is defense in depth inside one process. It does not stop an agent that can read files
some other way (its own shell or file tools); that takes separate configs per instance plus OS
or container filesystem permissions.
"""
from pathlib import Path

from mcp.server.mcpserver.exceptions import ToolError

from .corpus import Source, load_config


class PolicyError(Exception):
    """Invalid restricted configuration. Raised at startup; the server must not run."""


class AccessError(ToolError):
    """A request outside the policy. Its message is safe to show the agent."""


class Policy:
    def __init__(self, allowed=None):
        self.allowed = allowed  # None = unrestricted; else {name: (Source, configured path)}

    @property
    def restricted(self):
        return self.allowed is not None

    @classmethod
    def unrestricted(cls):
        return cls()

    @classmethod
    def restrict(cls, names, config=None):
        config = load_config() if config is None else config
        sources = config.get("sources", {})
        if not names:
            raise PolicyError("the allowlist is empty")
        allowed = {}
        for name in names:
            if name not in sources:
                raise PolicyError(f"allowed source {name!r} is not defined in the wayfinder config")
            path = Path(sources[name]["path"]).expanduser()
            if not path.is_dir():
                raise PolicyError(f"allowed source {name!r} is not an existing folder")
            allowed[name] = (Source(name, **sources[name]), path)
        return cls(allowed)

    def names(self):
        return sorted(self.allowed) if self.restricted else []

    def resolve(self, arg, default=None):
        """The Source an argument names. Unrestricted: a name or any folder (default: `default()`)."""
        if not self.restricted:
            return Source.resolve(arg) if arg else default()
        if arg is None:
            if len(self.allowed) == 1:
                arg = next(iter(self.allowed))
            else:
                raise AccessError(f"pass source: one of {self.names()}")
        # Exact names only: a path, a traversal or a name outside the list all get the same
        # answer, which never says whether such a source exists elsewhere.
        if not isinstance(arg, str) or arg not in self.allowed:
            raise AccessError(f"unknown source; available: {self.names()}")
        source, configured = self.allowed[arg]
        # Re-check on every call: the folder may be gone, or its path may now resolve elsewhere.
        if not configured.is_dir() or configured.resolve() != source.path:
            raise AccessError(f"source {arg!r} is unavailable")
        return source

    def sources(self):
        """Sources this policy may list."""
        if not self.restricted:
            return Source.configured()
        return [source for source, _ in self.allowed.values()]


def from_options(allow=None, unrestricted=False, config=None):
    """The policy for `wayfinder mcp`. Returns (policy, warning or None); raises PolicyError."""
    # The warning slot is kept for callers; no mode warns any more, it either runs or refuses.
    config = load_config() if config is None else config
    if allow and unrestricted:
        raise PolicyError("--allow and --unrestricted are mutually exclusive")
    if unrestricted:
        return Policy.unrestricted(), None
    names = allow if allow else config.get("mcp", {}).get("allow")
    if names is not None:
        return Policy.restrict(names, config), None
    raise PolicyError(
        "no allowlist configured. Set [mcp] allow = [\"<source name>\", ...] in the config "
        "(or pass --allow NAME); for local development, pass --unrestricted explicitly.")
