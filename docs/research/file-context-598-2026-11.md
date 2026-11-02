# Facts about a file when the agent reads it: the count before a model call, November 2026 (#598)

Status: **first stage only, measured 2026-11-02 on copies of one Linux machine's base, Claude Code transcripts and
Hermes state; the structural counts were computed by the script, and no product code changed. The A/B of questions 3
and 4 was NOT RUN; the effect on
answers is UNKNOWN.** The counts are opportunities filtered by creation time, with an uncertainty class. They do not
prove that a fact was on hand at a given `Read`. The Claude Code transcripts here are delegated, SDK-launched sessions,
not the author's interactive Mac sessions the issue has in mind; that corpus was not available and was not counted. The
examples below are invented; fact texts, paths, repositories and host names stay out of the repository.

#598 asks whether a `PreToolUse` hook on `Read` that adds the facts naming the file being read would help, and says to
count first and stop if matches are rare. The count:

- **413 of the 2,839 active facts off the shelf name a file** (14.5%) in a form a path extractor accepts without
  guessing: 217 by an absolute or `~/` path, 205 by a repository-relative path (some facts have both). 57 of the 205
  relative ones have no project to resolve the path against (global, host, service or no scope). Another 306 name only
  a directory and 168 only a bare file name; neither identifies a file.
- **Claude Code `Read`: 6 of 591 working calls (1.0%), in 5 of 153 sessions, touched a file a fact named in every
  version that may have been in force at the call.** These are 3 facts and 2 files. Another 53 calls in 14 sessions
  match only under some of those versions. Those are 4 facts, two of which make 70 of the 74 pairs. Their match
  depends on a change of scope, origin or expiry whose time the base does not record. Default places certainly show a
  fact on 3 calls.
- **Hermes `read_file`, a separate tool and no Claude hook: 77 of 2,218 calls (3.5%), in 54 of 314 sessions**,
  matched 66 facts on 15 files with no ambiguity; 19 more calls (8 facts) are ambiguous the same way. One file without
  an extension is named by 20 facts; a hook would have added 4,863 characters to that one call.
- **Text added**: on Claude Code the 6 certain calls would carry 1,950 characters. Each fact once per session, it would
  be 1,716. Tokens were not counted.
- **Recommendation: defer, do not build; no A/B on this corpus.** On the local Claude Code corpus the chances are
  rare: 1% of `Read` calls for certain, at most 10% counting every ambiguous one, from 3 to 7 facts. That is the stop
  #598 allows. What this note cannot answer is in [What remains](#what-remains).

## Data

All inputs were read-only copies under a scratch directory; the originals were not opened by memcue or written.

- **Facts**: a copy of the text history, verified byte-identical to the live directory (`diff -r`), and the live path
  and its symlinked alias verified to be one directory. The copy was finished by 2026-11-02 18:45:17 UTC+3, passed as
  `--snapshot-time`. 7,049 fact files, 30,285 versions. Every file passes the checks of `store.ParseFacts`: one fact per
  file, no two different lines with one version number. At the end of 2026-11-02 (UTC+3): 2,980 active, 4,068 retired,
  1 expired, none created later. 141 of the active facts are on the shelf, which no default search reads, so a hook
  would not serve them; 33 of those name a file. The oldest version in the base was created on 2026-10-19.
- **Claude Code**: a copy of the local transcript directory. 379 transcript files (18 of them subagent files), records
  from 2026-10-16 to 2026-11-02. Every assistant record has entrypoint `sdk-cli`: these sessions were started
  through the SDK by another agent, as delegated coding and research work. Only `tool_use` blocks of assistant records
  are read; tool results, request copies and other record types never are, and each `tool_use` id counts once. 629
  `Read` calls and 5,510 `Bash` calls. Calls are classed by the record they come from:
  - **main**: 567 Reads, 153 sessions.
  - **subagent**: 24 Reads, 2 sessions (a subagent file or `isSidechain`).
  - **stand**: 38 Reads with a working directory inside a research stand (`/docs/research/scripts/` or
    `/results/runs`), synthetic runs of earlier measurements, left out of the working numbers.
  - **own**: the session that made this measurement, left out; it made no `Read` before the copy was taken.
  - "Working" below means main and subagent: 591 Reads in 153 sessions.
