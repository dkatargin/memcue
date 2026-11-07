# Content-only storage upgrade (v0.31.0; #678)

Release status: prepared for v0.31.0; publication, installation and live-base migration remain separate operator steps.

This change removes `keywords` and `queries` (including full translations) from current SQLite facts, JSONL versions,
Go models, write APIs and tool schemas. Only literal `content` is indexed. It does not change the language of stored
content or delete metadata/history. Non-English content remains searchable in its own language; an English-first
search can need synonyms or a retry in a legacy language. The owner chose this simplification despite the retry
costs measured in #673. Those results do not establish retrieval equivalence or a cost guarantee.

## Before opening an existing base

1. Stop **all** consumers and writers on every machine sharing the base: CLI, scheduled/background dreams, hooks,
   integration providers, sync/merge drivers and caches. Pause synchronization while upgrading. Upgrade their binaries
   and integration instructions together. Do not let an old writer touch the upgraded text history.
2. With writers stopped, make an independent backup of the entire base: standalone SQLite file, or the JSONL history
   **and its cache**, plus per-base state and any SQLite journal files. A cache can hold pending versions whose append
   to JSONL failed. Keep the backup outside the current history and verify it is readable before proceeding. Preserve
   Git history and the pre-upgrade revision; never rewrite remote history. Do not back up by copying a changing DB.
3. Test a copy in an isolated path first. Opening standalone SQLite upgrades it to schema **9** in one transaction:
   add missing legacy metadata columns, establish opaque write identities before projection, drop the two auxiliary columns, rebuild FTS from content and set the version.
   Even a populated, correctly stamped old index is rebuilt. On error, the transaction rolls back; do not ignore the
   error or change `user_version` by hand. Unsupported triggers/indexes depending on removed columns must be reviewed
   on the isolated copy before retrying, not silently discarded by the migration.
4. For JSONL, open the isolated history with an explicitly isolated cache. An older readable cache is locked, its
   pending versions are rescued (including divergent versions at or below the file’s last number, using the usual merge/renumbering rules), and it is retained at `<cache>.schema<V>-<unique>`. The new cache is built under a
   temporary name and renamed only after success. Legacy JSONL is parsed without auxiliary text, backed up byte for
   byte under `<cache>.schema7-text-backup/<SHA256>.jsonl` (outside the history), then replaced atomically per file. If the cache is inside the history, backups instead use the sibling `<history>.schema7-text-backup` directory.
   An interrupted pass resumes on the next open; an error is returned instead of accepting an incomplete pass.
   Keep all set-aside caches and backups until the complete upgrade is accepted. Never use a backup directory as the
   current facts directory. File changes inside the history are normal new Git changes, not a history rewrite.
5. Check content and metadata/version chains, expired/retired semantics and searches on the copy. Repeat open and
   sync/merge between two upgraded copies. Then perform the coordinated offline upgrade and resume only upgraded
   consumers. Review and commit the migration's JSONL changes through the usual workflow.

## Refusal and recovery

An unreadable or newer cache is refused: it might contain pending versions. This version does not silently replace
it. Keep it untouched, recover its contents on a copy with the appropriate binary/tooling, and reconcile pending
versions before deliberately setting it aside. A missing cache can be rebuilt only from the history that remains;
removing a cache is not a recovery procedure when pending writes are possible. Invalid JSONL and failed backup or
replacement writes stop opening the store and report the failure. Correct the underlying problem and reopen; already
converted files remain valid and content-addressed backups are not overwritten. Existing lock files serialize
concurrent text migration/build/sync; normal SQLite locking serializes standalone upgrades.

Read-only historical inspection (`dump`, historical merge reads) supports older SQLite and JSONL without migrating
or writing them. It shows content and preserved metadata, not obsolete auxiliary fields. Import accepts legacy
auxiliary keys as historical input and discards them; it never appends them to content. Current add/correct and tool
handlers refuse obsolete auxiliary parameters, including flags after positional arguments, rather than storing them
as content. Use `--` for deliberately literal text beginning with a flag word. Old auxiliary dream answers/plans must
be discarded and prepared again; they are refused before applying their writes.

## Compatibility and rollback

SQLite schema 9 makes old standalone readers/writers refuse the base. **This does not protect text histories from
old clients:** a published old `OpenText` can set aside a newer cache and rebuild it, and old writers can put auxiliary
keys back into JSONL. There is no mixed-version sync guarantee. Stop old consumers together; do not rely on schema
version alone. No new implicit model, translation or expansion calls replace the removed fields. Splitting,
duplicate/outdated review and scope maintenance remain available.

