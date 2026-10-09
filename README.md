# wayfinder

Retrieve and insert for notes and repos, with an eval that picks the method from your own history.

- **retrieve**: which notes answer this question?
- **insert**: which existing note does this new text belong in, or which folder should a new note go in?

The eval mines what already happened (git history for inserts, Claude Code transcripts for
retrieve), scores each method against it, and `--pick` makes the winner your default. On the first
two vaults it was run on, plain BM25 plus recency beat embeddings and the Laya decision model.

## Install

```sh
uv tool install "git+https://github.com/VolksRat71/wayfinder"            # base: no ML dependencies
uv tool install "wayfinder[embed,laya] @ git+https://github.com/VolksRat71/wayfinder"   # optional methods
```

The repo is private, so `git` must already be able to reach it (`gh auth login && gh auth setup-git`, or an SSH key).

## Evaluate on your own data

```sh
wayfinder eval --source ~/notes          # any folder inside a git repo; zero config
wayfinder eval --pick                    # every source in ~/.config/wayfinder/config.toml
```

Results are appended to `~/.local/share/wayfinder/results.tsv`, and picks are stored in `~/.local/state/wayfinder/picks.json`.
See `examples/config.toml` for excludes, folder descriptions and extra transcript read roots,
and `examples/com.example.wayfinder-eval.plist` to run it weekly.

## Packs (extensions)

A pack is one decision: what to rank, how to build its eval data from history, and which methods
to compare. Built-in: `notes-retrieve`, `notes-insert`. Add your own as a folder holding
`pack.toml` and an optional `pack.py`, in `~/.config/wayfinder/packs/` or in a source's
`.wayfinder/packs/` (so a team can ship packs inside a repo). A repo's `pack.py` is code, so it
only runs for a source with `trust_packs = true` in your config; untrusted repo packs are skipped.

```toml
name = "my-pack"
description = "What this decides, for agents reading list_packs"
action = "retrieve"            # retrieve | insert
dataset = "my-builder"         # registered with @builder in pack.py
methods = ["bm25", "bm25+recent", "my-method"]
default = "bm25+recent"
metric = "mrr"                 # hit@1 | recall@5 | mrr, what --pick maximises
```

```python
# pack.py
from wayfinder.data import builder
from wayfinder.methods import register

@builder("my-builder")
def build(source):             # -> [{"query", "truth": [paths], "snapshot": commit}]
    ...

@register("my-method")
def my_method(corpus, query, notes):   # -> [(path, score)] best first
    ...
```

## Develop

```sh
uv venv && uv pip install -e ".[embed,laya,dev]" && .venv/bin/pytest -q
```