- **Hermes**: a read-only SQLite backup of the state database. 505 sessions from 2026-10-16 to 2026-11-02. 2,218
  `read_file` calls after 7 repeated call ids, and 12,190 `terminal` calls. 151 of the `read_file` calls came before
  the base's first fact and can match nothing.

## Method

[`scripts/file598/file598.py`](scripts/file598/file598.py), standard library only, with synthetic tests in
[`test_file598.py`](scripts/file598/test_file598.py). Every input and the output directory are arguments.

- **Inputs.** A named input that is missing or of the wrong type stops the run before the output directory is made. So
  does a fact history `store.ParseFacts` would refuse.
- **Output directory.** It must be new or empty, and must neither sit inside an input nor hold one.
- **What it writes.** Every file is 0600 in a 0700 directory, whatever the umask. The per-call and per-fact lines hold
  paths and fact IDs and stay private. `meta.json` and `summary.json` hold counts, dates and timings, with no host,
  path, session or fact ID.

### Paths in a fact

URLs and scp-style remotes are cut out first. A token that holds a variable (`$HOME/…`) or a glob is dropped whole. So
is a token next to a bracket or a backslash (`a[12].conf`, `my\ file.conf`), and a path followed by a space inside
quotes (`"foo bar.conf"`, `"foo.conf backup"`): it may be the head of a longer name. What remains is classed:

| kind | rule | invented example |
|---|---|---|
| absolute file | first directory is a filesystem root (`etc`, `opt`, `usr`, `var`, `home`, `Users`, …), at least two parts, a known extension or file name | `/etc/acme/server.toml` |
| `~/` file | the same under `~/` | `~/.config/acme/auth.json` |
| relative file | two or more parts, a known extension or file name, the first part not a host name | `internal/billing/invoice.go` |
| directory | absolute or `~/`, without a file-shaped last part | `/var/lib/acme/` |
| bare name | one part, file-shaped, not a product name such as `node.js` | `Makefile` |

`/api/v1/users`, `/review`, `example.org/team/app`, `team/app`, `docs/*.md` and `v1.2.3` are not paths. Line numbers
(`main.go:42`) and sentence punctuation are trimmed.

### Matches

Strong matches are:

- **abs**: the read path is the fact's absolute path, or its `~/` path under the session's home. A path without an
  extension counts too when the read is that exact path.
- **rel**: the read path is the fact's relative path under the root of the checkout it lies in. That checkout's project,
  read from its git remotes as they are now, the way `tier.Keys` does, must be the fact's project (`projectOf` of the
  dream: `repo:`/`dir:` scope, else the origin's key).
- **abs_worktree**: the fact's absolute path lies in a checkout. The read is the same relative path in another
  checkout of the same repository by remote.

Two repositories are never merged by a shared relative file name. A relative path under another repository, under a
removed worktree whose repository can no longer be read, or in a fact with no project, is counted only as a loose
match. So are a directory prefix and a bare file name.

### Time

A version's `created` is the time of its write only for some writers. `Add`, `Correct`, `Retire`, `Restore` and
`SplitFact` stamp the write. `Relabel`, `Retag` and `SetQueries` copy the `created` of the version before
(`internal/store/store.go`). So when a scope, an origin or an expiry changed is unknown, whatever `created` the version
carries. The script takes a version with the same content and status as the one before for the second kind.

- **Plausible versions at a call.** The last stamped version created by then had been written. Each metadata-only
  version after it may or may not have been, up to the next stamped version or the snapshot.
- **asof**: a call counts only when every plausible version is active, off the shelf, unexpired on that day (UTC+3),
  names the path and matches it.
- **ambiguous**: some plausible versions match and others do not. Such a call is counted apart, not in the headline.

In this copy 3,099 of the 7,049 facts have a metadata-only version that changed the scope (2,961), the origin (357) or
the expiry (20). On an earlier run of the same copy every ambiguous pair came from a scope change; that breakdown was
not repeated on the final run.

**today** is the same judgement at the end of 2026-11-02 (UTC+3), ignoring when the call was made. The snapshot was
taken before then, so no version is in doubt, and a version created later is left out. It is an upper bound, not a
count of past chances.

### Places

For each match the script also asks whether memcue's default search would show the fact in that session
(`recall.Query.Filter` with no `-in`). Inside a repository that is the repository's facts, this machine's host and
global ones; outside one, everything off the shelf. A place is certain when every plausible version is in it; the rest
are counted as unsure. A second variant adds what the read file's own repository would show, its facts, the host and
the global ones, to the session's places; it only adds.