Rollback requires stopping all consumers again and restoring the complete pre-upgrade backup (including cache and
state) on every participating copy. Auxiliary text cannot be recovered from the upgraded current representation.
Set-aside caches and content-addressed JSONL backups are recovery evidence, not an automatic complete rollback.
Writes made after upgrade must be separately reconciled before restoring an old snapshot or they will be lost.
Never downgrade in place, allow an old writer to rewrite upgraded files, or force-push history. Publication,
installation and live-base migration are separate operator actions; this source change performs none of them.

Historical research reports and raw results remain historical. Executable helpers tied to the removed auxiliary
APIs require their original source revision for comparable measurements; current content-only runs cannot be
interpreted as repeats of those experiments. The integration wording keeps the original capture/retry policy while
removing obsolete CLI options; no compliance or retrieval-quality experiment is claimed here.

## Preserved write identity

Schema 9 and current JSONL carry optional `write_id` operational metadata. Before discarding auxiliary values,
migration hashes a canonical legacy write fingerprint: fact identity, literal content, timestamp, author, origin,
status and legacy auxiliary values. **Version numbers are merge positions, not permanent write identity**, and are
excluded. JSONL arrays use the published comma-space encoding, so SQLite and JSONL establish the same fingerprint.
Optional metadata absent from older cache schemas does not define that fingerprint, but remains part of full version
equality and of the occurrence class. Omitted auxiliary fields and accepted explicit empty values share one complete-history
occurrence class before identities are persisted. Same-version append retries are compared using these canonical
classes before counting occurrences, so equivalent empty encodings count once while equal records at distinct versions
retain their multiplicity. Different content, metadata, nonempty auxiliary values or supplied identities at the same
version remain conflicts. Redundant empty fields do not replace an already stored identity; nonempty legacy fields
paired with a stored identity must match its fingerprint or parsing refuses the inconsistent row.

Repeated fully equal legacy tuples retain their recorded multiplicity: a complete history assigns their first,
second, etc. occurrences stable identities (a fingerprint plus an ordered occurrence suffix after the first).
Inserting different writes during a pre-upgrade merge does not change those occurrence ranks. Rows that merely
project to equal content, including different auxiliary values or metadata, are different classes. Read-only legacy
opens also establish identities from the complete history before answering subset queries. Merges preserve those
identities across renumbering; subsequent local corrections derive a new identity. No auxiliary plaintext is retained
in current fields, content or indexes. This is migration metadata, not a searchable field or a general event log.

The legacy format never recorded an independent event identifier. Occurrence correspondence preserves the multiplicity
actually recorded by the histories; it cannot recover additional author provenance or writes already collapsed by an
older client. Fully equal legacy tuples are observationally indistinguishable except for their recorded occurrence
order. Do not claim discarded information can be reconstructed. Retain original backups and reconcile any external
provenance before upgrading if it contradicts the recorded histories.

Older cache projections are matched using the fields they actually stored: a common available-data sequence or a
unique identity match establishes correspondence. Each cached occurrence consumes at most one file occurrence.
After divergence, multiple possible matches caused by missing schema labels are refused rather than guessing which
record was observed or inventing a new write. Keep the old cache and original backups for explicit reconciliation;
the cache is not retired on this refusal. A legacy text file may already have been projected with its raw bytes backed
up during the opening pass, so an error is not permission to discard recovery evidence. Pending writes are then reconciled using the normal history-union rules,
including correction versus retirement. Physical backup paths resolve existing symlink components and absent leaves;
when the proposed destination is inside history, the physical history's sibling is used. If that fallback also
resolves inside history, opening fails before rewriting fact history. Cache retirement creates saved names exclusively,
so repeated retirements cannot overwrite earlier cache bytes.

A prototype schema-8 copy that already discarded auxiliary information cannot recover original write distinctions
from its projected rows. Restore the complete pre-upgrade backup and migrate that copy instead; do not claim a later
schema change reconstructs discarded information. Coordinated rollout remains required for JSONL consumers.

The rejected pre-release schema-9 prototype used version-dependent digests. Its projected data has already discarded
the auxiliary inputs needed to establish corrected correspondence. Restore the original legacy SQLite/JSONL/cache
backup and upgrade that copy with the corrected source; do not mix prototype and corrected caches or attempt an
in-place digest rewrite. The corrected schema 9 is included in v0.31.0; no schema number protects JSONL from old consumers.

An earlier rejected candidate may also have persisted incompatible mixed-empty occurrence identities or merged an
invented version. Start again from the original complete legacy backup for a clean isolated upgrade; the corrected
reader does not infer which already-projected historical records can be discarded.
