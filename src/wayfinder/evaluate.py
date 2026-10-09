"""Score a pack's methods on rows built from a source's own history.

retrieve / insert-update rows: hit@1, recall@5, mrr; `<action>/unnamed` drops queries that name
the target file (keyword search gets those for free). insert-new rows: folder accuracy and
selective accuracy at 50% coverage, against the majority folder at the snapshot. With Laya
installed, `update_vs_new` asks Laya whether the text belongs in BM25's best note.
"""
import collections
import datetime
import json
import math
import os
from pathlib import Path

from . import methods as M
from .corpus import GitCorpus, LabelCorpus
from .data import BUILDERS

DATA = Path(os.environ.get("XDG_DATA_HOME", "~/.local/share")).expanduser() / "wayfinder"
STATE = Path(os.environ.get("XDG_STATE_HOME", "~/.local/state")).expanduser() / "wayfinder"
HEADER = "date\tcommit\tsource\taction\tmethod\tn\thit@1\trecall@5\tmrr_or_acc\tsel@50\n"


def selective_accuracy(confs, corrects, coverage):
    """Accuracy over the most confident `coverage` share; a cut inside a tie group takes the group."""
    if not confs:
        return None
    cut = sorted(confs, reverse=True)[max(1, math.ceil(coverage * len(confs))) - 1]
    kept = [ok for c, ok in zip(confs, corrects) if c >= cut]
    return sum(kept) / len(kept)


def _rank_scores(ranked, truth):
    order = [rel for rel, _ in ranked]
    ranks = [order.index(t) + 1 for t in truth if t in order]
    first = min(ranks) if ranks else None
    return {"hit1": first == 1, "recall5": sum(r <= M.K for r in ranks) / len(truth),
            "rr": 1 / first if first else 0.0}


def _rank_row(src, action, method, per):
    n = len(per)
    return (src, action, method, n, sum(p["hit1"] for p in per) / n,
            sum(p["recall5"] for p in per) / n, sum(p["rr"] for p in per) / n, "")


def _class_row(src, action, method, per):
    n = len(per)
    return (src, action, method, n, "", "", sum(p["correct"] for p in per) / n,
            selective_accuracy([p["conf"] for p in per], [p["correct"] for p in per], 0.5))


def folder_vote(source, ranked):
    votes = collections.Counter()
    for rel, s in [(rel, s) for rel, s in ranked if source.label(rel)][:M.K]:
        votes[source.label(rel)] += max(s, 0)
    if not votes:
        return None, 0.0
    label, mass = votes.most_common(1)[0]
    return label, mass / (sum(votes.values()) or 1)


def classify(pack, method, text):
    """A choice pack's labels ranked by `method`, scores normalised to sum to 1."""
    ranked = M.METHODS[method](LabelCorpus(), text, list(pack.labels.items()))
    total = sum(max(s, 0) for _, s in ranked) or 1
    return [(label, max(s, 0) / total) for label, s in ranked]


def _evaluate_choice(pack, source, names, add):
    """Accuracy and sel@50 per method; `choice/<label>` rows are that label's recall."""
    src, rows = (source.name if source else "-"), BUILDERS[pack.dataset](source)
    if not rows:
        return
    label, count = collections.Counter(r["truth"] for r in rows).most_common(1)[0]
    add((src, "choice", "majority", len(rows), "", "", count / len(rows), ""))
    for name in names:
        per = []
        for r in rows:
            top, conf = classify(pack, name, r["query"])[0]
            per.append({"correct": top == r["truth"], "conf": conf, "truth": r["truth"]})
        add(_class_row(src, "choice", name, per))
        for lab in pack.labels:
            if (subset := [p for p in per if p["truth"] == lab]):
                add(_class_row(src, f"choice/{lab}", name, subset))


