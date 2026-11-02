# Raw session history after an empty memcue search: a local first stage, November 2026 (#602)

Status: **first stage only, measured 2026-11-02 on copies of one Linux server's history. The Mac corpus that #602
names was not available, so no Mac criterion is met. The semantic labels are the research agent's own and were not
verified by anyone else.** Every example below is invented; the real queries, windows and labels stay private.

#602 asks whether a parser over raw transcripts, with no index, finds answers that `memcue search` missed, and
whether Hermes `session_search` already covers it. The Mac corpus the issue describes (1,480 Claude Code transcripts,
579 empty searches in `search.log`) does not exist on this server. Here only Hermes ran memcue searches as an agent, so
the measured population is Hermes's empty `memcue_search` calls. The Claude Code transcripts on this server are
searched with the same queries as a separate arm; that arm is a different population from the Mac's.

In short:

- **Empty agent searches here: 23 of the 418 `memcue_search` calls that returned a facts list (Oct 19 – Nov 2), all
  unique.** Seven are ordinary interactive work, 14 are cron runs, and 2 come from sessions where the author was
  testing memcue itself. That is fewer than the 50 the issue asks for, and nothing was mixed in to reach it.
- **By the author's labels, the parser over Hermes history found an answer for 2 of the 7 interactive queries and for
  1 of the 2 memcue-test queries; for these 14 cron queries it found none.** Seven queries are an observation, not a
  rate.
- **For the two interactive queries, `session_search` shows the same answering text**, after a filter that drops
  every message written at or after the query. For the third query, the answering message is cut in one place and
  absent in the other, so whether `session_search` covers it is **unknown**.
- **Cost is described, not ranked**: on the same 7 interactive queries the parser shows a median of 1,811 characters
  per query, and `session_search` 6,138 after the filter. The units differ (400-character windows against whole shown
  messages), so the numbers do not say which is more efficient.
- **The Claude Code transcripts on this server answered none of the queries** (0 answers in 23 labelled windows).
- **Recommendation: defer the command.** Seven interactive queries from one server cannot decide it, and the Mac
  corpus, which has no `session_search`, was not measured.

## What was measured

### Queries

- **Source**: a copy of Hermes `state.db`, taken with the SQLite backup API. A query is an assistant `tool_call` to
  `memcue_search` whose tool response is JSON with `"facts": []`. The hook that searches by program name never goes
  through a tool call, so none of its queries can enter. All 431 calls have a JSON response: 7 are errors, 6 are an
  object without `facts`, 395 found facts and 23 found none (418 with a facts list). Six calls have two tool responses;
  the first counts.
- **Search log**: `search.log` of the same base holds 520 searches since Oct 24 and 46 empty ones. Of the 46, 43 are
  the same Hermes calls, most of them twice: on an empty answer the plugin searches once more with the score floor off.
  The other three have no session and a one-word query: the program-name hook of a Claude Code container. The log
  cannot tell an agent query from a hook query, so the sample comes from tool calls, not from the log.
- **Strata**, fixed before any search ran: `cron` and `subagent` by session source, `delegated` by
  `model_config._delegate_from`, `memcue-session` when the session title names memcue, `interactive` otherwise. Repeats
  would have kept the earliest; there were none.
- **Time**: each query keeps the time of its tool call. A message at or after that time is not history yet.

The empty share in this sample is 5.5% of the calls with a facts list (23 of 418). The Mac's 8% counts hook queries
and plugin repeats too, so the two numbers do not compare.

### Corpora

| arm | what | messages kept | span |
|---|---|---|---|
| hermes-text | Hermes user and assistant text | 1,871 | Oct 16 – Nov 2 |
| hermes-tool | the same plus tool output (cost only, not labelled) | 27,106 | Oct 16 – Nov 2 |
| claude-local | Claude Code transcripts of this server's delegated `claude -p` runs | 2,064 | Oct 16 – Nov 2 |
| claude-host | Claude Code transcripts of the host's interactive sessions | 24 | Oct 9 – Oct 29 |

