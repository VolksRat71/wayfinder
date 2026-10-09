# wayfinder

Retrieve and insert for notes and repos, with an eval that picks the method from your own history.

- **retrieve**: which notes answer this question?
- **insert**: which existing note does this new text belong in, or which folder should a new note go in?

The eval mines what already happened (git history for inserts, Claude Code and Codex transcripts
for retrieve), scores each method against it, and `--pick` makes the winner your default. On the first
two vaults it was run on, plain BM25 plus recency beat embeddings and the Laya decision model.

## Quick start

You need [uv](https://docs.astral.sh/uv/) (`brew install uv`) and git access to this private repo:
run `gh auth login && gh auth setup-git` once, or use an SSH key. A bare `GITHUB_TOKEN` is not enough.

```sh
# 1. The CLI. Everything else calls it.
uv tool install "git+https://github.com/VolksRat71/wayfinder"

# 2. Your agent: Claude Code (inside a session) ...
/plugin marketplace add VolksRat71/wayfinder
/plugin install wayfinder@wayfinder
#    ... and/or Codex
codex plugin marketplace add VolksRat71/wayfinder && codex plugin add wayfinder@wayfinder

# 3. Optional: Obsidian (desktop), then enable "Wayfinder" under Settings > Community plugins
wayfinder obsidian-install ~/path/to/vault
```

Then point it at a folder of markdown notes:

```sh
wayfinder retrieve "how do we rotate the deploy keys" --source ~/notes
wayfinder eval --source ~/notes --pick     # optional: score the methods on your own history
```

**What it reads.** Everything stays on your machine. Retrieve and insert read the notes folder you
point them at. Only `wayfinder eval` reads more: the git history of that folder and your agent
transcripts (`~/.claude/projects`, `~/.codex/sessions`), which it uses to build its test
questions. It writes results to `~/.local/share/wayfinder/` and `~/.local/state/wayfinder/`.

**Upgrade.** Run `uv tool upgrade wayfinder`, `/plugin marketplace update wayfinder` then
`/plugin update wayfinder@wayfinder`, and `codex plugin marketplace upgrade wayfinder`, and
re-run `obsidian-install` for each vault.
**Remove.** Run `uv tool uninstall wayfinder`, `/plugin uninstall wayfinder@wayfinder`,
`codex plugin remove wayfinder`, and delete `<vault>/.obsidian/plugins/wayfinder/`.

The optional Laya and MiniLM methods pull in torch (several GB):
`uv tool install "wayfinder[embed,laya] @ git+https://github.com/VolksRat71/wayfinder"`.

## What each surface does

### Agents (Claude Code, Codex)

The plugins add read-only MCP tools (`retrieve`, `insert`, `list_sources`, `list_packs`, `run_pack`) and two skills: `wayfinder` (when to retrieve or insert, and how to read the results) and `wayfinder-packs` (how to write and evaluate a pack). `insert` only suggests. The agent does the write and follows your notes' own conventions.

### Obsidian (desktop)

Two commands, which work on the selection, or on the whole note if nothing is selected:
- **Related notes** opens the notes that best match.
- **Where does this go?** lists the existing notes this text belongs in, plus a folder for a new note.

The plugin calls the local CLI: there is no server and no network use. It looks for the CLI in `~/.local/bin`, `/opt/homebrew/bin` or `/usr/local/bin`. A custom path set in its settings is stored on that device only, never in the vault, so a synced or committed vault can't change which program runs.

## Use

```sh
wayfinder retrieve "how do we rotate the deploy keys" --source ~/notes
wayfinder insert "Deploy keys rotate every 90 days; the runbook is ..." --source ~/notes
echo "long text" | wayfinder insert - --source ~/notes --json
```

`--source` takes a configured name or any folder; by default it's the configured source containing the current directory, or the current directory itself. `insert` only suggests, so you or the agent do the write.

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
action = "retrieve"            # retrieve | insert | choice
dataset = "my-builder"         # registered with @builder in pack.py
methods = ["bm25", "bm25+recent", "my-method"]
default = "bm25+recent"
metric = "mrr"                 # hit@1 | recall@5 | mrr | accuracy, what --pick maximises
baselines = ["recent"]         # scored for comparison, never picked
# choice packs classify text instead of ranking notes:
# labels = { follow_up = "needs more work or a decision", done = "accepted as delivered" }
# per_source = false           # data doesn't depend on a source; evaluated once
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

`examples/packs/handback-triage/` is a complete outside pack: it labels every Claude Code
subagent handback by whether the lead later followed up, and compares a keyword baseline with
two Laya questions. Try it with
`ln -s "$PWD/examples/packs/handback-triage" ~/.config/wayfinder/packs/ && wayfinder eval --pack handback-triage`.
On one user's 368 handbacks, nothing beat always answering "done" (0.73): a useful negative result.

## Develop

```sh
uv venv && uv pip install -e ".[embed,laya,dev]" && .venv/bin/pytest -q
uv tool install -e .                 # put the dev checkout's `wayfinder` on PATH for the plugins
claude --plugin-dir .                # try the Claude plugin from the checkout; `claude plugin validate .` checks manifests
codex plugin marketplace add .       # try the Codex plugin from the checkout
cd obsidian && npm install && npm test   # build the Obsidian plugin into src/wayfinder/obsidian_plugin/ and smoke-test it
```

**Releasing.** Plugin caches are keyed by version, so a change only reaches teammates when the
version goes up. Bump it in all four places together: `pyproject.toml`, `.claude-plugin/plugin.json`,
`.codex-plugin/plugin.json` and `src/wayfinder/obsidian_plugin/manifest.json`.
