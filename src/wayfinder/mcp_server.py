"""stdio MCP server: retrieve / insert / packs for agents (Claude Code, Codex).

What a server may read is fixed at startup by its Policy (see policy.py); tool arguments only
choose among the allowed sources.
"""
import functools
import sys

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from . import live
from .packs import discover
from .policy import AccessError, PolicyError, from_options

READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=False)


def create_server(policy):
    server = MCPServer("wayfinder")

    def guarded(fn):
        """Restricted mode: unexpected errors become one generic line, with no traceback, path or text."""
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except ToolError:
                raise
            except Exception:
                if not policy.restricted:
                    raise
                raise ToolError("wayfinder: the request failed") from None
        return wrapper

    def source_for(arg):
        return policy.resolve(arg, default=live.default_source)

    @server.tool(annotations=READ_ONLY)
    @guarded
    def retrieve(query: str, source: str | None = None, k: int = 5, exclude: list[str] | None = None) -> dict:
        """Find the notes most likely to answer a question, best first, with their descriptions.
        Returns paths relative to the source; read them yourself. exclude: note paths to leave out.
        source: a name from list_sources (an unrestricted server also takes a folder path); may be
        omitted when only one source is available."""
        return live.retrieve(query, source_for(source), k, exclude=exclude)

    @server.tool(annotations=READ_ONLY)
    @guarded
    def insert(text: str, source: str | None = None, k: int = 5, exclude: list[str] | None = None) -> dict:
        """Suggest where new text belongs: existing notes to add it to (best first), and the folder
        for a new note if none fits. Suggests only; never writes. Follow the source's own filing rules.
        exclude: note paths to leave out, such as the note being filed if it already exists.
        source: a name from list_sources (an unrestricted server also takes a folder path)."""
        return live.insert(text, source_for(source), k, exclude=exclude)

    @server.tool(annotations=READ_ONLY)
    @guarded
    def list_sources() -> list[dict]:
        """Sources this server may read (name, path)."""
        return [{"name": s.name, "path": str(s.path)} for s in policy.sources()]

    @server.tool(annotations=READ_ONLY)
    @guarded
    def list_packs(source: str | None = None) -> list[dict]:
        """Decision packs available for a source (a name from list_sources), including any it ships."""
        return [{"name": p.name, "action": p.action, "description": p.description}
                for p in discover(source_for(source)).values()]

    @server.tool(annotations=READ_ONLY)
    @guarded
    def run_pack(pack: str, text: str, source: str | None = None, k: int = 5) -> dict:
        """Run any pack from list_packs on a query or text."""
        src = source_for(source)
        if pack not in discover(src):
            raise AccessError(f"unknown pack {pack!r}")
        return live.run_pack(pack, text, src, k)

    return server


def main(allow=None, unrestricted=False):
    try:
        policy, warning = from_options(allow, unrestricted)
    except PolicyError as e:
        sys.exit(f"wayfinder mcp: refusing to start: {e}")
    if warning:
        print(warning, file=sys.stderr)
    create_server(policy).run()
