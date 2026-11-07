# Synthetic retrieval comparison (#682)

**Primary Hit@5 reached a ceiling: lexical BM25, E5 vector and RRF60 hybrid each
found the gold fact for 30/30 positives (100%). Exploratory, post hoc Hit@1 was
25/30, 29/30 and 30/30 respectively.** First position improved on these examples;
top5 coverage did not. Vector and hybrid returned more non-gold facts and searched
more slowly in this implementation. This small authored development set supports
no general rollout, statistical significance or actual-agent benefit claim.

This is the measured synthetic pilot for [#682](https://github.com/juev/memcue/issues/682),
evaluating the production lexical baseline at
[`141b68884e98316faf205cb0b7a220953fa40307`](https://github.com/juev/memcue/commit/141b68884e98316faf205cb0b7a220953fa40307)
against experimental vector and hybrid arms. The publication base
`067d37fd24f34d3d6d00dd9e364a87718b19c185` differs by the content-only #683 change;
these measurements were not rerun on that base or today's main. Production,
defaults and backend remain unchanged; the broader issue remains open in scope.

## Corpus and frozen method

The [fixture](hybrid-682-synthetic-pilot/fixture.json) has 48 fictional facts:
30 targets and 18 distractors, all active version 1, global and without expiry.
There are 36 questions: 30 positives with one unique gold fact each, six per
exact-identifier/number, English, Russian, cross-language and conditions/negation
stratum, plus six negatives with no gold answer. These are author-labelled
fictional development examples, not blind, held-out or representative data.
Unique entity cues and the small corpus can make lexical retrieval easy.

The exact fixture and [method](hybrid-682-synthetic-pilot/method.json) were frozen
before encoding or ranking; labels, questions, parameters and rankers were not
tuned after results. All arms shared native SQLite facts/content/eligibility,
`In=["global"]`, `MEMCUE_NUMBER_TERMS=1`, top5 and score-descending then
ID/version-ascending ties. BM25 used OR-connected native query terms and requested
49 candidates. Exact cosine scanned all 48 eligible vectors, keeping positive
scores. Equal-weight RRF used `1/(60+rank)` with up to 100 candidates per list.
There was no ANN. Whole-fact clipping stopped at the first Unicode-scalar overflow;
the caller also checked a common 4096 UTF-8-content-byte bound. Any five facts
fit in 665 bytes, so neither bound clipped results.

## Quality

Quality counts each question once. Hit@5 was prespecified. **Hit@1 was extracted
post hoc after observing the primary ceiling**, not a confirmatory endpoint.

| Arm | Primary positive Hit@5 | Exploratory post hoc Hit@1 | Gold-slot Precision@5 | Non-gold / positive returns | Negatives with any return |
|---|---:|---:|---:|---:|---:|
| Lexical BM25 | 30/30 (100%) | 25/30 (83.3333%) | 30/150 (20%) | 44/74 (59.459%) | 6/6 |
| E5 vector | 30/30 (100%) | 29/30 (96.6667%) | 30/150 (20%) | 120/150 (80%) | 6/6 |
| RRF60 hybrid | 30/30 (100%) | 30/30 (100%) | 30/150 (20%) | 120/150 (80%) | 6/6 |

Each positive stratum scored 6/6 Hit@5 in all arms. Lexical placed gold first
25 times, second twice and third three times; vector placed it first 29 times
and second once. For example, Q19 asks in Russian where to buy a night-train ticket
at Fernwake: gold was lexical rank 2 and vector/hybrid rank 1. This is an
illustrative saved example, not an independent case study.

Gold-slot precision divides gold returns by 30×5 slots; missing slots count as
zero. Lexical left 76 slots empty, whereas vector/hybrid filled all 150 positive
slots. Non-gold share divides by actual positive returns and means nonmembership
in the author's fixed relevance set, not independently judged harm. All methods
returned something on all six negatives; no calibrated abstention was tuned.

## Search timing

There were 36 queries × 3 arms × 21 passes = **2,268 raw timing samples**:
one first observed pass and 20 warm repetitions (36 first and 720 warm per arm).
Arm order rotated deterministically. IDs, content and scores were identical across
all repetitions for each query/arm. Quality still has 36 unique questions, not
2,268 independent examples.

| Arm | First-pass median / p95 (ms) | Warm median / p95 (ms) |
|---|---:|---:|
| Lexical | 0.810437 / 1.540810 | 0.7467335 / 1.260566 |
| Vector | 5.9503535 / 8.831402 | 5.8154705 / 7.760088 |
| Hybrid | 6.4332975 / 10.024168 | 6.318714 / 8.549925 |

These are actual wall-clock medians and nearest-rank p95 values. First observed
passes shared database and OS caches and were not true cold runs. Timing is
**search-only with cached query vectors**, including eligibility, SQL vector reads
and JSON decoding, excluding encoding. This SQL full scan is not an optimized
vector engine or embedding-inclusive latency measurement.

## Encoding and verification

The model was `intfloat/multilingual-e5-small`, pinned revision
`614241f622f53c4eeff9890bdc4f31cfecc418b3`, ONNX CPU float32, 384 dimensions.
Both languages used `query:` / `passage:` prefixes, attention-mask mean pooling
and L2 normalization, right truncation at 512 and dynamic longest padding using
the actual tokenizer pad ID 1. The actual maximum was 32 tokens, with one mixed
84×32 batch (48 passages + 36 queries), intra-op 2 / inter-op 1 threads and
sequential execution. Public model asset hashes and runtime versions are in the
[sanitized summary](hybrid-682-synthetic-pilot/results.json).

Exactly one actual model session and one forward encoded all 84 texts. Successful
encoder-main walltime was 3.4487881986424327 s; external process walltime was
3.817051189020276 s. Whole-worker high-water RSS was 1,188,092 KiB
(approximately 1.133 GiB), including runtime, tokenizer, verification and model
allocations: neither isolated model RAM nor per-query latency. One earlier
encoder process failed before model load on a padding-configuration discrepancy
(model config 0 versus actual tokenizer 1), with zero model calls. That failed
attempt is preserved in the original evidence; there was no inference retry.
This pilot is separate from the historical tiny preflight and establishes no
agent/main-study admission. Its neural authorization is consumed.

Independent parent verification accepted this only as an authored synthetic pilot:
it recomputed quality and timing from all 2,268 samples, checked all 43 sealed
file records and 12 executed-source freeze entries, mapped all 84 vectors to
input task/ID/content hashes and independently reproduced cosine rankings for
all 36 queries. This publication adds no encoding or experiment.

## Published data and audit boundary

The static assets below permit independent arithmetic, vector and saved-ranking
audits without new encoding. The experimental executable harness is not shipped
by this documentation-only publication; there are no runnable main-branch CLI
reproduction commands here. The original sealed packet remains unchanged and
private runtime receipts are excluded. The published summary incorporates the
completed independent verification rather than the original pending-review label.

SHA256 values below identify exact original bytes; for gzip files they identify
**decompressed** bytes. Gzip headers have mtime 0 and no source filename.

| Asset | Contents / count | Original-byte SHA256 |
|---|---|---|
| [fixture.json](hybrid-682-synthetic-pilot/fixture.json) | 48 facts, 36 queries; exact copy | `2fdb3907ab719fb5dcb5baf48766df9c24fb99566a19e4a731bd22160fdecd98` |
| [method.json](hybrid-682-synthetic-pilot/method.json) | Frozen settings; exact copy | `3473dc432c61307b5dbfdbb2c90656fd4624fd43a7f289d42f19dbd6acb18556` |
| [query-results.csv](hybrid-682-synthetic-pilot/query-results.csv) | 108 query/arm rows; exact copy | `06db178f05df857a1db6dcc6ffed84b27b6b985ef3a29344425d6a97bfa5ea7a` |
| [search.json.gz](hybrid-682-synthetic-pilot/search.json.gz) | 2,268 samples, saved IDs/content/scores/times | `da65c74c5174e372665f4a679c1570902b59ed1f6bc03e7b8663c600fac055ea` |
| [vectors.json.gz](hybrid-682-synthetic-pilot/vectors.json.gz) | 84 vectors × 384 dimensions | `722f8438a31b885712c3f164d356beeeedb0c626465ce70ddb2cbc6de0374023` |
| [results.json](hybrid-682-synthetic-pilot/results.json) | Sanitized quality/timing, post hoc Hit@1, model/settings and worker accounting | Newly derived summary, not a raw receipt |

The observed first-position benefit coexists with unchanged top5 coverage, more
non-gold returns and slower search. Authored labels, unique cues and a ceiling on
this small set prevent a general effectiveness, rollout or agent-outcome conclusion.
