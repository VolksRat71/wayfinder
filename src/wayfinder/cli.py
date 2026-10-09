"""wayfinder: retrieve / insert over notes, and the eval that picks how."""
import argparse
import json
import shutil
import sys
from pathlib import Path

from . import evaluate as E
from . import live
from .corpus import Source
from .packs import discover


def _sources(args):
    return [Source.resolve(s) for s in args.source] if args.source else Source.configured()


def cmd_eval(args):
    sources = _sources(args)
    if not sources:
        sys.exit("No sources: pass --source PATH or add [sources.<name>] to ~/.config/wayfinder/config.toml")
    print("source\taction\tmethod\tn\thit@1\trecall@5\tmrr_or_acc\tsel@50")
    results = Path(args.results).expanduser()

    def run(pack, source):
        try:
            rows = E.evaluate(pack, source, args.methods, emit=lambda r: print("\t".join(map(E.fmt, r)), flush=True))
        except Exception as e:  # one broken pack must not sink the rest of the run
            where = source.name if source else "all"
            print(f"wayfinder eval: pack {pack.name} failed on {where}: {type(e).__name__}: {e}", file=sys.stderr)
            return
        E.append_results(rows, results)
        if args.pick and (best := E.pick(pack, source, rows)):
            print(f"picked {best} for {pack.name} on {source.name if source else 'all'}", file=sys.stderr)

    for pack in discover().values():  # packs whose data doesn't depend on a source run once
        if not pack.per_source and (not args.pack or pack.name in args.pack):
            run(pack, None)
    for source in sources:
        if source.root is None:
            print(f"skip {source.name}: not in a git repo, nothing to evaluate", file=sys.stderr)
            continue
        for pack in discover(source).values():
            if pack.per_source and (not args.pack or pack.name in args.pack):
                run(pack, source)


def _print(result, as_json):
    if as_json:
        print(json.dumps(result, indent=2))
        return
    for n in result["notes"]:
        print(f"{n['score']:.3f}  {n['path']}" + (f"  - {n['description']}" if n["description"] else ""))
    if (folder := result.get("new_note_folder")):
        print(f"new note -> {folder['folder']}/  ({folder['confidence']:.2f})")


def cmd_retrieve(args):
    source = Source.resolve(args.source) if args.source else None
    _print(live.retrieve(" ".join(args.query), source, args.k, exclude=args.exclude), args.json)


def cmd_insert(args):
    text = sys.stdin.read() if args.text in (None, "-") else args.text
    source = Source.resolve(args.source) if args.source else None
    _print(live.insert(text, source, args.k, exclude=args.exclude), args.json)


def cmd_mcp(args):
    from .mcp_server import main as serve
    serve(allow=args.allow, unrestricted=args.unrestricted)


def cmd_obsidian_install(args):
    vault = Path(args.vault).expanduser().resolve()
    if not (vault / ".obsidian").is_dir():
        sys.exit(f"{vault} is not an Obsidian vault (no .obsidian/ folder)")
    dest = vault / ".obsidian" / "plugins" / "wayfinder"
    dest.mkdir(parents=True, exist_ok=True)
    for name in ("manifest.json", "main.js"):
        shutil.copy2(Path(__file__).parent / "obsidian_plugin" / name, dest / name)
    print(f"Installed to {dest}. In Obsidian: Settings > Community plugins > enable Wayfinder, then run "
          "'Wayfinder: Related notes' or 'Wayfinder: Where does this go?' from the command palette.")
    # The plugin never takes the CLI path from the vault (a synced or committed data.json could
    # point it at anything); it checks the standard install locations instead.
    here = shutil.which("wayfinder")
    standard = [Path("~/.local/bin/wayfinder").expanduser(), Path("/opt/homebrew/bin/wayfinder"),
                Path("/usr/local/bin/wayfinder")]
    if here and Path(here) not in standard:
        print(f"This CLI is at {here}, which the plugin won't find by itself: set it in the plugin's settings "
              "(stored on this device only).")


def cmd_packs(args):
    source = Source.resolve(args.source[0]) if args.source else None
    for pack in discover(source).values():
        print(f"{pack.name}\t{pack.action}\t{pack.description}\t{pack.dir}")


def main(argv=None):
    p = argparse.ArgumentParser(prog="wayfinder", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("eval", help="score each pack's methods on your own history")
    e.add_argument("--source", action="append", help="configured source name or a path (repeatable)")
    e.add_argument("--pack", action="append", help="only these packs (repeatable)")
    e.add_argument("--methods", nargs="+", help="override the pack's method list")
    e.add_argument("--pick", action="store_true", help="make each pack's best method the default")
    e.add_argument("--results", default=str(E.DATA / "results.tsv"))
    e.set_defaults(fn=cmd_eval)
    r = sub.add_parser("retrieve", help="notes most likely to answer a question")
    r.add_argument("query", nargs="+")
    i = sub.add_parser("insert", help="where new text belongs (reads stdin when TEXT is - or missing)")
    i.add_argument("text", nargs="?")
    for c, fn in ((r, cmd_retrieve), (i, cmd_insert)):
        c.add_argument("--source", help="configured source name or a path (default: the one containing cwd)")
        c.add_argument("-k", type=int, default=5)
        c.add_argument("--json", action="store_true")
        c.add_argument("--exclude", action="append", help="note path (relative to the source) to leave out, e.g. "
                       "the note being filed (repeatable)")
        c.set_defaults(fn=fn)
    m = sub.add_parser("mcp", help="run the stdio MCP server")
    m.add_argument("--allow", action="append", metavar="NAME",
                   help="restrict this server to these configured sources (repeatable); tool arguments can't add more")
    m.add_argument("--unrestricted", action="store_true",
                   help="explicit local-dev mode: tools accept any folder path")
    m.set_defaults(fn=cmd_mcp)
    o = sub.add_parser("obsidian-install", help="install the Obsidian plugin into a vault")
    o.add_argument("vault")
    o.set_defaults(fn=cmd_obsidian_install)
    k = sub.add_parser("packs", help="list available packs")
    k.add_argument("--source", action="append")
    k.set_defaults(fn=cmd_packs)
    args = p.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
