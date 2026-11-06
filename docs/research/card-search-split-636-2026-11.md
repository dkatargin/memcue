# The card against search, on real prompts, November 2026 (after #636)

Status: **measured 2026-11-06 on the 50 prompts of #636, four arms, two repetitions each.** **Search carries the gain
of the memory; the card adds nothing measurable on top of it.**

[memory-baseline-636](memory-baseline-636-2026-11.md) found that memcue as installed scores +0.23 per prompt over a
session without memory, and that the global behaviour rules as plain text add nothing. It could not tell the two
other parts apart: the card (global and repository rules and decisions at session start) and the agent's own
search. This run takes each away in turn, and takes away the global part of the card alone.

In short:

- **Without search, the score drops.** The whole card with the agent's searches answered by an empty base scores 1.05
  of 2 on the 40 memory prompts against 1.24 for current: −0.19, 95% interval [−0.34, −0.03]. Its answers rest on
  knowledge of earlier sessions in 14 runs against 42.
- **Without the card, it does not.** Search with an empty card scores 1.22 against 1.24: −0.02 [−0.14, +0.11], 8
  wins, 22 ties, 10 losses. The session costs 5% less ($43.42 against $45.59 for 100 runs).
- **The global part alone is not settled.** A card without its global facts (15 facts instead of 45), with search,
  scores 1.11: −0.13 [−0.24, −0.02] against current, but −0.11 [−0.27, +0.03] against no card at all. Taking the
  whole card away does not hurt while taking a third of it away seems to; with four comparisons on one set of prompts,
  the second is as likely noise as a real effect.
- **Ordinary prompts move within the noise** in every arm (10 prompts).
- Recommendation: invest in search and in when the agent searches (#647), not in the card. Before the card shrinks or
  goes, measure what plan-mode answers cannot show: the behaviour rules (language, git workflow, what is never
  allowed) act on what the agent does, not on what it answers.

## Arms

Every arm is the setup of #636: one `claude -p --model opus` in plan mode on a clone of the prompt's repository as of
the prompt, the user's own `CLAUDE.md`, rules, settings and hooks, the memcue plugin with its session-start note, and
a throwaway copy of the base as of the prompt. The binary is the 0.28.0 tag with the research patch of #606
([card-keep.patch](scripts/card606e2e/card-keep.patch)); the runner is [run606.py](scripts/card606e2e/run606.py) with
`E2E_ARMS=card,search,noglobal`.

- **current**: the answers of the current arm of #636, graded again together with the three new arms. Same binary
  without the patch, which changes nothing without `MEMCUE_CARD_KEEP`; same snapshots and prompts.
- **card**: the whole card; the agent's own `memcue search` goes to an empty base with its own state
  ([search shim](scripts/card606e2e/search/memcue)), so every search answers that nothing matches. The searches of
  the user's program hook (#598) still read the session's base, as in current.
- **search**: an empty keep list, so the card carries no fact; the note still tells the agent to search, and search
  reads the base as in current.
- **noglobal**: a keep list of every fact not scoped global, so the card carries the repository's rules and decisions
  only (15 facts on average; no fact in 10 runs of 6 prompts, mostly in the Claude config directory); search as in
  current.

The plugin loaded in all 400 runs. In the card arm no search of the agent returned a fact. Two card runs started
without a line in `card.log`; their sessions show the card, in one of them smaller, as if a part of the session start
did not run.

## Results

300 new runs (50 prompts × 3 arms × 2 repetitions), no harness failure, $131.50; one search run stopped at the turn
limit and is graded as it answered. Graded by [grade606.py](scripts/card606e2e/grade606.py) as in #636, with the eight
answers of a prompt (four arms, two repetitions) under letters in a per-pass order; two passes, $9.98 and $10.00.

| arm | score | 2s | 0s | wrong | asks | past | searched | searches a run | card | cost |
|---|---|---|---|---|---|---|---|---|---|---|
| current | **1.31** | 42 | 14 | 9 | 48 | 42 | 71 of 100 | 2.2 | 45 facts | $45.59 |
| card | 1.14 | 31 | 19 | 12 | 42 | 14 | 72 of 100 | 2.2 | 44 facts | $45.07 |
| search | 1.28 | 35 | 12 | 8 | 45 | 38 | 79 of 100 | 2.5 | 0 | $43.42 |
| noglobal | 1.21 | 35 | 15 | 9 | 44 | 38 | 72 of 100 | 2.6 | 15 facts | $43.01 |

Score by group:

| arm | memory (40) | ordinary (10) |
|---|---|---|
| current | **1.24** | 1.60 |
| card | 1.05 | 1.48 |
| search | 1.22 | 1.55 |
| noglobal | 1.11 | 1.60 |

By prompt, each side the mean of its two repetitions, 95% bootstrap interval of the mean difference:

| pair | group | wins / ties / losses | mean diff | 95% interval |
|---|---|---|---|---|
| card − current | memory | 6 / 16 / 18 | −0.19 | [−0.34, −0.03] |
| search − current | memory | 8 / 22 / 10 | −0.02 | [−0.14, +0.11] |
| noglobal − current | memory | 4 / 19 / 17 | −0.13 | [−0.24, −0.02] |
| noglobal − search | memory | 6 / 19 / 15 | −0.11 | [−0.27, +0.03] |
| card − search | memory | 7 / 17 / 16 | −0.17 | [−0.36, +0.01] |
| card − current | ordinary | 3 / 4 / 3 | −0.12 | [−0.38, +0.10] |
| search − current | ordinary | 2 / 5 / 3 | −0.05 | [−0.17, +0.07] |
| noglobal − current | ordinary | 2 / 6 / 2 | +0.00 | [−0.15, +0.15] |

Noise: the grader gave the same score in both passes to 351 of 400 answers, with no 0↔2 flip. The two repetitions of
one arm differ on 12–18 of 50 prompts. Graded among eight answers instead of six, the current answers score 1.24 on
the memory prompts here and 1.21 in #636.

## What it means for the card

- The gain of #636 (+0.23 over no memory) comes through search: the card alone keeps a few points of it, and search
  alone keeps all of it.
- On these prompts the card neither adds to search nor saves the agent searches: with no card the agent searched in
  79 runs instead of 71, 2.5 times a run instead of 2.2, at 5% less cost.
- #637 (repository decisions that restate the tracker) and #645 (a profile instead of the global facts) both assume
  the card matters for answers. This run says it does not, measurably, for plan-mode answers. What it may matter for
  is behaviour, which this harness does not grade.

## Limits

- One run of 40 memory prompts and 10 ordinary ones, chosen as in #636; four comparisons on one set of prompts.
- Plan mode grades the answer, not the actions: whether the agent wrote the commit message in English, kept to the
  git workflow or avoided what the user forbade is not measured, and that is what most global rules are about.
- The search arm still had the session-start note that tells the agent to search; without it, search would run less.
- The current answers come from the #636 run, a few hours earlier, with the same binary, snapshots and prompts.
- Claude Code only.
