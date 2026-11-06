# Memory against no memory, on real prompts, November 2026 (#636)

Status: **measured 2026-11-06 on 40 prompts that need memory and 10 that do not, three arms, two repetitions each.**
**The memory pays: +0.23 per prompt, 95% interval [+0.07, +0.39], against a session without memcue.**

The question of #636: every card change since #606 was measured against the card before it, and nothing measured
what the memory as a whole gives. This run puts memcue 0.28.0 as installed (the note, the card, search, the facts)
against a session without memcue, and against a session that gets only the global behaviour rules as plain text.

In short:

- **On the 40 prompts that need memory, current scores 1.21 of 2, none 0.97.** By prompt, current wins 19, ties 16
  and loses 5; the mean difference is +0.23, 95% interval [+0.07, +0.39].
- **The behaviour rules alone give nothing measurable.** note scores 1.00 on the same prompts: +0.03 [−0.07, +0.12]
  over none, −0.21 [−0.36, −0.06] under current. The user's own `CLAUDE.md` and rules, present in every arm, already
  carry what those rules say; the gain comes from the rest of memcue: the repository part of the card and search.
- **No harm on ordinary prompts.** On 10 prompts with complete local instructions, current scores 1.62, none 1.60:
  +0.03 [−0.17, +0.20]. Ten prompts can show only a large harm, and there is none.
- **The cost is small.** A session with memcue costs $0.46 against $0.40 without (+13%), with the same median time
  and nearly the same turns and tool calls. The dream's cost is not part of this run.
- **Decision by the rule fixed before the run:** the memory pays. #637 and #638 go on as cost cuts, with this run as
  the reference. A plain-text profile of the user's rules (#645) starts from the finding that such rules add nothing
  over the user's own instructions here.

## Arms

Every arm is one `claude -p --model opus` in plan mode on a clone of the prompt's repository as of the prompt, with
the user's own `CLAUDE.md`, rules, settings and hooks, as in #606 and #623. The runner is
[run606.py](scripts/card606e2e/run606.py) with `E2E_ARMS=current,none,note`; the binary is `main` at the 0.28.0 tag,
built with the plugin's version and without the research patch of #606.

- **current**: the memcue plugin with its session-start note, the card of 0.28.0, the agent's own `memcue search`
  over a throwaway copy of the base as of the prompt.
- **none**: no memcue plugin (`enabledPlugins` off for the run) and an empty base. The user's own PreToolUse hook that
  runs `memcue search` for a command's program (#598, #635) runs in every arm; on the empty base it finds nothing.
- **note**: none plus the active global facts that the dream labelled `behaviour`, as of the prompt, given once at
  session start as a plain list by a SessionStart hook of the run's settings: 23–30 facts, 4,800–6,300 characters.

The memcue plugin loaded in all 100 current runs and in none of the others; the note text reached all 100 note runs
and no other; every current run started with a card (45 facts on average).

## Prompts

- **Memory: the 40 prompts of #606** (see [card-trim-606](card-trim-606-2026-11.md#prompts)), with their references.
  They were chosen as prompts that may need what the person decided or set up in earlier sessions, so this half
  favours memory.
- **Ordinary: 10 prompts from the same pool** of #606 that its filter judged standalone tasks not needing memory,
  picked by hand: questions answerable from the repository without the network, at most two a repository, 7
  repositories (one of them a work repository, one the Claude config directory). Prompts that need the network (a pull
  request to review, a ticket, a new upstream release) were left out: plan mode without network fails them in every
  arm alike.
- The prompts carry their group in `prompts.json`, and [grade606.py](scripts/card606e2e/grade606.py) reports each pair
  by group (`E2E_PAIRS=current-none,note-none,note-current`).

Prompt texts, references, answers and facts stay out of the repository.

## Isolation

As in #606: an empty clone that fetches only the history up to the prompt, a snapshot of the text history without the
versions created after the prompt, shims that refuse the network and writes, the file tools denied the live
repositories and the base.

