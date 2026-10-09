---
name: wayfinder
description: Use when you need to find which notes or docs answer a question in a notes vault or docs folder (before grepping through it), or when deciding where new information should be written down (which existing note to add it to, or which folder a new note belongs in). Uses the wayfinder MCP tools retrieve and insert.
---

# wayfinder

Two read-only tools over a folder of markdown notes (an Obsidian vault, a `docs/` tree):

- `retrieve(query, source?, k?)`: the notes most likely to answer a question, best first, with each note's `description`.
- `insert(text, source?, k?)`: where new text belongs. It returns the existing notes it most likely extends, best first, plus `new_note_folder`, the folder to use if it should be a new note instead.

`source` is a configured name from `list_sources`, or any folder path. If you leave it out, the tools use the source that contains the current directory. Pass a path whenever you know which vault or docs folder you mean.

## Retrieve

Call `retrieve` before grepping a vault for something you would otherwise search by hand. Read the top results yourself; a score only ranks notes against each other within one call, so it is not a confidence. On real vaults, the note an agent ended up needing was in the top 5 about 60-75% of the time. Fall back to grep when the top 5 clearly miss.

## Insert

Call `insert` before writing new information down, then decide:

1. If one of the top notes is clearly where this belongs (same topic, and its description fits), add the text there.
2. Otherwise create a new note in `new_note_folder`.

`insert` only suggests; you do the write. The vault's own conventions still apply, and they win over the suggestion: frontmatter, index or MOC rows, inbox rules, links back to the project. Read the vault's README or home note if you don't know them. On real vaults the right existing note was in the top 5 about 88-97% of the time.

## Without the MCP server

The CLI gives the same answers: `wayfinder retrieve "question" --source PATH --json`, and `wayfinder insert - --source PATH --json < text.md`. If `wayfinder` is missing, the user installs it with `uv tool install "git+https://github.com/VolksRat71/wayfinder"`.
