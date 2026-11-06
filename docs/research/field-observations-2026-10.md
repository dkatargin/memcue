# Field observations and corrected diagnoses, October 2026

These records fill gaps between the controlled studies. They are historical observations on private bases, often
one pass or one reader's judgement. Bases, real prompts, fact texts and local logs remain private and are unavailable
in this checkout. Only aggregate results are archived here; the linked sources distinguish observed behavior from
proposed fixes. No experiment was rerun for this archive. Related reports are in the [research index](README.md).

## Early timing and repeatability

On **20 October**, a **2,480-fact** base produced **393 groups, 66 actions, $7.58, 13 minutes** for
`dream -all -dry-run`. An earlier dry/real pair on a copy returned **13 versus 11 actions**, motivating saved plans
instead of paying for a second model decision. The earlier pair's model/configuration and elapsed time are not
recorded in [#4](https://github.com/juev/memcue/issues/4). The full triage study, including the 393/395-group
rebuild mismatch, is already in [dream-triage](dream-triage-2026-10.md).

The tokenizer decision in [#22](https://github.com/juev/memcue/issues/22) used **147 real prompts**: **1** port,
**0** IP addresses and **4** versions. Its
[correction](https://github.com/juev/memcue/issues/22#issuecomment-6294490452) established that retaining a ticket
term was insufficient without relaxing the two-known-term gate. Later number-term results supersede the decision
to drop versions; see [number-terms](number-terms-2026-10.md).

On **22 October**, four judge+bge-m3 hook runs over **228 active Hermes facts** took **916, 949, 822, 922 ms**,
median **919 ms**; cleanup from **277 to 228** did not change it. A dream dry run over **263 facts / 43 groups**
took **6.5 minutes / 131k output tokens**. The initial attribution to remote requests was explicitly a guess;
[the later breakdown](../evaluation.md#latency-october-2026) supplied evidence. Sources:
[#213 first comment](https://github.com/juev/memcue/issues/213#issuecomment-6335033364),
[#213 resolution](https://github.com/juev/memcue/issues/213#issuecomment-6338162103).

## Recall during the 0.5.x upgrades

The earlier [#221 diagnosis](https://github.com/juev/memcue/issues/221#issuecomment-6335234659), **22 October**,
used main `d3960cb`, **241 active Hermes facts**, Jev and bge-m3. **29** facts needed vectors; filling them on a copy
put a corrected target at vector rank **2 / judge 0.76 / served first**, and an added target at rank **3 / 0.64 /
cut by MaxFacts**. **80 of 80** FTS candidates failed the lexical gate on one short question. Vector top-ten ranges
were **0.60–0.69** and **0.50–0.54** on two questions. The second question's claimed answer was absent from the base:
its nearest fact described where configuration lived, not its value. This corrected the issue's original claim
that both misses were retrieval failures. The
[live follow-up](https://github.com/juev/memcue/issues/221#issuecomment-6335617785), build `1642c46`, filled **29/29**
and then **0** remained; corrected target/second-slot judge scores were **0.77/0.71**, and another version probe
scored **0.97**. A subsequent correction embedded one fact and left zero missing. Stale-fact preference was observed
before the fill but not reproduced on those follow-up prompts; no full before/after eval set was delivered there.

Both field runs below used **30 real user prompts**, fresh session IDs, copied bases and isolated state, with
`cwd` outside a repository. They were different base snapshots, not a controlled before/after quality experiment.

| Release and snapshot | Words + Jev | Words only |
|---|---|---|
| 0.5.1, 244 active facts, 863 rows, schema 5 | 24/30 prompts, 42 facts; p50 417 ms, p90 489 ms | 19/30 prompts, 31 facts; p50 38 ms |
| 0.5.2, 265 active facts, schema 5 | 26/30 prompts, 48 facts; p50 420 ms, p90 551 ms | 21/30 prompts, 32 facts; p50 45 ms |

The 0.5.1 base had **241 of 244** facts without queries. Its **42** deliveries were approximately **16 useful,
11 on-topic, 15 removed-state**, by one non-blind reader. Vet had handled a separate **3-candidate** session as
**2 approve / 1 retire**. The issue's claim that dream never backfilled already-seen facts was read from code;
no expensive whole-base dream was run to prove it. Source: [#276](https://github.com/juev/memcue/issues/276).

At 0.5.2 the first dream logged **268 expanded**, **263 of 265 active facts with queries**, and **6 actions
(3 retire, 3 correct)**. One reader labelled the Jev deliveries **18 useful / 20 on-topic / 10 noise-or-stale**,
the lexical ones **13 / 8 / 11**; these were not blind labels. Jev answered **7** prompts silent under words and
stayed silent on **2** cron deliveries; only **4 of 19** jointly answered prompts had identical fact sets.
Across **14 live gateway turns**, judge latency was **p50 891 ms, p90 1,279 ms**. The source attributed the gap from
isolated probes to TLS startup, without a separate timing experiment. Source:
[#287](https://github.com/juev/memcue/issues/287).

The same report found **8** stale facts against **3** from the documented grep. They were retired by hand; the
full check also corrected **7** facts. Its kind counts were **111 environment, 83 pitfall, 17 event, 12 rule,
10 repo, 10 other**; those listed counts do not partition all 265 active facts. They must not be silently completed.
The final [resolution](https://github.com/juev/memcue/issues/287#issuecomment-6355527552) records query expansion on
add, origin handling, suspect checks and event expiry. The proposed skip-judge gate was measured and rejected in
[judge-gate](judge-gate-2026-10.md); [listwise](listwise-2026-10.md) records why the alternative reader stayed opt-in.

The [0.5.2 rollout comment](https://github.com/juev/memcue/issues/285#issuecomment-6349509247) records a Mac dream
with **71 new facts, 6 actions, 25 expanded**, and **1 failed expansion call** whose **25** facts remained owed.
The Hermes check reduced missing queries **233 → 2**. These counters describe separate rollout probes, not a
replacement denominator for #287. DSH's desktop profile remained at **0.4.0** in that comment.

## Suspect checking and correction gaps

The [0.5.3 rollout](https://github.com/juev/memcue/issues/294#issuecomment-6350673360) found **6 suspects / 1 retired /
8 candidates decided** on the Mac, and **4 suspects / 1 retired / 3 historical facts kept** on Hermes. It also exposed
a false retirement: a still-valid diagnostic warning was kept in **2** dry runs and retired live. The fact was
reopened and corrected manually. [#296](https://github.com/juev/memcue/issues/296) proposed temperature 0 and a
second agreeing answer; its [delivery comment](https://github.com/juev/memcue/issues/296#issuecomment-6355526923)
records those changes and a wider version signal. That implementation statement is not a measured guarantee of
deterministic model behavior.

A [separate #296 check](https://github.com/juev/memcue/issues/296#issuecomment-6354202462), on **261 active facts**,
found **4** suspects, **3** correctly kept historical facts and **1** retired. It missed **3** false claims about
schema or latency that lacked a version/variable signal. All three were retired manually. The reported current
latency was **p50 360 ms** on a stand and about **420–450 ms** in the gateway. A broader signal would have nominated
about **20 of 261** facts, but that was an estimate, not an executed comparison. The entire suspect workflow was
later removed by #494.

On 0.5.3, `add` wrote **8** queries in **1.24 s** with the API configured; without it, queries stayed empty.
The same report found **13 of 257 active facts** without queries, all corrections: **10** dream corrections from
the upgrade night, **3** manual corrections. Its opening installation count was **261**; the issue used a later
257-active count for the query audit. [#297](https://github.com/juev/memcue/issues/297) and
[PR #299](https://github.com/juev/memcue/pull/299) record the same-run expansion fix, followed by the
[closure](https://github.com/juev/memcue/issues/297#issuecomment-6355258381). No new semantic recall A/B accompanied
that fix in these sources.

## The single-term diagnosis was narrowed

The preceding project-key survey in [#343](https://github.com/juev/memcue/issues/343) inspected **79 repositories**
on one workstation plus an archived base. It found directory/remote aliases, name collisions and owner-qualified
scope splits; counts per failure type were not reported. It motivated remote-derived keys, not a measured recall
gain. The separate scope/ranking comparisons are in [scope-filter](scope-filter-2026-10.md).

[#355](https://github.com/juev/memcue/issues/355) observed 0.7.0 on **428 live facts**: two turns returned **0** facts
in **12.8 / 14.1 ms**. Search returned **10** facts and placed the answer at rank **9**. The agent eventually used
**2 searches**, returning **45 unique facts / 18,670 characters**. The issue initially described the one known term
as rare and proposed a lower floor or fallback.

The [re-check](https://github.com/juev/memcue/issues/355#issuecomment-6387622680) used **437 indexed facts**: that
term occurred in **172**, about **40%**, so it was not rare. Lowering `min-terms` to **1** served **2 noise facts**,
including stale state; the answer remained rank 9. A provider search fallback would serve the same top two.
Only observable stop reasons and configurable floors went ahead. Silence on that prompt was accepted; the original
rare-term and fallback recommendations were withdrawn.

The later provider-limit probe on a copied base, [#477](https://github.com/juev/memcue/issues/477), found `limit: 0`
silently used the **5**-fact default, `limit: -3` failed with the binary's minimum-limit error, and `limit: 3`
returned **3** facts. This was argument validation, not search-quality evidence; [PR #479](https://github.com/juev/memcue/pull/479)
fixed zero handling.

## Operational probes after extraction was removed

- The [#542 rollout comment](https://github.com/juev/memcue/issues/542#issuecomment-6465167978), **0.21.2, 28 October**,
  found **0** duplicate-version groups on each of three live bases, and **0** missing number terms on the two
  Claude Code bases. Copied-base probes checked the shelf union and separator fix; Hermes provider tests were
  **76/76**. No actual Claude Code, Hermes or DSH agent session on that release was checked.
- [#577](https://github.com/juev/memcue/issues/577), **0.23.0, 29 October**, records one external-system finding refused
  as installation state because it contained a compatibility version range. The agent tried **3** times and
  abandoned it; a shelf-scoped write of the same text was accepted. The changed refusal message named the shelf and
  removal of incidental state. No comparative agent-recovery or recall-quality run was recorded for the message fix;
  the private technical finding itself is excluded from this archive.
- [PR #571](https://github.com/juev/memcue/pull/571), **29 October**, on a Mac-base copy without an API endpoint:
  `session-start -part 1` returned in **0.97 s**; a background Opus pass handled **141 fresh facts**, **27 split**,
  **57 expanded**, **15 retired or corrected**, **1 refused**, **$2.58**, **103 s model time**. One pass does not
  establish a general startup or cost bound.
- [PR #583](https://github.com/juev/memcue/pull/583), for [#582](https://github.com/juev/memcue/issues/582): on a copy
  with **22,857 versions**, **1,386 active facts** were relabelled from empty source to `agent`; three startup parts
  and four searches stayed byte-identical. Warm search was **26 ms versus 25 ms**. The issue separately counted
  **144** empty-source active facts in the Hermes base. Source relabelling did not independently verify authorship.
- [#588](https://github.com/juev/memcue/issues/588) records **5** fact histories ordered differently after two machines
  relabelled; [PR #587](https://github.com/juev/memcue/pull/587) supplied a deterministic tie order. The release
  acceptance checklist is not a new measurement. The PR separately checked all five real files: both merge orders
  produced one file with source labels and queries preserved, and a second open wrote nothing.
- [#593 rollout](https://github.com/juev/memcue/issues/593#issuecomment-6497133645), **0.26.0, 29 October**: with the
  ambient token removed, a bare model call failed authentication, while a dream using the configured token file
  completed **160 fresh facts / 72 groups / 5 calls / no error**. No token, token-file contents or local credential
  paths are reproduced here. [#596](https://github.com/juev/memcue/issues/596#issuecomment-6498035912) later checked
  the explicit expired-authentication error on 0.26.1; that was error reporting, not a recall experiment.
- [#639](https://github.com/juev/memcue/issues/639) observed one failed model write on **0.28.0**, using legacy kind
  `other`, then recovery on the next call. [PR #651](https://github.com/juev/memcue/pull/651) clarified that search
  may read legacy `repo`/`other` labels while add accepts six kinds. No failure-frequency or quality comparison was run.
