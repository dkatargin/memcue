# An acknowledged preference: one more line in the session note, November 2026 (#601)

Status: **measured 2026-11-02 on synthetic data; no product code changed.** In a side-by-side run of 2026-11-02
(see #601) Claude Code on Sonnet replied "no more tables" to a user who reads on a phone, stored nothing, and the next
session answered with a table. This note measures how often that happens on a small grid and whether one line in the
SessionStart note changes it.

In short:

- **Q1, the shipped texts.** Claude Code on Sonnet 5.5 stored the preference in 8 of 12 runs. In all 12 its second
  answer took the feedback into account, either by saying so or by visibly answering the new way; the grade does not
  tell those two apart, so this is not a count of explicit promises. The sample does show that feedback on the form
  of an answer can be acted on at once and still not be stored: 4 base runs did exactly that. The phone-and-tables
  case of the issue was stored in 3 of 3 runs; the misses are elsewhere: temperatures in Celsius (0 of 3) and short
  answers first (2 of 3).
- **Q2, the line.** With the line the agent stored the preference in 11 of 12 runs. The line does not fix the scope:
  2 of the 11 facts went to the repository's scope (both Celsius runs), so a session in another repository did not
  get them. Stored in the global scope: 9 of 12 against 7 of 12.
- **The card goes with following.** Every probe whose session card carried the preference was graded as following it
  (base 7 of 7, candidate 9 of 9); every probe without it was graded no or partial (base 3 no and 2 partial,
  candidate 3 no). This is an association: card and search were not varied separately, so it does not show that the
  card alone caused it. On an empty base none of the 12 reference probes was graded as following the preference.
- **Q3, noise and cost.** No measured noise in either arm: the two controls (a bad mood, a one-off CSV request)
  stored nothing in 12 of 12 runs, and no run stored anything besides the preference. The line cost about 1.3% more
  on the preference scenarios ($0.6536 against $0.6450 for 12 runs, API prices) and about 0.7 s a run (21.05 against
  20.39 s on average).

This is one grid: 4 preference scenarios and 2 controls, 3 repeats each. Repeats of a scenario are not independent;
the difference between the arms is two scenarios moving, not a rate.

## Method

Scripts, fixtures, tests and the data are in [`scripts/preference601/`](scripts/preference601/).

- **Stand.** The Docker image of the #531 stand with Claude Code 2.1.312. Its old memcue binary and plugins were not
  used: a binary built from `8ed3b53` (version string `0.26.1-r601.8ed3b53`) and the plugin of the same commit were
  mounted read-only over them, and every run checked their sha256 against the manifest in
  [`results/FROZEN.json`](scripts/preference601/results/FROZEN.json). Model `--model sonnet`, which every stream
  reported as `claude-sonnet-5-5`.
- **Arms.** `base` is the shipped plugin. `cand` differs in one place: the part-1 SessionStart hook pipes its output
  through [`stand/reminder601.py`](scripts/preference601/stand/reminder601.py), which adds the line of
  [`candidate/reminder.md`](scripts/preference601/candidate/reminder.md) as the last bullet of the memory note:
  "When you agree to change how you answer the user, the agreement is a standing rule of the user's: store it at
  once, do not only acknowledge it." The skill, the other hooks and the binary are the same bytes. The line is not
  shipped.
- **Delivery checked.** Before each session the runner ran the plugin's three hooks once in a side state directory
  and kept their output. In all 18 capture pairs the candidate's part 1 equals the base part 1 plus that line (4,837
  and 4,983 characters); parts 2 and 3 were empty in both. The streams' hook events (`--include-hook-events`) show
  the line in the part-1 response of every candidate session and of no base session, at start and on resume.
- **Scenarios** ([`fixtures/`](scripts/preference601/fixtures/)), written and hashed before the grid. Each capture is
  two turns in one session (`--resume`): a small task over an invented file, then natural feedback with a follow-up
  question. Nobody says "remember".

  | id | first turn | the feedback | fresh-session probe |
  |---|---|---|---|
  | D1 | compare three kettles | reads on the phone, tables are a mess, lists work better | compare three e-bikes |
  | D2 | a team chat announcement | leave out emoji, can't stand them in anything written for me | a plant swap notice |
  | D3 | which backup plan | rather the bottom line in a sentence or two first | which of two routers |
  | D4 | fermentation range of a recipe in °F | Fahrenheit means little, I think in Celsius | smoker settings from a recipe in °F |
  | C1 | expiring pantry items | rough night, barely slept, today is one thing after another | none |
  | C2 | unpaid invoices | for this one, comma-separated lines for a spreadsheet import | none |

- **Probe.** For every preference capture, a new container: a copy of that run's text base, a new home, config and
  state directory, no transcript, and a different repository, so only global facts reach the card and a default
  search. The prompt names no preference. A **reference** probe ran the same prompts on an empty base (base plugin,
  3 repeats).
