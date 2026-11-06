# Raw session history after an empty memcue search: the Mac stage, November 2026 (#602)

Status: **measured 2026-11-03 on the author's Mac, the corpus #602 names.** Follows the Linux first stage of
[history-fallback-602](history-fallback-602-2026-11.md) with its scripts: the parser `sessions.py` and the checks of
`aggregate.py` ran unchanged; the labels are new ([label602.py](scripts/history602/label602.py)). Every example
below is invented; queries, windows and labels stay off the repository.

In short:

- **For 5 of the 14 empty searches that are certainly the agent's own, a plain word search over the transcripts older
  than the query found a passage that answers it.** Together with the first stage (2 of 7 interactive queries on the
  server) that is about a third of the agent's empty searches with an answer in history.
- **None of the 8 answers found was outdated**, by a newer window of the same search or by a fact the base holds now.
- **The cost is small and fixed**: at most five windows of about 400 characters, a median of 2,009 characters a query.
  The answering window was the first of the five in 3 of 9 cases and within the first three in 7.
- **Precision is low**: of the 50 windows of those 14 queries, 6 answer, 15 are related and 29 only share words.
- **Recommendation: build the command**, history framed as leads to check, text of the user and the agent only, newest
  first, five windows. A separate issue describes it.

## What was measured

### Earlier feasibility observation

The [#602 body](https://github.com/juev/memcue/issues/602) reports a **2 November** Mac survey: **1,480 transcripts /
2.4 GB**, with a plain `rg` scan taking **0.1–1.2 s**; oldest transcript **1 October**, retention about **30 days**
with no explicit `cleanupPeriodDays`. Its earlier log count was **6,731 searches / 579 empty (8%)**, including
automatic program-hook queries. This is distinct from the 7,015-search snapshot and filtered 50-query sample below;
neither the raw empty share nor the grep timing is the parser's answer yield or measured invocation latency.

### Queries

- **Source**: `search.log` on the Mac, 7,015 searches from 2026-10-25 to 2026-11-03, 657 of them empty. The log has no
  flags and no session, so the queries of the program hook (one word, a program name, and the arguments it misreads
  as one: file names, quoting, ticket ids) were told apart by shape: only queries of two words or more count. 58
  unique queries are left, from 2026-10-29 on.
- **Sample**: 50 of the 58, drawn with a fixed seed.
- **Strata**: a query whose `memcue search` command was found in a transcript is the agent's, and its own session is
  left out of the search (14). For the other 36 the session was not found (a session of another harness, a transcript
  Claude Code has deleted, or a query written with other quoting); their own session is not left out, so their numbers
  can be high.

### Search

`sessions.py --claude-dir ~/.claude/projects` over 1,065 transcripts (oldest from 2026-10-01: Claude Code keeps about
30 days): user and assistant text, without thinking, tool input, tool output, skill bodies, command echoes, task
notifications and the prompts of `claude -p` sessions. A message counts when it holds enough of the query's words;
the five newest matches before the query time give one 400-character window each. A second arm adds tool output.

### Labels

Opus through `claude -p`, one call a query: the query, its time, its windows newest first, and the facts the base holds
now for its words. Each window is A (answers), R (related) or N (noise); an answer is outdated by a newer window or by
a fact. Only the text arm was labelled: tool output carries secrets and fetched pages. $3.63.

## Results

`aggregate.py --answer-arm text`, labels bound to the exact windows:

| arm | stratum | queries | with a window | windows A/R/N | queries with an answer | answers outdated | median chars per window |
|---|---|---|---|---|---|---|---|
| text | agent | 14 | 10 | 6/15/29 | **5** | 0 | 402 |
| text | unattributed | 36 | 24 | 3/8/90 | 3 | 0 | 402 |
| tool | agent | 14 | 12 | not labelled | — | — | 402 |
| tool | unattributed | 36 | 35 | not labelled | — | — | 402 |

Tool output gives a window to more queries (47 of 50 against 34), at the same cost a query; whether those windows
answer was not measured.

## Questions of #602

1. **How often does a search over older transcripts answer an empty agent search?** 5 of 14 on the Mac, 2 of 7 on the
   server: small samples that agree on about a third.
2. **What does a useful find cost?** Five windows of about 400 characters, 2,009 a query at the median; with tool
   output the same per query. Under one percent of a session's context.
3. **How often is the find outdated?** None of the 8 answers here, against a newer window or a fact of the base.
4. **Hermes**: the first stage found `session_search` showing the same text for the two server answers it could check.

## Limits

- 14 certain agent queries. The third is a direction, not a rate.
- The queries were told apart by shape, not by a flag; a two-word query of the hook would count as the agent's.
- One labeller (Opus) and one pass.
- Transcripts older than about 30 days are gone; a fallback over history reaches back a month unless
  `cleanupPeriodDays` is raised.

## Implementation check and matching follow-up

[PR #631](https://github.com/juev/memcue/pull/631), for [#621](https://github.com/juev/memcue/issues/621), compared
the command's passages with this study's parser windows, including query times and excluded sessions:
**50 queries, 50 identical window lists in the same order, 0 differences**. On the author's laptop its parallel
reader searched **2.5 GB in about 1.3 s**, versus **7 s** one file at a time; repeat count was not reported.
This verifies window parity, not improved answers or a live agent's choice to invoke the fallback.

The later [#644 count](https://github.com/juev/memcue/issues/644#issuecomment-6681914723), **6 November**, inspected
all **151 labelled text windows from the 50-query sample**, including unattributed queries, using the word rule
of `history.Terms`. This differs from
the **50 windows of 14 certain agent queries** in the headline precision figure. It did not rerun retrieval.

| Label | Some query term matched a whole word | Terms matched only within longer words |
|---|---:|---:|
| Answer (9) | 9 | 0 |
| Related (23) | 17 | 6 |
| Noise (119) | 53 | 66 |

The **66** noise windows with only within-word matches included **32** with a match inside a word rather than
at its start (**24** with no other match kind), **33** at the start of a longer word, **9** before an underscore,
dot or hyphen, and **1** Russian inflection with an ending of up to four letters. Categories overlap. The related
counts were **2** middle matches (**1** exclusive), **4** word-start matches and **2** identifier-boundary matches.

Exact boundaries could remove up to **66 noise / 6 related** windows; a word-start boundary could remove the
**24 noise / 1 related** windows matching only in the middle, with **0 answer windows** removed from this sample.
These are estimates on returned windows. Freed places could be filled by different windows, so neither table proves
a retrieval-quality improvement. The planned current-versus-word-start rerun was not performed in the snapshot.
The [maintainer closed #644](https://github.com/juev/memcue/issues/644#issuecomment-6687588869) with the current
matcher retained; reconsideration was left possible if fallback noise became material.

## DSH history: feasibility only

The [#630 comment](https://github.com/juev/memcue/issues/630#issuecomment-6687575312), **6 November**, surveyed
**97 DSH sessions / 69 MB**, **37** in journal v3 and **60** in v4; **13** journal files had been written since
30 October, newest on 5 November. Journals are zstd-compressed JSON lines, with one directory per project and session.
The recorded v4 envelope has `seq`, `time`, `type`, `data`, following a session header. No private journal text is
included here. This was a format/volume survey, not a measured DSH answer yield or an implemented reader.
The choice between a zstd dependency and an external command was deferred; #630 remained open at the archive cutoff.
