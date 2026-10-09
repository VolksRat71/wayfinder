"""Sources (a folder of notes, usually inside a git repo) and the corpora methods rank over.

A Source works with zero config: point it at a folder and its top-level folders become the insert
labels. `~/.config/wayfinder/config.toml` adds excludes, extra transcript read roots, folder
descriptions, and auto-placed paths.
"""
import bisect
import collections
import os
import re
import subprocess
import tomllib
from pathlib import Path

INDEX_NAMES = {"00 Home.md", "README.md", "MEMORY.md"}
FRONTMATTER = re.compile(r"\A---\n.*?\n---\n?", re.S)
DESCRIPTION = re.compile(r"^description:\s*[\"']?(.*?)[\"']?\s*$", re.M)
MAX_CHARS = 4000
CONFIG = Path(os.environ.get("WAYFINDER_CONFIG", "~/.config/wayfinder/config.toml")).expanduser()


def git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=True).stdout


def load_config():
    return tomllib.loads(CONFIG.read_text()) if CONFIG.exists() else {}


class Source:
    def __init__(self, name, path, exclude=(), labels=None, read_roots=None, auto_placed=(), instructions=None,
                 trust_packs=False):
        self.name, self.path = name, Path(path).expanduser().resolve()
        # A source's own pack.py is code from that repo; it only runs when the user's config says so.
        self.trust_packs = trust_packs
        self.cfg = {"exclude": list(exclude), "auto_placed": list(auto_placed),
                    "instructions": instructions or "Where should this note be filed?"}
        try:
            self.root = Path(git(self.path, "rev-parse", "--show-toplevel").strip())
            rel = self.path.relative_to(self.root).as_posix()
            self.prefix = "" if rel == "." else rel + "/"
        except subprocess.CalledProcessError:
            self.root, self.prefix = None, ""  # live use only; eval needs git history
        self.cfg["labels"] = labels or {
            d.name: {"folder": d.name, "criteria": d.name} for d in sorted(self.path.iterdir())
            if d.is_dir() and not d.name.startswith((".", "_")) and self.note(self.prefix + d.name + "/x.md")}
        roots = {str(self.path) + "/": ""}
        home = str(Path.home())
        if str(self.path).startswith(home):
            roots["~" + str(self.path)[len(home):] + "/"] = ""
        roots.update(read_roots or {})
        self.cfg["read_roots"] = roots

    @classmethod
    def resolve(cls, name_or_path):
        cfg = load_config().get("sources", {})
        if name_or_path in cfg:
            return cls(name_or_path, **cfg[name_or_path])
        p = Path(name_or_path).expanduser().resolve()
        named = next((n for n, c in cfg.items() if Path(c["path"]).expanduser().resolve() == p), None)
        return cls(named, **cfg[named]) if named else cls(p.name, p)

    @classmethod
    def configured(cls):
        return [cls(n, **c) for n, c in sorted(load_config().get("sources", {}).items())]

    def note(self, repo_path):
        """Repo path -> source-relative note path, or None if it is not a scoreable note."""
        if not repo_path.startswith(self.prefix) or not repo_path.endswith(".md"):
            return None
        rel = repo_path[len(self.prefix):]
        name = rel.rsplit("/", 1)[-1]
        if name in INDEX_NAMES or name.startswith("_MOC") or any(rel.startswith(x) for x in self.cfg["exclude"]):
            return None
        return rel

    def label(self, rel):
        return next((k for k, v in self.cfg["labels"].items() if rel.startswith(v["folder"] + "/")), None)

    def tree(self, commit):
        out = git(self.root, "ls-tree", "-r", "--name-only", commit, "--", self.prefix or ".")
        return {n for n in map(self.note, out.splitlines()) if n}


def split(raw):
    """(description, body) of a note's text."""
    front = FRONTMATTER.match(raw)
    desc = DESCRIPTION.search(front.group(0)) if front else None
    return desc.group(1) if desc else "", FRONTMATTER.sub("", raw).strip()[:MAX_CHARS]


class _Docs:
    """Shared by both corpora: `blob(key)` -> (description, body)."""

    def doc(self, rel, key):
        desc, body = self.blob(key)
        return f"# {Path(rel).stem}\n{desc}\n\n{body}"

    def option(self, rel, key):
        """Short label for a choice option: path plus the note's own description."""
        desc = self.blob(key)[0]
        return f"{rel[:-3]}: {desc}"[:240] if desc else rel[:-3]


class LabelCorpus(_Docs):
    """Candidates for a `choice` pack are its labels; a label's text is its description."""

    def blob(self, description):
        return "", description

    def age_days(self, label):
        return 0.0


class GitCorpus(_Docs):
    """Notes as they were at any commit, read from git once per blob. Used by the eval."""

    def __init__(self, source):
        self.source, self.text, self.snaps, self.times, self.snap = source, {}, {}, {}, None
        self.history = collections.defaultdict(list)  # note -> sorted commit times, for recency at any snapshot
        t = 0
        for line in git(source.root, "log", "--all", "--format=@%ct", "--name-only", "--",
                        source.prefix or ".").splitlines():
            if line.startswith("@"):
                t = int(line[1:])
            elif (rel := source.note(line)):
                self.history[rel].append(t)
        for times in self.history.values():
            times.sort()
        self.cat = subprocess.Popen(["git", "-C", str(source.root), "cat-file", "--batch"],
                                    stdin=subprocess.PIPE, stdout=subprocess.PIPE)

    def blob(self, sha):
        if sha not in self.text:
            self.cat.stdin.write(sha.encode() + b"\n"); self.cat.stdin.flush()
            size = int(self.cat.stdout.readline().split()[2])
            self.text[sha] = split(self.cat.stdout.read(size + 1)[:-1].decode("utf-8", "replace"))
        return self.text[sha]

    def at(self, snap):
        """[(rel_path, blob_sha)] for the scoreable notes at a commit; recency is measured from it."""
        self.snap = snap
        if snap not in self.snaps:
            out = git(self.source.root, "ls-tree", "-r", snap, "--", self.source.prefix or ".")
            self.snaps[snap] = [(rel, meta.split()[2]) for meta, path in (l.split("\t", 1) for l in out.splitlines())
                                if (rel := self.source.note(path))]
        return self.snaps[snap]

    def age_days(self, rel):
        if self.snap not in self.times:
            self.times[self.snap] = int(git(self.source.root, "show", "-s", "--format=%ct", self.snap))
        now, times = self.times[self.snap], self.history.get(rel, [])
        i = bisect.bisect_right(times, now)
        return (now - times[i - 1]) / 86400 if i else 1e6
