"""Packs: one decision (what to rank, how to build its eval data, which methods to compare).

A pack is a folder holding `pack.toml` and an optional `pack.py`. Packs are found, later ones
overriding earlier, in: the built-in packs, ~/.config/wayfinder/packs/, and a source's own
.wayfinder/packs/. `pack.py` may register builders (`@builder`) and methods (`@register`);
`dataset = "<name>"` then names one of its builders.

A source's `pack.py` is code from whoever controls that repo, so it is executed only when the
source sets `trust_packs = true` in ~/.config/wayfinder/config.toml. Otherwise that pack is skipped.
"""
import importlib.util
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

BUILTIN = Path(__file__).parent / "packs"
USER = Path("~/.config/wayfinder/packs").expanduser()


@dataclass
class Pack:
    name: str
    description: str
    action: str                     # retrieve | insert
    dataset: str                    # a registered builder
    methods: list = field(default_factory=lambda: ["bm25", "recent", "bm25+recent"])
    default: str = "bm25+recent"
    metric: str = "mrr"             # what `eval --pick` maximises: hit@1 | recall@5 | mrr
    dir: Path = None


def _load(d):
    spec = tomllib.loads((d / "pack.toml").read_text())
    if (d / "pack.py").exists():
        mod = importlib.util.spec_from_file_location(f"wayfinder_pack_{d.name.replace('-', '_')}", d / "pack.py")
        mod.loader.exec_module(importlib.util.module_from_spec(mod))
    return Pack(dir=d, **spec)


def discover(source=None):
    dirs = [(BUILTIN, True), (USER, True)]
    if source:
        dirs.append((source.path / ".wayfinder" / "packs", source.trust_packs))
    packs = {}
    for root, trusted in dirs:
        for d in sorted(root.glob("*/")) if root.is_dir() else []:
            if not (d / "pack.toml").exists():
                continue
            if (d / "pack.py").exists() and not trusted:
                print(f"wayfinder: skipped {d} (pack.py not run: set trust_packs = true for this source "
                      "in ~/.config/wayfinder/config.toml to allow it)", file=sys.stderr)
                continue
            pack = _load(d)
            packs[pack.name] = pack
    return packs
