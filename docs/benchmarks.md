# Benchmarks

Measured 2026-10-09 on wayfinder 0.2.1 (`3b446b3`), on two private Markdown vaults:

- **Team docs:** a ~390-note engineering knowledge vault (git history since January 2026).
- **Tech notes:** a ~160-note personal tech and projects vault (git history since September 2026).

The question sets and note names stay private because they come from those vaults. This page gives the method and the aggregate results. Your numbers will differ, so run `wayfinder eval` on your own notes.

## Agent race: does wayfinder make an agent faster?

Two Claude subagents on the same model got the same questions and had to name the note that answers each one.

- **wayfinder racer:** only the `retrieve` MCP tool, plus `Read` to confirm a candidate.
- **grep racer:** only `Grep`, `Glob` and `Read`.

Both ran in parallel, under the same instructions and conditions. The answers were checked against notes verified by hand beforehand. A question counts as correct only if the racer named the right note, or one of the notes accepted for it.

There were two question sets, each split across both vaults:

- **Title-findable** (7 questions): the answer note has a descriptive title, which a filename search can match.
- **Body-level** (8 questions): the answer is a detail inside the note body. The questions are phrased so that no note title gives them away.

Four rounds: each set was run twice, with fresh agents each time.

| | Questions | Correct (wayfinder / grep) | Time, mean | Tokens, mean | Tool calls, mean |
|---|---|---|---|---|---|
| Title-findable | 14 | 14/14 / 14/14 | **20.6 s** vs 29.3 s (1.4× faster) | **80.0k** vs 99.3k (−19%) | 12.5 vs 15.0 |
| Body-level | 16 | 16/16 / 16/16 | **18.5 s** vs 47.5 s (2.6× faster) | **83.4k** vs 86.6k (−4%) | 14.0 vs 12.5 |
| All rounds | 30 | 30/30 / 30/30 | **19.6 s** vs 38.4 s (2.0× faster) | **81.7k** vs 92.9k (−12%) | 13.2 vs 13.8 |

What this shows:

- **Accuracy was a tie.** A capable agent with grep finds the right note too; wayfinder gets it there faster.
- **The less a note's title gives away, the bigger the speed gain.** On body-level questions, grep had to try one search term after another and read candidates, while one ranked `retrieve` call usually put the answer in the top results.
- **Token savings are modest.** Every agent carries a large fixed overhead (instructions and tool definitions) before it searches anything, so the share of the search work saved is larger than these totals show.

Limits: 30 questions over four rounds is a small sample. Times include model latency. Both vaults use descriptive filenames, which helps grep on title-findable questions.

## Offline eval: ranking quality from each vault's own history

`wayfinder eval` builds test questions from what already happened, then scores each ranking method against them:

- **Insert:** a git commit that added text to an existing note asks "which note does this text belong in?"
- **Retrieve:** a prompt in a Claude Code or Codex transcript asks "which notes did the agent then read?"

The candidates for each question are the notes that existed just before the event. Defaults: retrieve uses `bm25+recent`; insert uses `bm25-trunc5+recent`, which `--pick` chose on both vaults.

| Vault | Task | Questions | Right note ranked first | Right note in top 5 | Mean reciprocal rank |
|---|---|---|---|---|---|
| Team docs | insert into an existing note | 59 | 0.70 | 0.95 | 0.80 |
| Tech notes | insert into an existing note | 67 | 0.57 | 0.91 | 0.71 |
| Tech notes | retrieve | 95 | 0.34 | 0.70 | 0.52 |
| Tech notes | retrieve, prompt doesn't name the note | 63 | 0.22 | 0.60 | 0.40 |

Retrieve labels are noisy: "the agent read this note" doesn't always mean it was the answer. A baseline that ranks the most recently edited notes first, ignoring the question entirely, scores well on retrieve, because agents mostly read what's being worked on. wayfinder reports that baseline but never picks it as a default.

## What didn't win

- **Laya** (a ~400M-parameter local decision model) never beat a plain baseline in six tests. Those tests were:
  - picking a new note's folder without training (best: 60% correct on its most confident half, against a 90% bar)
  - re-ranking BM25's top results
  - deciding whether text should update an existing note or start a new one
  - triaging agent hand-offs
- **MiniLM embeddings with nearest neighbours** beat Laya but not BM25 on these vaults.

Both are available as optional extras, `wayfinder[embed,laya]`, so you can test them on your own notes.

## Reproduce

```sh
wayfinder eval --source ~/notes --pick     # offline eval and default selection
```

The race used the prompt below for each racer, with the tool line swapped: wayfinder `retrieve` plus `Read` for one racer, `Grep`, `Glob` and `Read` for the other. Durations, token totals and tool-call counts came from the agent run reports.

> You are racer A in a timed note-finding race. Find, for each question, the single note that best answers it. Speed and accuracy both count. TOOLS: use ONLY … Read-only. QUESTIONS: … Reply with exactly N lines: `<n> | <vault-relative path> | <confidence>`.