The query's own session and its parents are left out: their text is in the context or was summarised into it.

### The parser

[`scripts/history602/sessions.py`](scripts/history602/sessions.py), standard-library Python, no index:

- **Kept**: user and assistant text. **Left out**: tool output (unless `--include-tool-output`), thinking,
  `tool_use` inputs, compaction summaries, skill bodies (`isMeta`), command echoes, task notifications, embedded
  system reminders, and Hermes's process notices, cron deliveries, system notes and delegation results. The quote of
  a Hermes reply is stripped before the body is judged. A user message in a cron, subagent or delegated session, or
  in a Claude Code `sdk-cli` or sidechain session, is a prompt written by a program and is left out as well. Rewound
  Hermes rows (`active=0, compacted=0`) are left out; compacted rows stay.
- **Query**: lowercase words, stop words dropped. A message matches when it holds 1 of 1 word, 2 of 2–4, or half of
  5 or more. Matches go newest first, one window per message, five per query; a window repeating a newer one is skipped.
  A window is at most 400 characters around the spot with the most query words.
- **Input checks**: a query needs a unique string id, a finite time with a zone and a list of session ids to leave
  out; a Hermes copy needs `parent_session_id`. A failed check stops the run before any output exists.
- **Output**: a new directory, 0700, files 0600; stdout carries counts only. The Hermes copy opens read-only and
  immutable.

40 tests on invented transcripts cover the time bound, future messages, machine text, wrapped machine text, schema
errors, invalid query files, window bounds, duplicates, permissions, the `session_search` wrapper and the aggregate's
bindings, including a stale or contaminated comparison and non-finite or negative counts. Ten mutants of the first parser were run against the first 24 tests: nine failed the suite, and the tenth
(thinking blocks) is equivalent to the original.

**Defects found on the way.** Hermes wraps the result of a background delegation as a user message,
`[ASYNC DELEGATION BATCH COMPLETE …]`, and the first filter did not know it: 14 of 52 Hermes windows of the first run
were machine text. The filter was fixed with a test that failed first, and the arm was run again; the selection and
the query rule did not change. A survey of all interactive user messages then found three more envelope kinds. A code
review later found that a machine body inside a reply quote got through; that was fixed too, and the run after it
gave the same windows as before. Machine text that carries no known marker would still get through.

### `session_search`

[`scripts/history602/hermes_session_search.py`](scripts/history602/hermes_session_search.py) imports and runs the
installed Hermes tool with the Hermes interpreter, on a second copy of `state.db`, with `HOME` and `HERMES_HOME` in an
empty scratch directory. Hermes reports its package version as 0.0.0, so the modules are identified by SHA-256:

| module | SHA-256 |
|---|---|
| `tools/session_search_tool.py` | `8ed4f3e49c70cc0723254f8dc81eaf8ea69733a22c32c1a45740717ab8cc6ee8` |
| `hermes_state.py` | `e507ebd78b870364fd2fced94212592380cd26d0d39eec67547ed9bc233ebb98` |
| `hermes_state_search.py` | `6e8f67ee7ee569adbf7d16bb116f37837e1d8589e2b6410d90a4c13e7079dfcc` |
| `hermes_state_messages.py` | `b3c5ad76a6d1a63c2800a0eca0c36240ad3098999a248568e46a7c3649cf9136` |

Each query ran with `limit=5`, `detail=adaptive`, `current_session_id` set to the query's session and `before` set to
the query time. An answer counts only if `success` is true and `count` equals the number of results; any other answer
is recorded as unknown and fails the run. All 23 answers passed.

**Postfilter, applied by this script, not by Hermes.** The tool's `before` bounds the start of a session, not the time
of a message, so it can show messages written after the query. The script keeps the tool's answer as it came and
writes a separate comparison in which every shown message (match, window, bookends) must have a timestamp before the
query, and a result whose matched message is not before the query is dropped whole. On these queries 6 of 38 results
had their match at or after the query, and 9 shown messages were dropped. The real tool has no such boundary.