- **Bounds.** At most 3 runs at once, `--max-budget-usd 0.60` per `claude -p` call, 12 minutes per container. The
  budget of $18 for the root was a soft launch threshold: before each launch the runner compared the money already
  reported with it, without reserving anything for units in flight, so with 3 captures in flight the total could pass
  it by up to about 3 × $1.20 plus whatever a call runs past its cap. The grid ran in batches (repeat 1, repeats 2–3,
  probes) and ended at $4.60 with grading, far below it. No run failed or was retried.
- **The controller.** The containers were started and graded by a private research controller on the docker host.
  It is not published and not approved for reuse. Its runs saved no plan of their own (image, model, options), and it
  did not re-check the inputs before skipping a finished run. A later hardened version passed its mock-based
  tests and a genuine Docker smoke: one control capture, extraction, both graders, aggregation and finished-unit
  resume. That smoke was separate from the 72-run dataset and cost about $0.06 at API prices. An adversarial review
  still found lifecycle failures (a timed-out container, a saved non-zero exit, spending of a started but empty
  attempt), so the hardened controller is not shipped either. The happy path does not prove those failure paths
  safe. What this note publishes is the specification of the experiment (fixtures, the container scripts
  in [`stand/`](scripts/preference601/stand/), byte for byte as they ran), the data and offline checks of it.
- **Plan and archive.** The scenarios, labels, grading prompts, the candidate line and the inputs were hashed into
  [`results/FROZEN.json`](scripts/preference601/results/FROZEN.json) before the grid.
  [`results/ARCHIVE_MANIFEST.json`](scripts/preference601/results/ARCHIVE_MANIFEST.json) was reconstructed after the
  run from the archive by [`archive601.py`](scripts/preference601/archive601.py), which reads files only and computes
  every hash again: every input and fixture file with its sha256 and the inputs digest, matching `FROZEN.json`; one
  image id across all 72 attempts, as their run.json recorded it (the image itself was not inspected offline);
  `claude-sonnet-5-5` and Claude Code 2.1.312 in every stream; a saved container exit of 0 in every attempt; no
  symlink or special file in any run; every probe started from its capture's final base. It is a reconstruction,
  not a plan saved before the run.
- **Grading.** [`records601.py`](scripts/preference601/records601.py) makes a record of each run (labels, the user's
  messages, answers, base changes with kind, scope and source, memcue calls; never the arm). Two passes graded every
  record with no tools: A on Opus, B on Sonnet. A grade binds to the record's sha256; a grade that is not the exact
  JSON asked for counts as unknown. One pass-B grade had an extra key and was graded again. Scope, kind and source
  are read from the base, not graded. The passes agreed on 213 of 216 fields; the three disagreements are below.
- **Checked again offline.** After the reviews the dataset was checked with the published offline scripts only,
  with no new model call or container. A fresh copy of the archive passed `archive601.py`; re-extracting it with
  [`records601.py`](scripts/preference601/records601.py) gave the same 72 record hashes; every one of the 144 grades
  still holds when parsed again from the grader's saved output against the record's fact ids, with the grader's
  container and claude both at exit 0; the summary and every count below came out identical. The commands are in
  [`results/README.md`](scripts/preference601/results/README.md). No harm to the host or to the data of the study was
  found.

## Results

72 runs: 36 captures, 24 probes, 12 reference probes.

| | base | cand |
|---|---|---|
| turn 2 took the preference into account (said so or answered the new way) | 12/12 | 12/12 |
| preference stored | 8/12 | 11/12 |
| of them global scope / repository scope | 7 / 1 | 9 / 2 |
| of them `-kind rule -source user` | 8/8 | 11/11 |
| other facts: useful / noise | 0 / 0 | 0 / 0 |
| controls: stored as lasting / limited in time / any change | 0/6 / 0/6 / 0/6 | 0/6 / 0/6 / 0/6 |
| searched memory in a preference run | 11/12 | 11/12 |
| probe: followed / partly / not | 7 / 2 / 3 | 9 / 0 / 3 |
| probe with the preference on the card: followed | 7/7 | 9/9 |
| probe without it: followed / partly / not | 0 / 2 / 3 | 0 / 0 / 3 |
| cost of 12 preference runs, $ at API prices | 0.645 | 0.654 |
| cost of 6 control runs / 12 probes, $ | 0.207 / 0.354 | 0.208 / 0.352 |
| mean seconds: preference run / control run / probe | 20.4 / 10.2 / 7.4 | 21.0 / 13.3 / 8.9 |

Stored, of 3, and probes that followed the preference, of 3 (reference: an empty base):

| scenario | stored base | stored cand | probe base | probe cand | reference |
|---|---|---|---|---|---|
| D1 lists, not tables | 3 | 3 | 3 | 3 | 0 (3 disputed: partial / no) |
| D2 no emoji | 3 | 3 | 3 | 3 | 0 |
| D3 bottom line first | 2 (1 in repository scope) | 3 | 1 (+2 partial) | 3 | 0 (3 partial) |
| D4 Celsius | 0 | 2 (both in repository scope) | 0 | 0 | 0 |

