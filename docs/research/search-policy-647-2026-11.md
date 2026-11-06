# When the agent searches, without a card, on real prompts, November 2026 (#647)

Status: **measured 2026-11-06 on the 50 prompts of #636, one new arm graded with three earlier ones, two repetitions
each.** **A note that has the agent fetch the user's rules and decisions at the start of a task replaces what the
card delivers, at no measurable cost to answers; it does not improve them.**

[card-search-split-636](card-search-split-636-2026-11.md) found that search carries the gain of the memory and that
the card adds nothing measurable to answers. The card has one job search does not do by itself: it hands the agent
the user's standing rules and decisions without being asked. This run tests a session-start note that gives that job
to search: no card, and an instruction to search the rules and decisions at the start of a task, with a short rule for
when to search at all.

In short:

- **Answers: the same.** The new note (rule) scores 1.21 of 2 on the 40 memory prompts, against 1.25 for memcue as
  installed (current) and 1.26 for search with the current note and no card (search): −0.04 [−0.18, +0.09] and −0.06
  [−0.18, +0.06]. All three stay well above no memory: rule +0.20 [+0.04, +0.38], current +0.24 [+0.07, +0.42].
- **Behaviour: the rules arrive by search.** With the new note the agent searched rules and decisions in 66 of 80
  memory runs, against 3 (current) and 4 (search); its first tool call was a search in 41 runs against 21 and 23, and
  only 6 memory runs went without any search, against 14 and 7.
- **Few extra searches on ordinary prompts.** On the 10 prompts that need no memory, 8 of 20 rule runs searched,
  against 5 and 6; 0.8 searches a run against 0.6.
- **Cost and time.** The cheapest of the three arms ($42.73 for 100 runs, against $45.59 and $43.42), with a median
  of 66 s against 60–61 s: the start-of-task search adds about a turn.
- **Search without the card scores the same as with it again** (+0.01 [−0.11, +0.14]), as in the split.
- Recommendation: a search-only memory is supported for answers. If the card goes, the note should carry the
  start-of-task search for rules and decisions, since that is the only way the standing rules still reach the agent
  unasked. No hint without fact text (arm C of the issue) is needed: missed searches on memory prompts are already
  6 of 80.

## Arms

Every arm is the setup of #636 and the split: one `claude -p --model opus` in plan mode on a clone of the prompt's
repository as of the prompt, the user's own `CLAUDE.md`, rules, settings and hooks, a throwaway copy of the base as of
the prompt.

- **current**: memcue 0.28.0 as installed, the card and the current note (answers of #636).
- **search**: the current note, no card (answers of the split).
- **rule** (new): no card, and a note that differs from the current one in three places
  ([note-rule-647.txt](scripts/card606e2e/note-rule-647.txt)):
  - the trigger of the first line: search "when the answer or the next step may depend on what an earlier session
    knew … Skip it when the user's message and the repository's files hold everything the task needs";
  - the card line becomes: "No card of rules arrives at session start … Before you start a task, and again when it
    turns to another system, run `memcue search -kind rule,decision "<words of the task>"` (add `-in global` for the
    rules that hold everywhere) and follow what applies";
  - the line on `-source user` no longer mentions the card.
- **none**: no memcue plugin and an empty base (answers of #636).

The rule arm runs the 0.28.0 tag with [card-keep.patch](scripts/card606e2e/card-keep.patch) and
[note-file.patch](scripts/card606e2e/note-file.patch) (`MEMCUE_NOTE_FILE` replaces the note), and the runner
[run606.py](scripts/card606e2e/run606.py) with `E2E_ARMS=rule`. The new note reached all 100 rule runs and no card did.

## Results

100 new runs, none failed, $42.73. Graded by [grade606.py](scripts/card606e2e/grade606.py) with the eight answers of a
prompt (four arms, two repetitions) under letters in a per-pass order; two passes, $9.95 and $9.92.

| arm | score | 2s | 0s | wrong | asks | past | searched | searches a run | median time | cost |
|---|---|---|---|---|---|---|---|---|---|---|
| current | **1.32** | 40 | 14 | 9 | 40 | 46 | 71 of 100 | 2.2 | 61 s | $45.59 |
| search | **1.32** | 39 | 11 | 8 | 40 | 42 | 79 of 100 | 2.5 | 60 s | $43.42 |
| rule | 1.26 | 36 | 13 | 6 | 47 | 45 | 82 of 100 | 2.9 | 66 s | $42.73 |
| none | 1.11 | 29 | 21 | 15 | 47 | 1 | 2 of 100 | 0.1 | 59 s | $40.48 |

| pair | group | wins / ties / losses | mean diff | 95% interval |
|---|---|---|---|---|
| rule − current | memory | 9 / 20 / 11 | −0.04 | [−0.18, +0.09] |
| rule − search | memory | 9 / 18 / 13 | −0.06 | [−0.18, +0.06] |
| search − current | memory | 10 / 21 / 9 | +0.01 | [−0.11, +0.14] |
| rule − none | memory | 14 / 19 / 7 | +0.20 | [+0.04, +0.38] |
| current − none | memory | 19 / 15 / 6 | +0.24 | [+0.07, +0.42] |
| rule − current | ordinary | 1 / 5 / 4 | −0.12 | [−0.30, +0.07] |
| rule − search | ordinary | 1 / 7 / 2 | −0.05 | [−0.20, +0.10] |

The agent's searches, by group (the program hook's searches left out):

| arm | group | runs that searched | searches a run | a rule,decision search | first tool a search | calls that returned facts |
|---|---|---|---|---|---|---|
| current | memory | 66 of 80 | 2.6 | 3 | 21 | 99 of 116 |
| search | memory | 73 of 80 | 3.0 | 4 | 23 | 120 of 137 |
| rule | memory | 74 of 80 | 3.4 | 66 | 41 | 129 of 154 |
| current | ordinary | 5 of 20 | 0.6 | 0 | 0 | 7 of 7 |
| search | ordinary | 6 of 20 | 0.6 | 1 | 2 | 7 of 7 |
| rule | ordinary | 8 of 20 | 0.8 | 5 | 2 | 9 of 9 |

Noise: the grader gave the same score in both passes to 359 of 400 answers, with no 0↔2 flip; the two repetitions of
one arm differ on 11–16 of 50 prompts.

## Questions of #647

- **Is a better instruction enough, or is a proactive signal worth its complexity?** The instruction is enough to make
  the agent search: memory prompts without any search fall to 6 of 80. No hint without fact text was built.
- **Does a decision rule improve answers?** No: −0.06 against the current note without a card, within the noise.
- **Spurious searches?** A few on ordinary prompts (8 of 20 runs against 5–6), each returning facts; no ordinary prompt
  scored measurably worse.
- **What it changes:** the standing rules reach the agent through a search it makes at the start of a task, which is
  what a search-only memory needs.

## Limits

- One run; plan mode grades answers, not actions, so whether the fetched rules change what the agent does is not
  measured. The rule-and-decision search is the mechanism; its effect on behaviour is an assumption.
- The rule arm ran a few hours after the others with the same binary, snapshots and prompts.
- Claude Code only. Hermes and DSH build their own card (session-card) and were not run.
