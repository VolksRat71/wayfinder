"""Dataset builders: turn what actually happened into labelled rows. `builder(source) -> [row]`.

git-inserts       a commit edited an existing note (kind=update: query = added lines, truth = [note])
                  or added a note (kind=new: query = its text, truth = its folder label)
transcript-reads  a typed prompt (or subagent brief) in a Claude transcript; truth = notes then read

Every row carries `snapshot`, the commit whose notes are the candidates, so no method can find a
note that did not exist yet. Bulk commits (> MAX_FILES notes) and renames are filing passes, not
placement decisions, and are skipped; so are paths a tool picks (`auto_placed`).
"""
import json
import re
from pathlib import Path

from .corpus import FRONTMATTER, git, load_config

MAX_FILES = 5
MIN_ADDED_CHARS = 80
YAML_LINE = re.compile(r"^[a-z_]+:\s")
TAG_BLOCK = re.compile(r"<(system-reminder|pasted_content[^>]*)>.*?</\1[^>]*>|\[Image[^\]]*\]", re.S)
# ponytail: Bash reads are found by path mention, not by parsing the shell; relative paths after a
# `cd` are missed. Commands that move/delete/copy files are not reads.
NOT_A_READ = re.compile(r"\b(mv|rm|cp|git)\b")
BUILDERS = {}


def builder(name):
    def add(fn):
        BUILDERS[name] = fn
        return fn
    return add


@builder("git-inserts")
def git_inserts(source):
    log = git(source.root, "log", "--all", "--reverse", "-M", "--format=@%H %P", "--name-status", "--",
              source.prefix or ".")
    commits, cur = [], None
    for line in log.splitlines():
        if line.startswith("@"):
            sha, *parents = line[1:].split()
            cur = {"sha": sha, "parent": parents[0] if parents else None, "files": []}
            commits.append(cur)
        elif line.strip():
            status, *paths = line.split("\t")
            cur["files"].append((status[0], paths[-1]))
    auto = [re.compile(x) for x in source.cfg["auto_placed"]]
    seen, rows = set(), []
    for c in commits:
        notes = [(s, source.note(p), p) for s, p in c["files"] if source.note(p)]
        if not c["parent"] or not notes or len(notes) > MAX_FILES or any(s == "R" for s, _, _ in notes):
            continue
        for status, rel, repo_path in notes:
            if any(a.search(rel) for a in auto):
                continue
            if status == "A" and source.label(rel) and rel not in seen:
                seen.add(rel)
                text = FRONTMATTER.sub("", git(source.root, "show", f"{c['sha']}:{repo_path}")).strip()
                if text:
                    rows.append({"kind": "new", "query": f"# {Path(rel).stem}\n\n{text}", "truth": source.label(rel),
                                 "path": rel, "snapshot": c["parent"], "commit": c["sha"]})
            elif status == "M":
                diff = git(source.root, "show", "-U0", "--format=", c["sha"], "--", repo_path)
                added = "\n".join(l[1:] for l in diff.splitlines()
                                  if l.startswith("+") and not l.startswith("+++") and not YAML_LINE.match(l[1:]))
                if (len(added.strip()) >= MIN_ADDED_CHARS and (rel, added) not in seen
                        and rel in source.tree(c["parent"])):
                    seen.add((rel, added))
                    rows.append({"kind": "update", "query": added.strip(), "truth": [rel],
                                 "snapshot": c["parent"], "commit": c["sha"]})
    return rows


def _prompt_text(msg):
    content = msg.get("content")
    if isinstance(content, list):
        if any(c.get("type") == "tool_result" for c in content):
            return None
        content = "\n".join(c.get("text", "") for c in content if c.get("type") == "text")
    if not isinstance(content, str):
        return None
    text = TAG_BLOCK.sub("", content).strip()
    return None if not text or text.startswith(("<", "Caveat:")) else text


def _read_paths(tool_use, roots):
    """Absolute note paths a Read or Bash call looked at."""
    inp = tool_use.get("input") or {}
    if tool_use.get("name") == "Read":
        return [inp.get("file_path", "")]
    if tool_use.get("name") != "Bash" or NOT_A_READ.search(inp.get("command", "")):
        return []
    cmd = inp.get("command", "").replace("\\ ", " ")
    return [m.group(0) for root in roots for m in re.finditer(re.escape(root) + r"[^\"'\n|;&>]*?\.md", cmd)]


def transcript_files():
    roots = load_config().get("transcripts", ["~/.claude/projects"])
    files = []
    for r in map(lambda p: Path(p).expanduser(), roots):
        # Subagent transcripts count too: their first prompt is the brief they were given.
        files += sorted(r.glob("*/*.jsonl")) + sorted(r.glob("*/*/subagents/*.jsonl"))
    return files


def _reads(source):
    roots, seen = source.cfg["read_roots"], set()
    for path in transcript_files():
        subagent = path.parent.name == "subagents"
        prompt, ts, reads = None, None, []

        def flush():
            truth = sorted(set(reads))
            if prompt and truth and (prompt, tuple(truth)) not in seen:
                seen.add((prompt, tuple(truth)))
                yield {"query": prompt, "truth": truth, "ts": ts, "session": path.stem}

        for line in open(path, encoding="utf-8"):
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("isSidechain") and not subagent:
                continue
            msg = r.get("message") or {}
            if r.get("type") == "user" and (text := _prompt_text(msg)):
                yield from flush()
                prompt, ts, reads = text[:2000], r.get("timestamp"), []
            elif r.get("type") == "assistant" and isinstance(msg.get("content"), list):
                for c in msg["content"]:
                    if c.get("type") != "tool_use":
                        continue
                    for fp in _read_paths(c, roots):
                        for abs_root, rel_root in roots.items():
                            if fp.startswith(abs_root) and (rel := source.note(source.prefix + rel_root + fp[len(abs_root):])):
                                reads.append(rel)
        yield from flush()


@builder("transcript-reads")
def transcript_reads(source):
    rows, snapshots = [], {}
    for row in _reads(source):
        # Candidates = the source as committed just before the prompt; drop truths that did not exist yet.
        hour = row["ts"][:13]
        if hour not in snapshots:
            snapshots[hour] = git(source.root, "rev-list", "-1", f"--before={row['ts']}", "--all", "--",
                                  source.prefix or ".").strip()
        snap = snapshots[hour]
        if snap and (truth := [t for t in row["truth"] if t in source.tree(snap)]):
            rows.append({**row, "truth": truth, "snapshot": snap})
    return rows
