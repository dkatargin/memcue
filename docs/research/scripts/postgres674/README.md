# Disposable PostgreSQL research stand

This stand reads invented public fixtures only. It leaves production storage and CLI defaults unchanged. Run it in an exclusive disposable worker, with two CPU workers maximum. It starts an owned rootless PostgreSQL process, exercises local clients, and stops the process before returning. No unattended service is installed.

Read [the ADR](../../postgres-674-adr.md), [report](../../postgres-674-report.md), and [predeclaration](declaration.json) first. The first completed checkpoint retains raw evidence under ignored `.research-private/evidence/run-02`; the final formatted-driver run is identified by the report. An earlier failed run remains there too. Raw directories, dumps, requests, logs, and model vectors are private even though their input corpus is synthetic. Do not copy a raw directory into a public report.

## Dependencies

Verified environment: Debian 13 x86_64, Go 1.27.0, Python 3.13.5, `dpkg-deb`, `curl`, `/usr/local/bin/build-check.sh`. Existing runtime libraries satisfy the extracted PostgreSQL binaries when the accompanying ICU, LDAP, XML, XSLT and libpq packages are on `LD_LIBRARY_PATH`. No Docker daemon is needed. `packages.json` pins downloaded Debian package versions and SHA256 values. PostgreSQL is 17.11, pgvector 0.8.0. JIT remains disabled; LLVM's optional JIT module is not used. This package extraction is not a system package installation or a production upgrade recommendation.

Set `RESEARCH_CACHE` to an owned cache outside Git discovery, and verify `git -C "$RESEARCH_CACHE/tmp" rev-parse --show-toplevel` fails. Never use a shared temporary directory or a Git checkout as `TMPDIR`: existing install tests can affect common Git config when fixtures discover a parent repository. All task-specific raw output goes in the assigned worktree. The commands below use environment-specific cache placeholders; see private `environment.txt` for the executed worker paths.

```bash
export RESEARCH_CACHE="$WORKER_CACHE/memcue-pg674"
mkdir -p "$RESEARCH_CACHE/tmp" .research-private/evidence
chmod 700 "$RESEARCH_CACHE" "$RESEARCH_CACHE/tmp" .research-private .research-private/evidence
export TMPDIR="$RESEARCH_CACHE/tmp"
export GIT_CEILING_DIRECTORIES="$RESEARCH_CACHE"
export MEMCUE_NUMBER_TERMS=1 OPENBLAS_NUM_THREADS=2 TOKENIZERS_PARALLELISM=false
unset MEMCUE_FACTS MEMCUE_SEARCH_LOG MEMCUE_USAGE_LOG MEMCUE_DREAM_EVERY MEMCUE_CLAUDE_TOKEN_FILE
unset SEARCH_LOG USAGE_LOG DREAM_EVERY CLAUDE_TOKEN_FILE
python3 docs/research/scripts/postgres674/bootstrap.py "$RESEARCH_CACHE"
python3 docs/research/scripts/postgres674/download_model.py "$RESEARCH_CACHE/e5-small"
```

Install the Python packages into an isolated cache, never the system interpreter. This worker initially had no pip or venv support. It bootstrapped pip from `https://bootstrap.pypa.io/get-pip.py` into `$RESEARCH_CACHE/pydeps`, then installed `requirements.lock` there. The bootstrap response hash is retained privately; future environments should use an existing trusted pip or a verified bootstrap. `requirements.lock` pins all observed package versions, but is not a wheel hash lock. The exact pip command and environment are in private evidence.

```bash
# With an existing trusted pip:
/usr/local/bin/build-check.sh python3 -m pip install --target "$RESEARCH_CACHE/pydeps" \
  -r docs/research/scripts/postgres674/requirements.lock
export PYTHONPATH="$RESEARCH_CACHE/pydeps"
/usr/local/bin/build-check.sh go build -p 2 -o .research-private/sqlite_bridge-next \
  ./docs/research/scripts/postgres674/sqlite_bridge.go
/usr/local/bin/build-check.sh python3 docs/research/scripts/postgres674/experiments.py \
  --pgroot "$RESEARCH_CACHE/pgroot" --model-cache "$RESEARCH_CACHE/e5-small" \
  --bridge .research-private/sqlite_bridge-next --out .research-private/evidence/run-next
```

Each heavy command has one wrapper. The driver does not invoke `build-check.sh`; do not wrap this whole shell session or nest wrappers. Go tests use `-p 2 -parallel 2`. The DB pool and race executor use at most two workers; model inference uses two CPU threads and processes one input per recorded embedding sample.

The driver refuses an existing output directory, symlink components in its output path, and a different baseline HEAD. The bridge also requires a new output directory with an existing parent; it refuses prior output before writing normalized data or opening SQLite. JSON and SQLite file creation is exclusive. Keep the original measured bridge binary and use a new binary path for repaired builds. The audit uses the same directory guard. `recompute.py --output` requires a new file and refuses symlink components; use stdout to inspect existing evidence without publishing another file.

The driver freezes its source/input hashes before execution. Do not edit evaluated scripts or fixtures while a run is active. Failed runs keep outputs and an error traceback only after creating their own output directory. Failure logging never replaces an existing record, symlink or hardlink. Normal exits and Python exceptions stop the owned PG process in `finally`; a hard worker kill still requires the parent to verify process cleanup.

## Verification and recomputation

```bash
/usr/local/bin/build-check.sh python3 -m unittest discover -s docs/research/scripts/postgres674 -p 'test_*.py' -v
python3 docs/research/scripts/postgres674/recompute.py .research-private/evidence/run-next \
  --output .research-private/recomputed-next.json
/usr/local/bin/build-check.sh python3 docs/research/scripts/postgres674/audit.py \
  --pgroot "$RESEARCH_CACHE/pgroot" --evidence .research-private/evidence/run-next \
  --bridge .research-private/sqlite_bridge-next --out .research-private/evidence/audit-next
/usr/local/bin/build-check.sh go test -p 2 -parallel 2 ./docs/research/scripts/postgres674
/usr/local/bin/build-check.sh go test -p 2 -parallel 2 ./...
```

`recompute.py` reads saved ranks and labels without calling the DB or model. It recomputes per-arm, per-stratum, and per-intent-language metrics at 1/5/10, verifies both repetitions, checks every hit against independently implemented eligibility, checks auxiliary/metadata token isolation with positive controls, compares the PG history projection, checks source hashes and failure assertions, and summarizes latency with nearest-rank quantiles. It does not independently judge semantic labels. Labels were authored with the synthetic facts, not by a blinded annotator.

The 26 held-out cases are distinct from two tuning cases; no parameter tuning was performed. Three additional cases test field isolation. Some intent-language labels use English literal anchors; only four held-out query strings contain Cyrillic. These data do not establish balanced English/Russian production performance. Exact identifier/version probes are small and do not prove broad adversarial robustness.

`fixture.json` is checked in and hash-pinned. `make_fixture.py` only regenerates those public invented inputs; it is not run during experiments. Regeneration or label edits require a new declaration and distinct evidence directory. `schema.sql` is only executed in a freshly created disposable database. Never point this driver at an existing database or modify it to infer a user's fact-base path.

The [repair-cycle-1 erratum](../../postgres-674-erratum.md) distinguishes the original measured source from the repaired output guards. Existing run manifests and measurements retain their original source hashes.
