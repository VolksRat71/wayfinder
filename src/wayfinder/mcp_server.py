"""stdio MCP server: retrieve / insert / packs for agents (Claude Code, Codex)."""
from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from . import live
from .corpus import Source
from .packs import discover

server = MCPServer("wayfinder")
READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=False)


def _source(source):
    return Source.resolve(source) if source else live.default_source()


@server.tool(annotations=READ_ONLY)
def retrieve(query: str, source: str | None = None, k: int = 5, exclude: list[str] | None = None) -> dict:
    """Find the notes most likely to answer a question, best first, with their descriptions.

    source: a configured source name (see list_sources) or a folder path; defaults to the source
    containing the current directory. exclude: note paths to leave out (e.g. the note you are in).
    Returns paths relative to the source; read them yourself.
    """
    return live.retrieve(query, _source(source), k, exclude=exclude)


@server.tool(annotations=READ_ONLY)
def insert(text: str, source: str | None = None, k: int = 5, exclude: list[str] | None = None) -> dict:
    """Suggest where new text belongs: existing notes to add it to (best first), and the folder
    for a new note if none fits. Suggests only; never writes. Follow the source's own filing rules.
    exclude: note paths to leave out, such as the note being filed if it already exists."""
    return live.insert(text, _source(source), k, exclude=exclude)


@server.tool(annotations=READ_ONLY)
def list_sources() -> list[dict]:
    """Configured sources (name, path). Any folder path also works as a source."""
    return [{"name": s.name, "path": str(s.path)} for s in Source.configured()]


@server.tool(annotations=READ_ONLY)
def list_packs(source: str | None = None) -> list[dict]:
    """Decision packs available for a source, including any the source ships itself."""
    return [{"name": p.name, "action": p.action, "description": p.description}
            for p in discover(_source(source)).values()]


@server.tool(annotations=READ_ONLY)
def run_pack(pack: str, text: str, source: str | None = None, k: int = 5) -> dict:
    """Run any pack from list_packs on a query or text."""
    return live.run_pack(pack, text, _source(source), k)


def main():
    server.run()
