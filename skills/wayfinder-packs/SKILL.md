---
name: wayfinder-packs
description: Use when creating, testing or evaluating a wayfinder pack (a custom retrieve/insert decision with its own dataset builder or ranking method), or when the user asks which wayfinder method works best on their own notes or repo.
---

# wayfinder packs

A pack is one decision: what to rank, how to build labelled eval data from history, and which methods to compare. `wayfinder eval` scores every method on the user's own history, and `--pick` makes the winner the runtime default. A method only earns its place by beating the plain baselines (`bm25`, `recent`, `bm25+recent`) on that data.

## Where packs live

- Built in: `notes-retrieve` and `notes-insert`.
- The user's packs: `~/.config/wayfinder/packs/<name>/`.
- Packs a repo ships: `<source>/.wayfinder/packs/<name>/`. A repo's `pack.py` is code, so it only runs if the user sets `trust_packs = true` for that source in `~/.config/wayfinder/config.toml`. Never set it for a repo the user hasn't reviewed.

## Writing one

`pack.toml`:

```toml
name = "my-pack"
description = "One line saying what this decides; agents read it via list_packs"
action = "retrieve"            # retrieve | insert
dataset = "my-builder"         # a built-in builder (git-inserts, transcript-reads) or one from pack.py
methods = ["bm25", "recent", "bm25+recent", "my-method"]
default = "bm25+recent"
metric = "mrr"                 # hit@1 | recall@5 | mrr
```

`pack.py` (optional):

```python
from wayfinder.data import builder
from wayfinder.methods import register

@builder("my-builder")
def build(source):
    # Return rows built from what already happened, never hand-written guesses:
    # {"query": str, "truth": [note paths relative to the source], "snapshot": "<commit sha>"}
    # The snapshot is the commit just before the event, so no method can see the future.
    ...

@register("my-method")
def my_method(corpus, query, notes):
    # notes: [(path, key)]; corpus.doc(path, key) is the text; corpus.age_days(path) is the recency.
    # Return [(path, score)], best first.
    ...
```

## Evaluating

```sh
wayfinder packs --source PATH                         # check the pack is found (or why it was skipped)
wayfinder eval --source PATH --pack my-pack           # score it
wayfinder eval --source PATH --pack my-pack --pick    # make the winner the default
```

Results are appended to `~/.local/share/wayfinder/results.tsv`. Report each method's hit@1, recall@5 and mrr against the baselines. Look at the `/unnamed` rows too: they drop queries that literally name the target file, which keyword search gets for free. Don't tune weights on a few dozen rows; that only fits the test set.
