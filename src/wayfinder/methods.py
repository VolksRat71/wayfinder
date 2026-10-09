"""Ranking methods. Each is `method(corpus, query, notes) -> [(rel_path, score)]`, best first.

  bm25         keyword baseline
  recent       most recently edited first (no text at all)
  bm25+recent  BM25 (scaled to 0-1) + RECENCY_WEIGHT * recency
  bm25+links   BM25 (scaled to 0-1) + 1 for notes the query [[links]] to
  bm25-trunc5, bm25-trunc5+recent  the same with every word cut to its first 5 letters, so
               "parameters" meets "params" and "deploys" meets "deployment"
  minilm       all-MiniLM-L6-v2 cosine similarity           (extra: wayfinder[embed])
  bm25+laya    BM25 shortlist re-ranked by a Laya `choice`   (extra: wayfinder[laya])

Packs add their own with `@register("name")` in pack.py.
"""
import collections
import functools
import math
import os
import re
from pathlib import Path

K, SHORTLIST = 5, 10
# ponytail: fixed, untuned weights; tuning on this little data would just fit the test set.
RECENCY_WEIGHT, RECENCY_DAYS = 0.5, 7
TOKEN = re.compile(r"\w+")
WIKILINK = re.compile(r"\[\[([^\]|#]+)")
METHODS = {}


def register(name):
    def add(fn):
        METHODS[name] = fn
        return fn
    return add


@functools.lru_cache(maxsize=None)
def _tokens(text, cut=None):
    return [t[:cut] for t in TOKEN.findall(text.lower())]


@register("bm25")
def bm25(corpus, query, notes, k1=1.5, b=0.75, cut=None):
    docs = [_tokens(corpus.doc(rel, key), cut) for rel, key in notes]
    avg = sum(len(d) for d in docs) / max(len(docs), 1)
    df = collections.Counter(t for d in docs for t in set(d))
    q = set(_tokens(query, cut))
    scores = []
    for (rel, _), d in zip(notes, docs):
        tf = collections.Counter(d)
        s = sum(math.log(1 + (len(docs) - df[t] + .5) / (df[t] + .5)) * tf[t] * (k1 + 1)
                / (tf[t] + k1 * (1 - b + b * len(d) / avg)) for t in q if t in tf)
        scores.append((rel, s))
    return sorted(scores, key=lambda x: -x[1])


def _scaled_bm25(corpus, query, notes, cut=None):
    ranked = bm25(corpus, query, notes, cut=cut)
    top = ranked[0][1] if ranked and ranked[0][1] > 0 else 1
    return {rel: s / top for rel, s in ranked}


def _recency(corpus, rel):
    return math.exp(-corpus.age_days(rel) / RECENCY_DAYS)


@register("recent")
def recent(corpus, query, notes):
    return sorted(((rel, _recency(corpus, rel)) for rel, _ in notes), key=lambda x: -x[1])


@register("bm25+recent")
def bm25_recent(corpus, query, notes):
    base = _scaled_bm25(corpus, query, notes)
    return sorted(((rel, s + RECENCY_WEIGHT * _recency(corpus, rel)) for rel, s in base.items()), key=lambda x: -x[1])


@register("bm25-trunc5")
def bm25_trunc5(corpus, query, notes):
    return bm25(corpus, query, notes, cut=5)


@register("bm25-trunc5+recent")
def bm25_trunc5_recent(corpus, query, notes):
    base = _scaled_bm25(corpus, query, notes, cut=5)
    return sorted(((rel, s + RECENCY_WEIGHT * _recency(corpus, rel)) for rel, s in base.items()), key=lambda x: -x[1])


@register("bm25+links")
def bm25_links(corpus, query, notes):
    linked = {l.strip().lower() for l in WIKILINK.findall(query)}
    base = _scaled_bm25(corpus, query, notes)
    return sorted(((rel, s + (rel[:-3].lower() in linked or Path(rel).stem.lower() in linked))
                   for rel, s in base.items()), key=lambda x: -x[1])


# --- optional: embeddings ----------------------------------------------------------------------

MINILM = "sentence-transformers/all-MiniLM-L6-v2"
_vectors = {}


@functools.cache
def _minilm_model():
    from transformers import AutoModel, AutoTokenizer
    return AutoTokenizer.from_pretrained(MINILM), AutoModel.from_pretrained(MINILM).eval()


def embed(texts):
    import torch
    tok, model = _minilm_model()
    out = []
    with torch.no_grad():
        for i in range(0, len(texts), 32):
            batch = tok(texts[i:i + 32], padding=True, truncation=True, max_length=256, return_tensors="pt")
            hidden = model(**batch).last_hidden_state
            mask = batch["attention_mask"].unsqueeze(-1)
            out.append(torch.nn.functional.normalize((hidden * mask).sum(1) / mask.sum(1), dim=-1))
    return torch.cat(out)


@register("minilm")
def minilm(corpus, query, notes):
    import torch
    # Keyed by source too: two vaults can hold the same relative path with the same mtime
    # (a copied note), and must never share each other's vectors.
    scope = str(getattr(getattr(corpus, "source", None), "path", ""))
    keys = [(scope, *n) for n in notes]
    missing = [(k, n) for k, n in zip(keys, notes) if k not in _vectors]
    if missing:
        for (key, _), vec in zip(missing, embed([corpus.doc(*n) for _, n in missing])):
            _vectors[key] = vec
    sims = (torch.stack([_vectors[k] for k in keys]) @ embed([query])[0]).tolist()
    return sorted(zip((rel for rel, _ in notes), sims), key=lambda x: -x[1])


# --- optional: Laya ----------------------------------------------------------------------------

def _device():
    if os.environ.get("WAYFINDER_DEVICE"):
        return os.environ["WAYFINDER_DEVICE"]
    import torch
    return "mps" if torch.backends.mps.is_available() else "cpu"


@functools.cache
def router():
    from laya import Router
    return Router(device=_device())


def laya_choice(state, criteria, instructions):
    ans = router().predict(state, {"q": {"type": "choice", "instructions": instructions, "criteria": criteria}},
                           model="english", head_max_len=512)["answers"]["q"]
    return ans["probabilities"]


def laya_noul(state, instructions):
    return router().predict(state, {"q": {"type": "noul", "instructions": instructions}},
                            model="english")["answers"]["q"]["noul"]


@register("bm25+laya")
def bm25_laya(corpus, query, notes):
    ranked = bm25(corpus, query, notes)
    head, tail = ranked[:SHORTLIST], ranked[SHORTLIST:]
    keys = dict(notes)
    options = {f"o{i}": corpus.option(rel, keys[rel]) for i, (rel, _) in enumerate(head)}
    probs = laya_choice(query, options, "Which note is most relevant?")
    return sorted(((rel, probs.get(f"o{i}", 0)) for i, (rel, _) in enumerate(head)), key=lambda x: -x[1]) + tail


def available(name):
    """Whether a method's optional dependencies are installed."""
    need = {"minilm": "transformers", "bm25+laya": "laya"}.get(name)
    if not need:
        return True
    import importlib.util
    return importlib.util.find_spec(need) is not None
