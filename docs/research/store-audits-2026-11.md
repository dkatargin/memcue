# Text-store audit outcomes, November 2026

These investigations began as hypotheses in #635 and #640–#642. This note records the observed outcomes in their
implementation PRs, including narrower delivery than the original acceptance lists. It is a historical source
archive, not a new durability or security certification. No fault injection or live-base access was performed for
this documentation change. See the [research index](README.md).

## Interrupted cache builds

[#635](https://github.com/juev/memcue/issues/635) observed the schema-7 cache rebuild at **2.7 s on the Mac** and
**5.1–5.2 s on the server/Hermes**. A custom hook with a **2 s** timeout killed the Mac build, leaving a hot journal;
read-only opens then failed with SQLite error **776** until a normal open rolled back and completed the build.
No fact loss was reported. Repeated short-timeout callers could restart the same unfinished build indefinitely.

[PR #652](https://github.com/juev/memcue/pull/652) chose building under a temporary name and renaming after commit.
Its regression used a damaged fact file to stop the build, then a repaired file and a simulated leftover journal to
check recovery. That is deterministic evidence for the failure/recovery path; the PR does not report a new real
process-kill timing series or post-fix latency table. Parallel first opens were checked separately.

## Writes acknowledged before text persistence

[#640](https://github.com/juev/memcue/issues/640) initially described a static-review risk. The later
[PR #653](https://github.com/juev/memcue/pull/653) reproduced two cases after a JSONL append failed following a
successful SQLite commit:

| Case | Before the fix | Delivered protection |
|---|---|---|
| A later append succeeds | Full row-count stamp hides the earlier failure; version stays cache-only | Dirty stamp survives later writes; next open exports owed versions |
| Schema upgrade sets the cache aside | New cache built from text omits the cache-only version; old cache file remains | Readable old cache supplies versions beyond each text file's last version before being set aside |

The PR names two regressions that failed on the prior main:
`TestAFailedFileWriteIsNotHiddenByALaterOne` and `TestASetAsideCacheGivesTheTextWhatItLacks`.
It explicitly leaves these limits:

- CLI/tools still report success when an append fails. The fix did **not** deliver the issue's requested distinction
  between durable text success and pending synchronization.
- A version numbered at or below a file's last version is not merged from an old-schema cache; it remains in the
  set-aside file. An unreadable cache is set aside without recovery from it.
- No full process-interruption crash matrix was run. The PR relies on the existing next-open export for the
  commit-to-append window; this is not a new proof covering all crash/retry cases.

These are synthetic reproduced failures and bounded recovery checks, not a reported production loss incident.

## Fact-file validation

[#641](https://github.com/juev/memcue/issues/641) began as a threat-model task, explicitly without demonstrated
traversal or exploitation. [PR #654](https://github.com/juev/memcue/pull/654) found that **6** malformed-file cases
all opened on the old main: short name, dots, lowercase name, wrong shard directory, another fact's ID inside and a
symlink to an outside file. The changed open refused them while retaining normal files and keeping linked contents
out of errors. This establishes input rejection, not evidence that an attacker previously read or wrote outside
the base.

The live-history compatibility survey inspected **7,580 files**: all strict ULIDs in the expected directories,
none refused. Names were checked with a **26-character uppercase/digit shape**, deliberately looser than strict
ULID parsing for readable fixtures. The git merge driver and SQLite-to-text migration were outside that PR's change.
The source does not claim a complete rename-race, symlink-directory or every-export-path audit.

## In-place edits versus replacement

The hypothesis in [#642](https://github.com/juev/memcue/issues/642) held in
[PR #655](https://github.com/juev/memcue/pull/655): changing file content in place left its directory mtime unchanged,
so open did not reread it. It did not overwrite it with stale cache data either. Once the directory changed, the
history merge retained the edit as latest. A throwaway macOS git checkout replaced the changed file with a new inode
and moved the directory time, so it was seen on open.

The selected contract supported memcue and git as writers, with `memcue correct` for edits. It left `rsync --inplace`
and manual in-place edits outside automatic detection. No runtime code changed and no before/after benchmark was
reported. `TestAnOpenSeesAReplacedFileAndNotAnInPlaceEdit` passed **5 of 5** recorded runs. The current storage
instructions are in the repository README; this historical test does not establish every filesystem/sync mode.