**Provenance.** Every number below comes from one run of the final script on the frozen copies, with `--today
2026-11-02 --tz-minutes 180 --snapshot-time 2026-11-02T18:45:17+03:00`. `summarize`, which reads all its inputs before
it makes its output, recomputed the summary from that run's per-call and per-fact lines byte for byte. Earlier runs of
older versions of the script are superseded and not used here.

## Results

### Question 1: facts that name a file

Of 2,839 active facts off the shelf at the end of 2026-11-02:

| facts naming | count |
|---|---|
| a file, any form below | 413 |
| an absolute file path | 162 |
| a `~/` file path | 56 |
| an absolute or `~/` file path | 217 |
| a repository-relative file path | 205 |
| of those, with a project to resolve it in | 148 |
| of those, with no project (global, host, service, no scope) | 57 |
| only a directory | 306 |
| only a bare file name | 168 |

By the scope of the 413: repository 200, host 114, global 58, none 25, service 15, directory 1. 99 of the 217 facts
with an absolute or `~/` path name a file that exists on this machine now. 4 name a path under a macOS home, which no
read here can match.

"Found from the path as a Read passes it" is an exact lookup for the 217. The 148 relative paths with a project need
the checkout's root and its remotes. The 57 without a project cannot be found without guessing a root. A bare name
never identifies a file.

### Question 2: calls that touch such a file

| | Claude Code `Read`, working | Hermes `read_file` |
|---|---|---|
| calls | 591 | 2,218 |
| sessions with a call | 153 | 314 |
| calls with a certain strong match (asof) | **6 (1.0%)** | **77 (3.5%)** |
| sessions with such a call | 5 | 54 |
| distinct facts / files, worktrees folded | 3 / 2 | 66 / 15 |
| matched by abs / abs_worktree / rel (calls) | 0 / 3 / 3 | 74 / 1 / 2 |
| calls with only an ambiguous match | 53 (14 sessions, 4 facts) | 19 (12 sessions, 8 facts) |
| certain matches the default places certainly show | 3 calls, 1 fact | 63 calls, 64 facts |
| the same, unsure place | 3 calls | 5 calls |
| with the read file's repository added | 3 calls, 1 fact | 63 calls, 64 facts |
| today, upper bound | 62 calls (22 sessions, 9 facts) | 105 calls (71 sessions, 55 facts) |
| facts per certain call, median / max | 1.5 / 2 | 1 / 20 |
| characters added, every certain call | 1,950 | 45,604 |
| characters per certain call, median / max | 325 / 416 | 359 / 4,863 |
| characters added, each fact once per session | 1,716 | 43,375 |
| the same, only facts the default places show | 468 | 39,940 |

The default places were known for 440 of the 591 Claude Code calls; the rest ran in worktrees removed since. Adding the
read file's repository changed no count here, though the script now only widens the places, so it could have.

**Concentration, Claude Code.** The 53 ambiguous calls read 15 paths, which are 4 files once worktrees of one
repository are folded. Of their 74 call–fact pairs, 70 come from two facts that say where one component's source and
tests live; their match holds under some plausible versions and not under others. The 6 certain calls are 9 pairs on
2 files.

**Hermes by session source** (certain calls): cron 49 of 1,030; subagents 4 of 344; interactive chat and desktop
sources 24 of 844.

**Loose matches are noise.** A directory prefix matched 584 of the 591 Claude Code calls and 2,042 of the 2,218
Hermes calls: the base names a few top-level directories that hold nearly everything. A bare file name matched 198
Claude Code calls. A relative path under the wrong root or repository matched 20, one in a removed worktree 21, one in
a fact with no project 32. None of these is an exact file match, and none is counted above.

**The stand runs** (38 Reads) matched nothing.

**Not the #598 surface, for scale only.** A command that names a matched file anywhere in its text, heredocs included,
is an upper bound for a hook on the shell. It matched for certain 140 of 5,152 working Claude Code `Bash` calls (69
facts) and 1,040 of 12,190 Hermes `terminal` calls (223 facts). 300 `Bash` calls have an ambiguous match, 5 of them
also a certain one, so 295 have only an ambiguous one; on `terminal` it is 94, 4 and 90. 4,165 of the working `Bash`
calls name a file, seven times the number of `Read` calls, so a `Read` hook sees a small part of the files these
sessions touch.

