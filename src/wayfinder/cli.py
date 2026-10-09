"""wayfinder: retrieve / insert over notes, and the eval that picks how."""
import argparse
import sys
from pathlib import Path

from . import evaluate as E
from .corpus import Source
from .packs import discover


def _sources(args):
    return [Source.resolve(s) for s in args.source] if args.source else Source.configured()


def cmd_eval(args):
    sources = _sources(args)
    if not sources:
        sys.exit("No sources: pass --source PATH or add [sources.<name>] to ~/.config/wayfinder/config.toml")
    print("source\taction\tmethod\tn\thit@1\trecall@5\tmrr_or_acc\tsel@50")
    for source in sources:
        if source.root is None:
            print(f"skip {source.name}: not in a git repo, nothing to evaluate", file=sys.stderr)
            continue
        for pack in discover(source).values():
            if args.pack and pack.name not in args.pack:
                continue
            rows = E.evaluate(pack, source, args.methods, emit=lambda r: print("\t".join(map(E.fmt, r)), flush=True))
            E.append_results(rows, Path(args.results).expanduser())
            if args.pick and (best := E.pick(pack, source, rows)):
                print(f"picked {best} for {pack.name} on {source.name}", file=sys.stderr)


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
    k = sub.add_parser("packs", help="list available packs")
    k.add_argument("--source", action="append")
    k.set_defaults(fn=cmd_packs)
    args = p.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