Each comparison row carries the hash and time of its query. The aggregate refuses the whole comparison, instead of
counting a row as empty, when a row's hash or time differs from the query file, when any kept message is not written
before the query time, or when a character count is not a non-negative integer equal to the kept text. The run used
here was repeated once to add these fields; apart from them it is identical to the run before, and so are the
aggregates.

From the code of the tool:

- FTS5 with implicit AND; on zero rows it retries with a trigram table, then with OR. Words joined by `-`, `.` or `_`
  become phrases.
- The FTS table indexes `tool_calls` as well as `content`. Of the 32 results whose match is before the query, 27
  matched a message with empty content and tool-call arguments.
- Cron sessions are searchable but ranked below interactive ones; `subagent`, `kanban` and `tool` sessions are hidden.
- The top result comes with up to five messages on each side (4,000 characters each) and three at each end of the
  session (1,200 each); the other results come with the matched message only.

The hash of the first copy did not change; the second copy got `-wal` and `-shm` files when it was opened.

### Labels

Items were shown per query, mixed across arms in a fixed random order, with the role and the age relative to the
query. Today's top five facts for the query were shown for the outdated check only. Labels: **answers** (the passage
holds what the query looked for, judged by the session title as the intent), **related**, **noise**; outdated:
**newer** (a newer item says otherwise), **fact** (today's base says otherwise).

The labels were assigned by the research agent itself (Claude Opus 5.5). That reader was not blind to the selection,
and no person graded anything.

**Binding.** A label counts only when [`aggregate.py`](scripts/history602/aggregate.py) recomputes its id from the
query, the message and the exact window text of the saved results, and the hash of the text the reader saw matches
that window. 72 of the 103 labels bind to the parser windows of this run. The other 31 were given to items that only
`session_search` returned; the reader saw a window cut from the stored message, not the text the tool shows, so those
labels bind to nothing here and are not counted. Every result of `session_search` is therefore unlabelled.

**Privacy limitation and disclosure.** The research agent itself ran on Anthropic's Claude Opus 5.5 and read real
Hermes history windows to assign these labels. Consequently those tool results were sent to Anthropic; not launching
a separate grader did **not** avoid that transfer. The research task had required that private history not be sent
to an additional provider without approval. Further raw-window reads and semantic relabelling were prohibited when
this was identified. Code fixes continued in the existing research-agent session; this note does not claim that its
previously received context was purged. Independent review is limited to code, synthetic fixtures and aggregates. No real query, window
or raw label packet is included in the public artifacts. The semantic labels remain the research agent's own,
independently unverified judgements.

## Results

### Q1. How often does history answer an empty search?

Bound labels only; no window of these runs was left unknown.

| arm | stratum | queries | with a window | queries with an answer | windows answers / related / noise |
|---|---|---|---|---|---|
| hermes-text | interactive | 7 | 6 | **2** | 2 / 16 / 11 |
| hermes-text | memcue-session | 2 | 1 | **1** | 2 / 1 / 0 |
| hermes-text | cron | 14 | 4 | **0** | 0 / 7 / 10 |
| claude-local | all | 23 | 7 | 0 | 0 / 8 / 14 |
| claude-host | all | 23 | 1 | 0 | 0 / 0 / 1 |

With seven interactive queries, 2 of 7 is an observation, not a rate. For these 14 cron queries, which looked on the
research shelf for a new topic, the parser found no answer; whether that holds for other cron work is not measured.

The Claude Code arms are cross-corpus: the queries came from Hermes. They answer "did anything on this server's Claude
Code side know it", not the Mac's question.

### Q2. What does a find cost?

The same queries for both methods; a query with nothing shown counts as 0. Characters, not tokens.

| stratum | queries | parser windows, median characters per query | `session_search` after the postfilter, median characters per query |
|---|---|---|---|
| interactive | 7 | 1,811 | 6,138 |
| memcue-session | 2 | 467.5 | 2,418 |
| cron | 14 | 0 | 0 |

The parser counts its windows; `session_search` counts the content and tool-call arguments of every message it
shows. The rows describe what each would put in a context; they do not rank the methods. The whole raw answer of
`session_search`, with its JSON and the messages the filter drops, had a median of 9,570 characters over all 23 queries.

With tool output the parser returns windows for 17 queries instead of 11, over a corpus 14 times larger (27,106
messages against 1,871). Of its 78 windows, 4 are text windows already labelled and 74 are **unknown**; they also carry
secrets and fetched pages and never left the private output.

### Q3. How often is a find outdated?

- **By a newer message or by today's base**: 0 of the 4 bound answering windows. Today's facts were used only for this
  check, not as proof that a fact existed when the query ran.
- An earlier draft of this note counted one outdated find among `session_search`'s results. That label belongs to the
  31 that do not bind, so the finding is **unverified**.
- **Writing after the query**: without the strict time bound the parser would have matched 134 later messages for the
  interactive queries; `session_search` returned 6 results matched at or after the query and showed 9 later messages,
  which the postfilter dropped.

The base cannot be rebuilt as of a query: `Store.Relabel` and `Store.Retag` add a version with a new scope or expiry
and keep `Created`, and the shared text history starts on Oct 31. So whether a fact was in scope at a query time is
**unknown**; the measurement relies on the empty answer recorded in the transcript instead.

### Q4. Does `session_search` already cover it?

For each bound answering window of the parser, the aggregate looks for the same text among the messages
`session_search` showed for the same query, after the postfilter:

| stratum | answering windows | same text shown | message shown, text cut or absent | message not shown |
|---|---|---|---|---|
| interactive | 2 | **2** | 0 | 0 |
| memcue-session | 2 | 0 | 1 | 1 |

So `session_search` shows the parser's answering text for both interactive queries with an answer. For the
memcue-session query it is **unknown**: one answering message is shown only up to the 1,200-character cut, which ends
before the parser's passage, and the other is not shown. Whether the kept part answers would need a new label, and no
new labels were made. Its own matches are mostly tool-call arguments (27 of 32).

## Recommendation

**Defer `memcue sessions`.** On this server, `session_search` showed the parser's answering text for 2 of the 3
queries with an answer, and the third is unknown; seven interactive queries from one server cannot decide whether a
second history search is worth building. The Mac, which has no `session_search`, decides it. Run the same scripts on
the Mac's `search.log` and `~/.claude/projects`, dropping the hook's program-name queries, and have someone other
than the author label the windows.

## What stays open

- The Mac criterion of #602: about 50 empty agent queries from the Mac's `search.log` over its Claude Code
  transcripts, and the 30-day retention there. Not measured.
- Labels for `session_search`'s own results and for the tool-output arm. None bind.
- An independent or human grader. None.

## Reproduce

```sh
cd docs/research/scripts/history602
TMPDIR=<private dir> python3 -I test_sessions.py
python3 -I sessions.py --queries Q.jsonl --hermes-db COPY/state.db --arm hermes-text --out OUT/hermes-text
python3 -I sessions.py --queries Q.jsonl --hermes-db COPY/state.db --arm hermes-tool --include-tool-output --out OUT/hermes-tool
python3 -I sessions.py --queries Q.jsonl --claude-dir PROJECTS --arm claude-local --out OUT/claude-local
env -i PATH=/usr/bin:/bin HOME=SCRATCH HERMES_HOME=SCRATCH HERMES_PY hermes_session_search.py \
    --hermes-root HERMES --db COPY2/state.db --queries Q.jsonl --out OUT/session-search
python3 -I aggregate.py --queries Q.jsonl --run hermes-text=OUT/hermes-text --run claude-local=OUT/claude-local ... \
    --session-search OUT/session-search/comparison.jsonl --labels L.jsonl
```

`Q.jsonl` lines are `{"qid", "query", "time", "stratum", "exclude_sessions"}`, built from the copy's tool calls by the
rule in Queries. The query file, the label packets and the labels are not in the repository.
