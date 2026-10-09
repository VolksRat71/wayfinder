"""The runtime: retrieve / insert against a source's files as they are now."""
import os
import sys
import time
from pathlib import Path

from . import methods as M
from .corpus import Source, _Docs, split
from .evaluate import classify, folder_vote, picked
from .packs import discover

PRUNE = {".git", ".obsidian", ".trash", "node_modules", ".venv"}


def _opened_path(fd):
    """Where an open file really lives, asked of the OS about the descriptor (not the name)."""
    if sys.platform == "darwin":
        import fcntl
        return fcntl.fcntl(fd, fcntl.F_GETPATH, bytes(1024)).split(b"\0", 1)[0].decode()
    if os.path.isdir("/proc/self/fd"):
        return os.readlink(f"/proc/self/fd/{fd}")
    return None


class LiveCorpus(_Docs):
    """Notes on disk now. A note's key is `rel@mtime_ns`, so caches drop it when it changes.

    Only files whose real path is inside the source are notes: a symlink pointing out of the
    source is skipped, and os.walk does not descend into symlinked folders.
    """

    def __init__(self, source):
        self.source, self.now, self.cache, self.mtimes = source, time.time(), {}, {}
        self.root = Path(os.path.realpath(source.path))

    def inside(self, path):
        return Path(os.path.realpath(path)).is_relative_to(self.root)

    def at(self, _snapshot=None):
        notes = []
        for dirpath, dirnames, filenames in os.walk(self.source.path):
            dirnames[:] = [d for d in dirnames if d not in PRUNE and not d.startswith(".")]
            for name in filenames:
                full = Path(dirpath) / name
                rel = full.relative_to(self.source.path).as_posix()
                if self.source.note(self.source.prefix + rel) and self.inside(full):
                    self.mtimes[rel] = full.stat().st_mtime
                    notes.append((rel, f"{rel}@{full.stat().st_mtime_ns}"))
        return notes

    def read(self, path):
        """The file's text, only if the file actually opened lives inside the source.

        Open first, then ask where the descriptor points, so a file or folder swapped for a
        symlink between listing and reading can't redirect the read outside the source.
        """
        try:
            fd = os.open(path, os.O_RDONLY)
        except OSError:
            return None
        with os.fdopen(fd, "rb") as f:
            real = _opened_path(f.fileno())
            if real is None:
                # ponytail: no fd-path API on this platform, so the check is by name and can race;
                # macOS and Linux use the descriptor.
                real = os.path.realpath(path)
            if not Path(real).is_relative_to(self.root):
                return None
            return f.read().decode("utf-8", "replace")

    def blob(self, key):
        if key not in self.cache:
            text = self.read(self.source.path / key.rsplit("@", 1)[0])
            self.cache[key] = split(text) if text is not None else ("", "")
        return self.cache[key]

    def age_days(self, rel):
        return (self.now - self.mtimes.get(rel, 0)) / 86400


def default_source(cwd=None):
    """The configured source containing `cwd`, else `cwd` itself as a zero-config source."""
    cwd = Path(cwd or os.getcwd()).resolve()
    for source in Source.configured():
        if cwd == source.path or source.path in cwd.parents:
            return source
    return Source(cwd.name, cwd)


def _method(pack, source):
    name = picked(pack, source)
    return M.METHODS[name if M.available(name) and name in M.METHODS else pack.default]


def _results(corpus, ranked, keys, k):
    return [{"path": rel, "score": round(score, 4), "description": corpus.blob(keys[rel])[0]}
            for rel, score in ranked[:k]]


def _notes(corpus, exclude):
    """The note being looked up or filed must not rank (or vote) for itself."""
    return [(rel, key) for rel, key in corpus.at() if rel not in (exclude or ())]


def retrieve(query, source=None, k=5, pack="notes-retrieve", exclude=None):
    """Notes most likely to answer `query`, best first."""
    source = source or default_source()
    p = discover(source)[pack]
    corpus = LiveCorpus(source)
    notes = _notes(corpus, exclude)
    return {"source": str(source.path), "method": picked(p, source),
            "notes": _results(corpus, _method(p, source)(corpus, query, notes), dict(notes), k)}


def insert(text, source=None, k=5, pack="notes-insert", exclude=None):
    """Where `text` belongs: existing notes to add it to, and a folder if it should be a new note."""
    source = source or default_source()
    p = discover(source)[pack]
    corpus = LiveCorpus(source)
    notes = _notes(corpus, exclude)
    ranked = _method(p, source)(corpus, text, notes)
    # The folder vote uses text similarity only: recency pads every recent note's score, and in
    # the eval it dropped new-note folder accuracy (bm25 0.58 vs bm25+recent 0.42).
    label, confidence = folder_vote(source, M.bm25(corpus, text, notes))
    folder = source.cfg["labels"][label]["folder"] if label else None
    return {"source": str(source.path), "method": picked(p, source),
            "notes": _results(corpus, ranked, dict(notes), k),
            "new_note_folder": {"folder": folder, "confidence": round(confidence, 3)} if folder else None}


def run_pack(pack, text, source=None, k=5, exclude=None):
    source = source or default_source()
    p = discover(source)[pack]
    if p.action == "choice":
        name = picked(p, None if not p.per_source else source)
        name = name if M.available(name) and name in M.METHODS else p.default
        return {"pack": p.name, "method": name,
                "labels": [{"label": l, "score": round(s, 4)} for l, s in classify(p, name, text)]}
    return (retrieve if p.action == "retrieve" else insert)(text, source, k, pack, exclude)
