# Early capture, labelling and vector measurements, October 2026

Historical results from 20–22 October, before transcript extraction, vet and vector recall were removed. These are
aggregate observations on private bases, not current guarantees. The original bases, owner labels, transcripts and
one-off run outputs are unavailable in this checkout. Links below identify the recorded evidence; nothing was rerun
for this archive. See the [research index](README.md) for the later decisions.

## Usefulness and the admission policy

The owner kept **9 of 40** extracted facts. A policy retaining four kinds would pass **32**, only **7** of which the
owner kept. Model judges agreed with the owner's labels on **10–17 of 40**. These small samples motivated a review
queue: kind alone did not establish usefulness. The issues do not identify each judge/configuration or give a
per-model table. A separate observation said **93%** of the active base, about **2,400 facts**, came from the older
note migration; the proposed audit thresholds and review batches were plans, not measured audit precision.
Sources: [#17](https://github.com/juev/memcue/issues/17), [#19](https://github.com/juev/memcue/issues/19),
[#24](https://github.com/juev/memcue/issues/24).

The implementation of #17 was measured on ten holdout sessions with Opus:

| Policy run | Kept | Kind counts: pitfall / environment / decision / rule | Rejected | Cost |
|---|---:|---|---:|---:|
| Initial | 55 | 28 / 20 / 4 / 3 | 1 of 56, a tool-sourced decision | $5.27 |
| After `d729a75`, same sessions | 52 | 29 / 17 / 4 / 2 | 9 | $4.53 |

The second run's sources were **43 tool, 6 user, 3 user_confirmed**. Rejections were **4** quotes outside a RESULT
block, **1** outside a USER block, **2** kind `other`, **1** tool-sourced decision and **1** secret-shaped text.
The USER-block rejection lost a decision the owner had judged useful: the model quoted an assistant restatement.
The secret-shaped rejection could not be adjudicated from the log's first 80 characters. This archive preserves
that uncertainty without copying the rejected text. The target of 10–15 candidates per 40 facts was not met;
the policy checked trust rather than cutting volume. Sources: [PR #25](https://github.com/juev/memcue/pull/25),
[re-measurement comment](https://github.com/juev/memcue/pull/25#issuecomment-6291492729).

The separate prompt A/B, its negative alternatives and compound-fact measurement are already in
[Evaluation](../evaluation.md#what-to-keep-october-2026) and
[One claim per fact](../evaluation.md#one-claim-per-fact-october-2026), from
[PR #16](https://github.com/juev/memcue/pull/16) and [PR #231](https://github.com/juev/memcue/pull/231).

## Labels on the old base

On 22 October the Mac base had **2,623 active facts**, **2,564** without kind and scope, and **1** with expiry.
The Hermes base had **241 active**, **188** without kind and **1** with expiry; its missing-scope count was not
recorded. Only **4** migrated rules reached the Mac card. Source: [#219](https://github.com/juev/memcue/issues/219).

[PR #228](https://github.com/juev/memcue/pull/228) first labelled **2,442 of 2,444** facts on a copy in about
**13 minutes**, with no failures. Notes resolved **626** complete labels in the dry-run accounting.
Treating all feedback notes as rules admitted tool facts to the card. In the revised sample of **213** such facts,
the model called **97 rule, 52 pitfall, 20 environment**; the PR does not enumerate the remaining categories.
An initial full labelling on a copy produced **164** global rules. The revised model policy led to an expectation
of roughly **100**, superseded by the live count below. Source: [#229](https://github.com/juev/memcue/issues/229).

The live run used `deepseek-flash`, about **30 minutes**, with no failures. The comment reports **2,561 of 2,563**
facts labelled (**628** from notes, **1,935** by model); those route counts sum to the input count, not the reported
labelled count. The source does not explain the difference. Its resulting kind distribution sums to 2,618 and
therefore also has a different denominator; it must not be presented as a partition of the 2,561 changed facts.

| Kind | Facts reported after labelling |
|---|---:|
| pitfall | 893 |
| environment | 753 |
| rule | 221 |
| event | 210 |
| decision | 204 |
| procedure | 150 |
| repo | 121 |
| other | 66 |

There were **60** global rules; cards in two repositories grew from **4 to 13 lines**. Hermes labelled **188 of
188**, with **13** rules fitting its card. Source:
[#229 live-count comment](https://github.com/juev/memcue/issues/229#issuecomment-6337456276).

## Choosing the card's contents

The later [#363](https://github.com/juev/memcue/issues/363) archived-base observation counted **9 stated global rules**,
about **1,300 characters**, versus **68 global rules / 15,300 characters** competing for budget. That motivated
placing stated facts outside the budget; [the subsequent budget and delivery studies](card-and-capture-observations-2026-10.md)
record its consequences.

[PR #249](https://github.com/juev/memcue/pull/249) measured a later base with **65 global rules** and two repository
sets of **129** and **49** rules/decisions. The budget was **3,500 characters**. Repository names below are anonymous.

| Card | Before: global / repository (stated total) | After |
|---|---|---|
| No repository | 15 / — (6) | Same facts |
| Repository A, 129 candidates | 6 / 10 (16) | Same facts |
| Repository B, 49 candidates | 11 / 4 (6) | 9 / 6 (6) |

The last row exchanged two model-written global rules for two repository decisions. Stated-first ordering changed
nothing in that sample because stated facts were already newest. Two alternatives were rejected: only **9 of 65**
global rules appeared in three days of recall logs, making recall-hit ordering unsuitable for the rules the card
was meant to deliver; a hard half-card cap displaced **3** stated repository decisions with **3** model-written
global rules. These findings explain the historical selection rule, not the later removal of the card in #656.

## Splitting and answer-shape failures

Two limited DeepSeek dry runs preceded the larger [reasoning study](reasoning-off-2026-10.md):

| Path, 22 October | Sample | Result |
|---|---|---|
| Vet candidate split | 6 live candidates | 3 kept, 3 split; nothing written |
| Dream split on a Mac base, `-since 2026-10-22` | 18 facts | 5 split, 9 groups, no refused split; 2 min 36 s; nothing written |

The frequency on a larger queue or whole base was unmeasured. Sources:
[PR #235](https://github.com/juev/memcue/pull/235), [PR #237](https://github.com/juev/memcue/pull/237).

After reasoning was disabled for review, object-shaped split parts failed decoding in **2 of 4** dry runs over
the same **6** candidates on 0.5.0. Supporting both strings and objects with text yielded **6 of 6** decoded dry
runs, **0** failures. This was a parser check, not proof of unchanged semantic quality. Sources:
[#270](https://github.com/juev/memcue/issues/270), [PR #271](https://github.com/juev/memcue/pull/271).

## The first vector reader

[#48](https://github.com/juev/memcue/issues/48) used **322 facts and 120 real prompts** with blind-judge labels:
**35** memory-needing prompts got nothing from lexical recall; vector top-1 would offer a useful fact for about
**11**. Vector/lexical top-2 overlap was **0.20**. Vectors kept only **10 of the 21** useful facts found by words.
A cosine floor of **0.55** kept **20 of 35** misses but also **33 of 37** prompts needing no memory.

The implementation's follow-up used **233 bge-m3 vectors** on the same 120-prompt labelled set. The denominators
differ from the earlier pool; do not merge them. Sources: [PR #49](https://github.com/juev/memcue/pull/49),
[later vector architecture](../vectors.md).

| Setting | Prompts with a fact | Labelled useful facts | All facts | Facts into prompts needing no memory |
|---|---:|---:|---:|---:|
| Words only | 73 | 13 | 127 | 45 |
| Fallback margin 0.75 | 115 | 15 | 214 | 64 |
| Fallback margin 1.0 | 87 | 13 | 159 | 52 |
| Fallback margin 1.5 | 73 | 13 | 127 | 45 |
| Fallback floor 0.62 + margin 0.1 | 82 | 13 | 147 | 51 |
| Vector only, margin 1.0 | 46 | 3 | 64 | 14 |
| Vector only, floor 0.62 | 49 | 8 | 84 | 25 |

The labels covered lexical-proposed pairs only; newly added pairs were unlabelled, so these rows could not establish
the vector reader's gain. That limitation motivated the [gold set](gold-set-2026-10.md).

The later Jev `score`/`noul` threshold table is already in
[jev-judge](jev-judge-2026-10.md). Its implementation dry run on **235 approved facts / 41 candidates** retired
**4** genuine duplicates at **0.58–0.83**, left **37** to the DeepSeek review model, and finished with **28 approved /
13 retired, 0 errors, $0.0786**. These model/reviewer verdicts are not independent truth labels. Sources:
[#51 comment](https://github.com/juev/memcue/issues/51#issuecomment-6304474154),
[PR #52](https://github.com/juev/memcue/pull/52).

The 0.3.0 pilot initially produced **0 rerank rows over 180 prompts** because `gold_set.py` passed texts where the
helper expected ID/text pairs. A locally patched script then produced **177/180 rows, 396k input tokens, $0.0166,
0.79 s median**. Source: [#61](https://github.com/juev/memcue/issues/61),
[PR #63](https://github.com/juev/memcue/pull/63). This is a tooling failure followed by a repaired run, not an
endpoint-quality result. [The pilot record](../models.md#why-the-pilot) preserves the reader and truth-sample
comparison. [#65](https://github.com/juev/memcue/issues/65) and [PR #73](https://github.com/juev/memcue/pull/73)
clarify that its **2,571 approved facts** exceeded the **400/1,700** duplicate-request cap: the pilot did not measure
a duplicate-stage benefit. Later chunking tests do not retroactively add one.

[PR #151](https://github.com/juev/memcue/pull/151), for [#132](https://github.com/juev/memcue/issues/132), benchmarked
**10,000 facts, 128 dimensions**, on **Apple M4 Pro, Go 1.27**: a **2,000**-vector pool took about **9.1 ms** and
allocated **9.7 MB**, against **45.3 ms / 55.3 MB** for all vectors. Older facts then contributed lexical candidates
only. Repeat count was not recorded. This is a synthetic benchmark of the removed vector path.

When vectors were deleted, a Mac-base copy shrank from **24,698,880 to 11,382,784 bytes**: **2,684 vectors → 0**,
**8,231 fact rows unchanged**. First open with delete/VACUUM took **0.14 s**, the next **0.08 s**; integrity check
was `ok`. Source: [PR #262](https://github.com/juev/memcue/pull/262), for
[#260](https://github.com/juev/memcue/issues/260). The recall-quality reason is in
[one-model](one-model-2026-10.md); file shrinkage alone does not establish quality.

## Accounting and shelf baseline

[#258](https://github.com/juev/memcue/issues/258) reported one Hermes day of **140k input / 43k output** extraction
tokens and **966k / 4k** vet tokens, all with `cost_usd=0`. Endpoint token accounting and reported provider dollars
were different quantities; these zero-dollar fields did not mean free processing. No price conversion was recorded
in that issue. The later per-task cost study is [dream-cost-643](dream-cost-643-2026-11.md).

Before the shelf change, [#433](https://github.com/juev/memcue/issues/433) counted **890 IDs / 402 live facts**:
**271 host, 58 repo, 36 service, 29 global, 8 unscoped**. **92 extraction runs** stored **191** facts and rejected
**148**, including **137** for evidence outside a RESULT block. These observations motivated provenance-based
shelving. They did not measure later shelf capture or answer use; those have separate stages in
[research-shelf-531](research-shelf-531-2026-10.md) and
[research-shelf-confirm-531](research-shelf-confirm-531-2026-10.md).