def evaluate(pack, source, methods=None, emit=print):
    """Yield summary rows (source, action, method, n, hit@1, recall@5, mrr_or_acc, sel@50)."""
    names = [m for m in (methods or pack.methods) if M.available(m)]
    if pack.action == "choice":
        out = []
        _evaluate_choice(pack, source, names, lambda row: (out.append(row), emit(row)))
        return out
    corpus, rows = GitCorpus(source), BUILDERS[pack.dataset](source)
    groups = ({"retrieve": rows} if pack.action == "retrieve" else
              {"insert_update": [r for r in rows if r["kind"] == "update"],
               "insert_new": [r for r in rows if r["kind"] == "new"]})
    out = []

    def add(row):
        out.append(row)
        emit(row)

    for action, group in groups.items():
        if not group:
            continue
        if action == "insert_new":
            per = []
            for r in group:
                counts = collections.Counter(source.label(rel) for rel, _ in corpus.at(r["snapshot"]) if source.label(rel))
                label, count = counts.most_common(1)[0]
                per.append({"correct": label == r["truth"], "conf": count / sum(counts.values())})
            add(_class_row(source.name, action, "majority", per))
        for name in names:
            method, per = M.METHODS[name], []
            for r in group:
                notes = corpus.at(r["snapshot"])
                if action == "insert_new":
                    if name == "bm25+laya":
                        probs = M.laya_choice(r["query"], {k: x["criteria"] for k, x in source.cfg["labels"].items()},
                                              source.cfg["instructions"])
                        label, conf = max(probs.items(), key=lambda x: x[1])
                    else:
                        label, conf = folder_vote(source, method(corpus, r["query"], notes))
                    per.append({"correct": label == r["truth"], "conf": conf})
                else:
                    per.append({**_rank_scores(method(corpus, r["query"], notes), r["truth"]),
                                "named": any(Path(t).stem.lower() in r["query"].lower() for t in r["truth"])})
            if action == "insert_new":
                add(_class_row(source.name, action, name, per))
            else:
                add(_rank_row(source.name, action, name, per))
                if (unnamed := [p for p in per if not p["named"]]):
                    add(_rank_row(source.name, action + "/unnamed", name, unnamed))
    if pack.action == "insert" and "bm25+laya" in names:
        for row in _update_vs_new(source, corpus, rows):
            add(row)
    return out


def _update_vs_new(source, corpus, rows):
    """Laya noul: does this text belong in BM25's best existing note, or in a new note?"""
    if len({r["kind"] for r in rows}) < 2:
        return []
    per = []
    for r in sorted(rows, key=lambda r: r["kind"] != "update"):
        belongs = r["kind"] == "update"
        text = r["query"] if belongs else r["query"].split("\n", 2)[-1]  # drop the new note's title line
        notes = corpus.at(r["snapshot"])
        best = M.bm25(corpus, text, notes)[0][0]
        p = M.laya_noul(f"New text:\n{text[:1500]}\n\nExisting note: {corpus.option(best, dict(notes)[best])}",
                        "Does the new text belong inside the existing note, rather than in a separate new note?")
        per.append({"p": p, "belongs": belongs})
    n = len(per)
    majority = max(sum(x["belongs"] for x in per), sum(not x["belongs"] for x in per)) / n
    correct = [(x["p"] > 0.5) == x["belongs"] for x in per]
    conf = [max(x["p"], 1 - x["p"]) for x in per]
    return [(source.name, "update_vs_new", "majority", n, "", "", majority, ""),
            (source.name, "update_vs_new", "laya-noul", n, "", "", sum(correct) / n,
             selective_accuracy(conf, correct, 0.5))]


def fmt(x):
    return f"{x:.3f}" if isinstance(x, float) else str(x)


def append_results(rows, path, commit=""):
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    with open(path, "a") as f:
        if new:
            f.write(HEADER)
        for row in rows:
            f.write("\t".join([datetime.date.today().isoformat(), commit] + [fmt(x) for x in row]) + "\n")


METRIC_COLUMN = {"hit@1": 4, "recall@5": 5, "mrr": 6, "accuracy": 6}
PRIMARY_ACTION = {"retrieve": "retrieve", "insert": "insert_update", "choice": "choice"}


def pick(pack, source, rows):
    """Record the pack's best method for this source; the runtime uses it as the default."""
    col = METRIC_COLUMN[pack.metric]
    scored = [(r[col], r[2]) for r in rows
              if r[1] == PRIMARY_ACTION[pack.action] and r[2] in pack.methods and r[2] not in pack.baselines]
    if not scored:
        return None
    best = max(scored)[1]
    picks_path = STATE / "picks.json"
    picks = json.loads(picks_path.read_text()) if picks_path.exists() else {}
    picks.setdefault(str(source.path) if source else "-", {})[pack.name] = best
    picks_path.parent.mkdir(parents=True, exist_ok=True)
    picks_path.write_text(json.dumps(picks, indent=2) + "\n")
    return best


def picked(pack, source):
    path = STATE / "picks.json"
    picks = json.loads(path.read_text()) if path.exists() else {}
    return picks.get(str(source.path) if source else "-", {}).get(pack.name, pack.default)
