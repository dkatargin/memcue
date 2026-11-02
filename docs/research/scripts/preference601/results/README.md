# Results of the #601 measurement

Data only; the analysis is in [the report](../../../preference-capture-601-2026-11.md). Collected 2026-11-02 on a
docker host by a private research controller, which is not published and not approved for reuse. The image of the
#531 stand ran with the memcue binary and the plugins replaced by read-only mounts of the inputs in
[`FROZEN.json`](FROZEN.json). The scripts in [`../stand/`](../stand/) are byte for byte the container scripts and
the candidate filter that ran (their sha256 are in `FROZEN.json`); their comments still name that controller.

- `FROZEN.json`: sha256 of the scenarios, labels, grading prompts, the candidate line and the main inputs (binary,
  base and candidate plugin files, container scripts), written before the grid ran.
- `ARCHIVE_MANIFEST.json`: the result of [`../archive601.py`](../archive601.py) over the raw root, reconstructed
  after the run: every input file and fixture file with its sha256, the inputs digest computed from them, the image
  id as the runs recorded it, the model and Claude Code version the streams report, and an empty list of problems.
  The runs saved no plan before they started.
- `data/records/<key>.json`: 72 records (36 captures, 24 probes, 12 reference probes). `record` is what the graders
  saw, without the arm; `sha256` is its hash. `meta` is an allowlist: arm, phase, scenario, repeat, image, inputs
  hash, time, cost, tokens, the model and plugins the stream reported, tool names, memcue call counts, the hook
  delivery flags and the fact ids on the session card.
- `data/grades/A`, `data/grades/B`: pass A (Opus) and pass B (Sonnet), no tools, the arm hidden. Each grade names
  the record hash it graded and carries the grader's raw answer (`raw_result`) and the exit codes of its container
  (`docker_exit`) and of claude (`grader_exit`), so `parsed` can be checked against the raw answer. One pass-B grade
  failed the schema check (an extra key) and was graded again; the first attempt was kept in the raw archive, not
  here.
- `data/summary.json`: one row per record with the combined labels and the counts of the report (`aggregate`).

## Checking the archive offline

On a copy of the raw root (`inputs/`, `fixtures/`, `runs/`, `grades/`, `grading/`), from this directory's parent:

```sh
python3 -I archive601.py --root ROOT --frozen results/FROZEN.json --expect results/ARCHIVE_MANIFEST.json
python3 -I records601.py extract ROOT          # exit 1 if any run is incomplete, tampered or not docker_exit 0
python3 -I records601.py summary ROOT --json SUMMARY.json
python3 -I records601.py export ROOT NEW_DIR   # NEW_DIR must equal results/data
MEMCUE601_BIN=/path/to/memcue python3 -I test_preference601.py
```

None of them starts a container or a model. Only the tests start processes: `make_inputs.py`, the plugins' hook
scripts over the memcue build named by `MEMCUE601_BIN`, and `git init`, all in temporary directories. On
2026-11-02 a fresh copy of the archive passed the first command; extraction gave the same 72 record hashes, all 144
grades valid, and a summary and export identical to `data/`.

The raw runs (streams, base snapshots, hook logs, grader work directories) stay on the docker host and in a local
copy outside the repository.
