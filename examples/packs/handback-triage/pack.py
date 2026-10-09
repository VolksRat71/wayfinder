"""handback-triage: which subagent handbacks need the lead to follow up?

Data: every SubagentHandback in Claude Code subagent transcripts. Label = follow_up if the parent
session later sent that agent a SendMessage (more work, a decision, a correction), else done.
That is what happened, not a guess, but it is a proxy: some follow-ups are planned next phases.
"""
import json
import re
from pathlib import Path

from wayfinder.corpus import load_config
from wayfinder.data import builder
from wayfinder.methods import register

QUESTION = ("Does this report from a delegated agent need the lead to follow up, because the work is "
            "unfinished, blocked, waiting on a decision, or has problems?")


def _records(path):
    for line in open(path, encoding="utf-8", errors="ignore"):
        try:
            yield json.loads(line)
        except ValueError:
            continue


def _tool_uses(record):
    for c in (record.get("message") or {}).get("content") or []:
        if isinstance(c, dict) and c.get("type") == "tool_use":
            yield c


@builder("claude-handbacks")
def claude_handbacks(source):
    rows = []
    for root in load_config().get("transcripts", ["~/.claude/projects"]):
        for sub in sorted(Path(root).expanduser().glob("*/*/subagents/*.jsonl")):
            parent = sub.parent.parent.with_suffix(".jsonl")
            if not parent.exists():
                continue
            agent = sub.stem.removeprefix("agent-")
            follow_ups = [r.get("timestamp", "") for r in _records(parent) for c in _tool_uses(r)
                          if c["name"] == "SendMessage" and agent[:8] in json.dumps(c.get("input"))]
            for r in _records(sub):
                for c in _tool_uses(r):
                    if c["name"] == "SubagentHandback" and (text := (c.get("input") or {}).get("message", "").strip()):
                        later = any(t > r.get("timestamp", "") for t in follow_ups)
                        rows.append({"query": text[:4000], "truth": "follow_up" if later else "done"})
    return rows


# Baseline Laya has to beat: words agents use when they stop short.
WAITING = re.compile(r"\b(paused|stopped|blocked|waiting|gate|not yet|couldn'?t|can'?t|failed|need(s)? (you|your|a decision)|"
                     r"your call|decide|question|left (open|undone)|partial|unverified)\b", re.I)


def _yes_no(p):
    return sorted([("follow_up", p), ("done", 1 - p)], key=lambda x: -x[1])


@register("keywords")
def keywords(corpus, query, labels):
    hits = len(WAITING.findall(query))
    return _yes_no(min(0.95, 0.2 + 0.15 * hits))


@register("laya-noul")
def laya_noul(corpus, query, labels):
    from wayfinder.methods import laya_noul as noul
    return _yes_no(noul(query, QUESTION))


@register("laya-needs-review")
def laya_needs_review(corpus, query, labels):
    # Laya's typed-decisions checkpoint was trained on agent traces with a `needs_review` question.
    from wayfinder.methods import router
    ans = router().predict(query, {"needs_review": {"type": "noul", "instructions": QUESTION}},
                           model="typed-decisions")["answers"]["needs_review"]
    return _yes_no(ans["noul"])