### Matcher cost

In the final run the Python matcher built its index in 14.01 s and matched a path in 5.15–10.46 ms, depending on the
tool. This is a research script on a copy. It says nothing about the latency of a hook that starts a process for
every `Read`, or about model time.

### Checks of the extractor

The research agent inspected examples privately on an earlier run of the same copies, before the final quote rule;
this was not a human or independent semantic assessment. These checks were not repeated on the final run, so they
show what kind of errors the extractor makes, not error rates for the numbers above.

- **Precision.** In the most frequent certain (fact, file) groups of each tool, the fact named the file it matched.
- **Misses.** Read paths were searched as substrings of the facts in force at the call. The few missed pairs were of
  two kinds: an extension-less path followed by its arguments inside backquotes, which the quote rule drops, and a
  path written behind an `owner/repo/` prefix.

## What it means

These are interpretations, not measurements.

- On Claude Code the certain chances are 3 facts. The ambiguous ones are a handful of facts about a repository the
  sessions were working in. A session that reads a file already sees it. A fact that says where its tests are is what
  the agent finds by listing the directory. Whether such a fact improves an answer is the open question #361 answered
  the other way for prompt-time injection.
- On Hermes the matched files are mostly the machine's own configuration, scripts and caches, described by host facts.
  Some files are named by many facts at once, so a hook needs a cap. A Claude Code `PreToolUse` hook does not reach
  Hermes `read_file`; a Hermes hook would be a separate build.
- The counts cannot tell an injection that helps from one that repeats what the file says. Only the A/B can.

## What remains

#598's acceptance asks for numbers on all four questions and a build-or-drop recommendation. This note answers
questions 1 and 2 on the local corpus only and stops before the A/B, as the issue allows when matches are rare. To
close the issue:

1. **The same count on the author's Mac base and interactive transcripts**, with
   `file598.py measure --facts … --claude-projects … --home … --host … --today … --tz-minutes … --snapshot-time …
   --out …` (no `--hermes-state`). If the interactive sessions match as rarely, drop the idea.
2. **A small A/B, the way [pull-2026-10](pull-2026-10.md) ran**, only if step 1 finds enough distinct facts with a
   certain match.
   - Prompts: 10–20 real prompts from sessions with a certain match, each on a clone of its repository as of the
     prompt, in the throwaway setup of [e2e-files](e2e-files-2026-10.md).
   - Arms: as released, and as released plus a `PreToolUse` hook on `Read` that adds the matching facts, at most 3
     facts and 600 characters.
   - Grading: blind, 0–2, counting the prompts a fact made worse.
   - Cost: the input tokens the hook adds and the hook's time per `Read` are measured inside the runs.

Until then: **defer**. Nothing ships, no hook and no default changes, and #598 stays open.

## Not measured, and what the numbers rest on

- **The Mac corpus and interactive sessions.** Every local Claude Code session was started through the SDK by another
  agent. That population reads mostly through the shell and works mostly in fresh worktrees, so this corpus does not
  stand for it.
- **Answer quality, tokens and hook latency** (questions 3 and 4): NOT RUN, UNKNOWN.
- **Time.** The asof class is consistent with the history, not proven by it. It trusts that a stamped `created` is the
  time of the write and that versions were written in version order. A merge between machines, or a writer older than
  today's store code, can break either.
- **Sync delay.** A version may have reached this machine after its `created`, so asof can count a fact before it was
  here.
- **Coverage.** 17 days of transcripts (2026-10-16 to 2026-11-02) against a base whose oldest fact is from 2026-10-19.
- **Removed worktrees.** 151 of 591 Claude Code calls ran in a worktree whose repository can no longer be read. Their
  relative paths count as loose (21 calls), and their default places are unknown.
- **Repository identity.** The remotes of a checkout are read as they are now, not as they were at the call. The
  resolver reads `remote.*.url` from the common git config only. It does not read per-worktree config, `include` files
  or `insteadOf` rewrites, ignores comment and case rules beyond the simple form, compares paths without resolving
  symlinks except for the Claude config directory, and treats only `/tmp` and `/var/tmp` as temporary.
- **The extractor.** A relative path under a directory named like a host (`conf.d/…`) is dropped, and the
  `owner/repo/path` form is not resolved. A spaced file name outside quotes is still cut at the space, and any
  path followed by a space inside quotes, such as a command with its arguments in backquotes, is dropped.