- **"Acknowledged" here mostly means "followed".** The label counts an answer that visibly switches (a list instead
  of a table, °C instead of °F) as acknowledged, so it is not evidence of an explicit agreement to change for good.
  In the four base D3/D4 runs that stored nothing, the answer switched and did not mention memory. In candidate D4 r1 the agent said "I'll use Celsius for the rest of this
  conversation" and stored nothing: it read the feedback as being about this conversation.
- **What gets stored is the feedback that names the answer's form.** Tables and emoji were stored in every run of
  both arms. Celsius was the hardest: the user explains a habit ("that's what I think in") and asks for the numbers
  again; base treated it as a request for this answer three times.
- **The repository scope is the remaining gap.** The skill says `-scope global` for a user rule unless the user ties
  it to one repository. In 3 of 19 stored facts the agent chose `repo` anyway (base D3 r2, cand D4 r2 and r3). The
  probe in another repository then did not see the fact and did not follow it. The line says nothing about scope,
  and it did not help there.
- **Following went with the card.** Probes searched memory in 5 of 24 runs; when the card carried the rule, the
  answer was graded as following it every time. The design does not separate the card from a search, so this is an
  association, not a measured effect of the card alone. On an empty base the same prompts gave 0 full follows in 12
  reference probes (D1 3 disputed partial / no, D3 3 partial, D2 and D4 3 no each). That is what these 12 answers
  show; it does not prove the model never answers that way by default.
- **Grader disagreements**: the three reference probes of D1 (pass A partial, pass B no; the answers mix a table with
  lists). They are counted as disputed, not as either label. No disagreement on any capture or probe of the two arms.

### Cost and time

At API prices, as the CLI reported them: the grid $2.78 (captures $1.71, probes $0.71, reference probes $0.36),
grading $1.82 (pass A $1.22, pass B $0.60), the smoke runs before the grid $0.27; $4.87 in all. The runs used a
`claude setup-token` subscription token, so these are API-equivalent figures, not money billed. After `--resume` the
CLI reports a session's cost cumulatively: the second turn's `total_cost_usd` already holds the first; the figures
above count each capture once.

## Isolation

- One container per run: uid of the host user, no capabilities, `no-new-privileges`, a read-only root with a
  temporary `/tmp`, memory, CPU and process limits. Mounted: the run directory and, read-only, the memcue binary,
  the plugin of the arm and the container script. No home directory of the host, no live base, no Docker socket; a
  probe container showed exactly these mounts.
- Home, `CLAUDE_CONFIG_DIR`, the XDG directories and `TMPDIR` live in the run directory. `--setting-sources ""`,
  `--strict-mcp-config` with no MCP server, the plugin by `--plugin-dir`, the built-in auto-memory and telemetry
  off, `--permission-mode bypassPermissions` inside the container only. Web tools and the tools that reach past the
  container (cloud routines, schedules, workflows, notifications) were disallowed in both arms.
- The streams list two plugins bundled in the 2.1.312 binary in every run of both arms (`cc-plugin-agents-md`,
  `cc-plugin-plugin-authoring`), as in #531. Their effect was not measured.
- The token came in through `--env-file` and was visible to the agent in its environment. The network is the
  ordinary bridge of the #531 stand: egress was **not** restricted to the model API. A scan for the token's exact
  value, the host's home path, user name and host name found nothing in the raw runs, the records or the grades.
- Everything the agents and graders saw went to Anthropic. The data is invented.

## Limits

- 4 preference scenarios and 2 controls, 3 repeats; repeats correlate. The arms differ by D3 (one run) and D4 (two
  runs, both stored in the wrong scope).
- One wording of the line, in one place (the note). A `Stop` hook line, the other option of #601, was not measured.
- One model (Sonnet 5.5) and one Claude Code version. Opus was not measured here.
- Two-turn conversations; a preference said deep in a long session may behave differently.
- Model grading only, two passes on two models; no person checked a label. Whether a stored fact means the
  preference (its polarity, a negation, a condition such as "for this one", a time limit) is the graders' reading.
  The tests of the scripts check that a grade has the exact form and names real facts; they say nothing about how
  well the graders read meaning.
- The correctness of the answers to the tasks themselves (the kettle comparison, the invoice total) was not graded.

## Conclusion

On this grid the shipped texts already store most acknowledged preferences (8 of 12), including the case from the
issue. The line raises that to 11 of 12, with no noise in the controls and about 1.3% more cost. What a later
session gets depends on the scope: only a global rule reaches the card in another repository, and that rose from 7
to 9 of 12. Every probe with the rule on its card was graded as following it; that is an association, not a
measured effect of the card alone.

Recommendation: the line is cheap, and here it brought no measured capture noise and no drop in following the
preference (answer correctness was not graded). The evidence for it is two scenarios moving on one grid. If the owner wants it in `cmd/memcue/session.go`, it deserves a separate issue, and that issue should also
consider saying that a preference about how to answer is global unless the user ties it to a repository: that is the
miss the line left. Neither change is tested beyond this grid.
