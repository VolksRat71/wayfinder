# wayfinder

Retrieve and insert for notes and repos, with an eval that picks the method from your own history.

- **retrieve**: which notes answer this question?
- **insert**: which existing note does this new text belong in, or which folder should a new note go in?

The eval mines what already happened (git history for inserts, Claude Code and Codex transcripts
for retrieve), scores each method against it, and `--pick` makes the winner your default. On the first
two vaults it was run on, plain BM25 plus recency beat embeddings and the Laya decision model.
In an agent race on those vaults, an agent using wayfinder found the right note as often as one
using grep (30/30 each), and 2× faster overall, 2.6× on questions whose answer isn't in a note's
title. See [docs/benchmarks.md](docs/benchmarks.md).

## Quick start

You need [uv](https://docs.astral.sh/uv/) (`brew install uv`) and git access to this private repo:
run `gh auth login && gh auth setup-git` once, or use an SSH key. A bare `GITHUB_TOKEN` is not enough.

```sh
# 1. The CLI. Everything else calls it.
uv tool install "git+https://github.com/VolksRat71/wayfinder"

# 2. Tell the agent server which notes it may read (it refuses to start without this):
cat >> ~/.config/wayfinder/config.toml <<'TOML'
[sources.notes]
path = "~/notes"
[mcp]
allow = ["notes"]
TOML

# 3. Your agent: Claude Code (inside a session) ...
/plugin marketplace add VolksRat71/wayfinder
/plugin install wayfinder@wayfinder
#    ... and/or Codex
codex plugin marketplace add VolksRat71/wayfinder && codex plugin add wayfinder@wayfinder

# 4. Optional: Obsidian (desktop), then enable "Wayfinder" under Settings > Community plugins
wayfinder obsidian-install ~/path/to/vault
```

Then point it at a folder of markdown notes:

```sh
wayfinder retrieve "how do we rotate the deploy keys" --source ~/notes
wayfinder eval --source ~/notes --pick     # optional: score the methods on your own history
```

**What it reads.** wayfinder itself sends nothing anywhere. Retrieve and insert read the notes
folder you point them at; when an agent calls them, the results (paths and note descriptions) go
into that agent's conversation like any other tool output. Only `wayfinder eval` reads more: the git history of that folder and your agent
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

## Isolation: restricted MCP mode

Keep separate vaults separate when agents use them, such as company docs, work and tech notes, and
personal-life notes. Each MCP server gets a fixed allowlist of sources from its operator config at
startup. **Tool arguments can only choose among those names; they can't add a source.**

Inside a restricted server:
- Every tool (`retrieve`, `insert`, `list_packs`, `run_pack`) only reads allowed sources, by
  **exact configured name**. Folder paths, `..` traversal, `~` and unknown or disallowed names are all
  refused with the same message, which lists only the allowed names. It never says whether a refused
  name exists elsewhere.
- `list_sources` lists only allowed sources. If exactly one source is allowed it's the default;
  with several, the agent must name one. There is no fallback to the current directory.
- Files are notes only if their real path is inside the source. Symlinks pointing out of it (file or
  folder) are skipped, and the check is repeated at read time. This applies in every mode.
- Each call re-checks its source. If the folder is gone, or its path now resolves somewhere else
  (for example, swapped for a symlink), that call fails. Nothing falls back to unrestricted access.
- An invalid allowlist (empty, a name that isn't configured, a missing folder) stops the server
  from starting.
- Unexpected errors reach the agent and the server log as one generic line, without a traceback,
  path or note text.
- Embedding caches are keyed by source, so vaults never share vectors.
- `insert` stays a read-only placement suggestion.

Choose the mode when you launch the server:

```sh
wayfinder mcp --allow company-docs --allow tech-notes   # restricted to these configured sources
wayfinder mcp --unrestricted                            # explicit local-dev mode: any folder path
wayfinder mcp                                           # uses [mcp] allow from the config;
                                                        # refuses to start if there is none
```

**Separate work and personal instances.** The strongest setup inside wayfinder is a separate config
file per instance, so the work server's config doesn't contain the personal vault at all:

```toml
# ~/.config/wayfinder/work.toml
[sources.company-docs]
path = "~/work/company-docs"
[sources.tech-notes]
path = "~/notes/tech"
[mcp]
allow = ["company-docs", "tech-notes"]
```

```toml
# ~/.config/wayfinder/life.toml
[sources.life-notes]
path = "~/notes/life"
[mcp]
allow = ["life-notes"]
```

Point each server at its own config: in Claude Code, a project-scoped `.mcp.json` per workspace;
in Codex, an entry in `~/.codex/config.toml`:

```json
{ "mcpServers": { "wayfinder-work": { "command": "wayfinder", "args": ["mcp"],
    "env": { "WAYFINDER_CONFIG": "${HOME}/.config/wayfinder/work.toml" } } } }
```

```toml
[mcp_servers.wayfinder-life]
command = "wayfinder"
args = ["mcp"]
env = { WAYFINDER_CONFIG = "/Users/you/.config/wayfinder/life.toml" }
```

The plugins' bundled server runs plain `wayfinder mcp` with the default config
(`~/.config/wayfinder/config.toml`), so that file needs an `[mcp] allow` (it's the "work" instance
above). Add other instances as your own server entries.

**Upgrading from 0.1.** In 0.1, `wayfinder mcp` with no allowlist ran unrestricted and printed a
warning. From 0.2 it refuses to start. Add `[mcp] allow` to your config, or use `--unrestricted`
for local development.

**What this does not protect.** These checks are defense in depth inside one process, not a
security boundary on their own:
- An agent with its own shell or file tools (Claude Code's Read/Bash, Codex's shell) can read
  anything your OS user can, whatever wayfinder allows. Restricted mode does not protect against
  such an agent.
- The CLI and the Obsidian plugin are run by you and stay unrestricted. `wayfinder eval` reads
  git history and your agent transcripts.
- Packs in `~/.config/wayfinder/packs/`, and repo packs you've marked `trust_packs`, are code you
  chose to run.
- For real isolation, also run each instance as its own process with its own config, and use OS
  or container filesystem permissions: a separate macOS user, or a container that mounts only
  the allowed folders, read-only.

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

@register("my-method")          # add requires="module" for optional deps
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