- One prompt's linked worktree had been removed since #606, so its first 6 runs failed before the session started.
  The runner now clones the repository's root when the prompt's directory is gone, and the 6 runs were run again.
- 54 of 300 runs named a live path in a Bash command (18 current, 16 none, 20 note). The shims and the deny list
  refused nearly all of it; 1 current run got a directory listing back.
- In 4 runs on the memcue repository itself, the none and note agents learnt of memcue from the code and called
  `memcue search`; the base was empty and returned nothing.
- A relabel keeps the creation time of a fact, so a snapshot shows the `behaviour` labels and scopes set after the
  prompt; current and note share that.

## Results

300 runs (50 prompts × 3 arms × 2 repetitions), none failed, $130.37. Graded by
[grade606.py](scripts/card606e2e/grade606.py): one Opus call a prompt reads the prompt, the reference and the six
answers under letters in a per-pass order; two passes, $8.81 and $8.85. A flag counts when both passes raise it; a
score is the mean of the two.

| arm | score | 2s | 0s | wrong | asks | past | turns | tools | cost | median time | searched | card |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| current | **1.29** | 39 | 16 | 13 | 41 | 41 | 11.5 | 10.5 | $45.59 | 61 s | 71 of 100 | 45 facts |
| none | 1.10 | 27 | 20 | 15 | 45 | 1 | 10.7 | 10.2 | $40.48 | 59 s | 2 of 100 | — |
| note | 1.11 | 23 | 17 | 16 | 47 | 2 | 11.6 | 10.6 | $44.30 | 60 s | 2 of 100 | — |

Score by group:

| arm | memory (40) | ordinary (10) |
|---|---|---|
| current | **1.21** | 1.62 |
| none | 0.97 | 1.60 |
| note | 1.00 | 1.57 |

By prompt, each side the mean of its two repetitions, 95% bootstrap interval of the mean difference (5,000
resamples):

| pair | group | wins / ties / losses | mean diff | 95% interval |
|---|---|---|---|---|
| current − none | memory | 19 / 16 / 5 | **+0.23** | [+0.07, +0.39] |
| current − none | ordinary | 2 / 7 / 1 | +0.03 | [−0.17, +0.20] |
| note − none | memory | 8 / 25 / 7 | +0.03 | [−0.07, +0.12] |
| note − none | ordinary | 2 / 5 / 3 | −0.03 | [−0.23, +0.17] |
| note − current | memory | 6 / 13 / 21 | −0.21 | [−0.36, −0.06] |
| note − current | ordinary | 2 / 5 / 3 | −0.05 | [−0.23, +0.12] |

Noise: the grader gave the same score in both passes to 263 of 300 answers, with no 0↔2 flip. The two repetitions of
one arm differ on 14 (current), 13 (none) and 16 (note) of 50 prompts.

The `past` flag (the answer rests on knowledge of earlier sessions that the repository does not hold) is raised on 41
current answers and on 1–2 of the others: the score difference comes with answers that use what memcue holds.

## Decision

The rule of #636, with the gap closed as noted in the issue before the run:

- **current − none: mean +0.23, interval [+0.07, +0.39], above zero and above +0.15** → the memory pays. #637 and
  #638 go on as cuts of what it costs, each measured against this run.
- **note within −0.05 of current?** No: −0.21 [−0.36, −0.06]. The static rules do not carry the gain. On these
  prompts the behaviour rules as text are worth no more than the user's own instructions; what memcue adds is the
  repository part of the card and search, which this run does not separate.
- **Ordinary prompts:** no measurable harm from memory.

## Limits

- One run; the memory half was chosen as prompts that need memory, so the gain in daily work is smaller than +0.23,
  and the ordinary half (10 prompts) shows only a large harm.
- The prompts are from eight days of one person's work; the references come from sessions that had every tool and
  that day's state.
- Plan mode, without network and without writes, answers what the agent would do, not whether the task got done.
- The run does not tell the repository part of the card from search: both are in current, neither is in note.
- The running cost of the memory is more than the sessions: the dream and the card's share of every session start
  are not measured here.
- Claude Code only.
