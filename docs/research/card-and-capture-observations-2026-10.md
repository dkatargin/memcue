# Card delivery, capture and ordinary-work adoption, October 2026

Historical observations from 26–29 October, with a later card-admission probe from 3 November. These fill gaps in
the individual studies, using aggregate counts only. Private bases, session lists, note contents and local harnesses
are not shipped or reconstructed. The card and its channel-labelling task were removed in #656; the measurements
below explain earlier decisions, not current behavior. See the [research index](README.md).

## Legacy facts and a rejected broad cleanup

[#457](https://github.com/juev/memcue/issues/457) originally counted **14** version-naming facts on Hermes 0.16.0,
newest version **0.14.0**, and **1** expired fact, already hidden by search. A later
[PR #466](https://github.com/juev/memcue/pull/466) dry run on a different local-base copy, binary built as **0.16.0**,
proposed **5** retirements and found **0** expired facts. It did not run against the issue's Hermes base or establish
that all 14 were retired. Historical state/behavior separation was imperfect: one still-true binary-location fact
was retired, while other old-version facts without the recognized shape stayed. This upkeep ended with #494.

The corrected body of [#475](https://github.com/juev/memcue/issues/475) inspected **416 live Hermes facts** on 0.17.0:
**6** were pure state; **4** of those had no source and legacy kinds. Across that base there were **37** legacy-kind
facts (**14 event, 14 repo, 7 procedure, 2 other**) and **31 source=agent** facts. State entered through legacy data,
direct agent writes and a pitfall label that bypassed the state check. The
[first comment](https://github.com/juev/memcue/issues/475#issuecomment-6411889001) says the body was rewritten after
the original mixed periods or blamed the wrong path; the earlier body is not in the supplied snapshot.

The owner initially chose to retire all old kinds, then narrowed the scope after a copied-base dry run:
**700** old-kind facts and **75** more under the full state rule, on about **3,400** Claude Code facts. Real
procedures and pitfalls would be lost. The final branch retired **6** on Hermes (**5 of the original 6** pure-state
examples; the CLI version stayed) and **1** on Claude Code. Only moments such as restart/PID, line count or mtime
were swept, excluding rules/decisions. Sources:
[initial decision](https://github.com/juev/memcue/issues/475#issuecomment-6412094964),
[narrowed decision and dry run](https://github.com/juev/memcue/issues/475#issuecomment-6412399660),
[PR #482](https://github.com/juev/memcue/pull/482).

A later [#475 comment](https://github.com/juev/memcue/issues/475#issuecomment-6412599297) counted **3,612** latest
active Claude Code facts: **775 (21%)** had legacy/empty kinds (**277 event, 188 procedure, 157 repo, 78 other,
75 empty**). **771** had no source, **4** were user-sourced; **276 of 277 events** had no expiry. The listed event
creation-date counts, **156 / 7 / 113**, sum to 276, not all 277 events. This later count neither reverses the
narrowed cleanup decision nor proves these facts were useless. It defines live by latest `status=active`;
review-state eligibility is not separately counted. [PR #482](https://github.com/juev/memcue/pull/482) compresses
the rejected sweep to 775 of roughly 3,400; keep its shorthand separate from the staged 700+75 description.

## Why the research shelf was empty

[#476](https://github.com/juev/memcue/issues/476) found **0 of 416** facts on the shelf. Over **14 days**, interactive
web use occurred in **11 of 70 sessions**, last at **24 October 13:31**; none of the primary sessions used an external
tool after the shelf shipped. Most external reading happened in cron/subagent contexts, which did not extract.
Thus the original kind-policy explanation was insufficient: the sessions doing research wrote no facts.

One documented default had also been rejected as kind `other`; that was a separate prompt problem, not an estimated
failure rate. The [owner's decision](https://github.com/juev/memcue/issues/476#issuecomment-6412095316) enabled
external-evidence-only cron extraction. #494 then removed transcript extraction, including this cron path. The
later [#531 confirming study](research-shelf-confirm-531-2026-10.md) measures the agent-written design instead.

## Ordinary-work search adoption: three different windows

[#478](https://github.com/juev/memcue/issues/478) replaced a mixed-period count with the following account. Of
**70** selected interactive sessions, **20** ordinary sessions preceded installation, approximately **18** belonged
to push mode, and **0 ordinary sessions** yet belonged to pull mode. All **13 of 13** pull-era Matrix sessions were
about memcue. Earlier 4/15 or 1/38 counts therefore did not measure ordinary-work adoption under pull mode.

| Measurement | Ordinary sessions | Searched | Wrote | Limitation |
|---|---:|---:|---:|---|
| Through 27 October 06:00 UTC | 4 | 4 | 1 | 2 unlabelled; below the required 10 sessions |
| 24 October 21:48 MSK through 29 October 02:24 MSK | 17 | 15 (88%) | 3 | One reviewer; invocation, not answer quality |

The final selection required source `android`, `matrix`, `telegram` or `tui`, a session beginning after the pull
switch and a user message longer than **45 characters**. A reset conversation counted separately. Manual title and
first-message classification excluded **20** memory-related sessions, **9** subagents, empty sessions and a greeting.
The **2** sessions without search were general-knowledge questions. The decision was to keep pull mode without a
nudge, tool-result hint or prefetch. First-turn versus later search and benefit to answers were unmeasured. Sources:
[partial comment](https://github.com/juev/memcue/issues/478#issuecomment-6435644025),
[final baseline and decision](https://github.com/juev/memcue/issues/478#issuecomment-6491714358).
The private per-session list remains only in the source; no session IDs or personal topics are copied here.

The older [Hermes plugin study](hermes-plugin-2026-10.md), [0.14 study](pull-hermes-014-2026-10.md) and
[0.16 study](pull-hermes-016-2026-10.md) retain their original windows; their adoption estimates must not be compared
as if the same population and period were used. The later #647 issue body's statement that #478 could not establish
ordinary-work adoption is superseded by the final comment above. That comment still does not establish answer quality.

## A whole-turn test did not describe the live pull path

[#474](https://github.com/juev/memcue/issues/474) fed **11 real user turns** to the 0.17.0 provider on a copy with
**416 live facts**: top three had **9 useful / 8 related / 12 noise** among **29** labelled facts, with a useful fact
on **6/11** turns. Three shortened queries found **4/4, 2/2, 3/3** useful facts; one full-turn query had **0/5**.
No turn was empty, but **2** returned one irrelevant fact. This supported a query-narrowing proposal only if the
model actually sent whole turns.

The [re-check](https://github.com/juev/memcue/issues/474#issuecomment-6411886731) read all **72** live search calls in
the same **14-day** store: median **6 words**, **71/72** at most **12 words**, one at **20**, and **0/72** equal to a
user turn or a substring of at least 40 characters. The auditor had supplied whole turns; pull-mode `prefetch`
returned empty. The issue closed on a false premise, with no query-narrowing change.

## Startup truncation and the budget regression

On 0.17.0, **6 of 53** Claude Code sessions since 25 October crossed the context threshold. The longest context
shown fully was **9,973 characters**, the shortest moved to a file **10,165**; the preview was **2 KB** and no
transcript read the saved file. The card grew **24 → 50 facts / 5,032 → 9,230 characters** in a day, plus about
**1,900** for the note. Source: [#480](https://github.com/juev/memcue/issues/480).

A [probe](https://github.com/juev/memcue/issues/480#issuecomment-6412924279) with **2** SessionStart hooks of
**8,933 characters each**, **17,866 total**, delivered both fully: the limit was per hook. The selected three-part
delivery allowed **9,500 characters per part**, splitting only between lines. The cited card contained **31 global
rules / 18 repository decisions**. Of the 31 globals, **14** were extracted user words and **16** came from archived
notes; the comment does not assign the remaining one. This evidence motivated preserving stated rules across parts.

Agents also placed flags after search text: **8 of 9** ordinary-work searches in [#481](https://github.com/juev/memcue/issues/481).
The listed examples account for **4** `-n 5` and **3** `-in all` calls; no form is given for the eighth.
Two `-in all` calls returned unrelated globals before the flag-order fix and wanted facts after it. These are
observations of CLI use, not an A/B answer-quality sample.

[#487](https://github.com/juev/memcue/issues/487) corrected its initial claim that the card had no ceiling: it had a
**3,500**-character budget and **400**-character line clipping, but stated facts bypassed the budget. The live Hermes
card was **18 rules / 3,079 characters**; **13** user-sourced rules held **2,003 of 2,870 fact-text characters**.
The base had **417 live facts / 26 rules / 18 global rules**. A separate repository-cwd copy probe measured:

| Card | Characters | Fact lines | Reported omitted |
|---|---:|---:|---:|
| 0.17.0 | 5,727 | 36 | No hint |
| Branch, default budget | 3,471 | 23 | 14 |
| Branch, budget 1,200 | 1,183 | Not reported | 30 |

At budget 1,200 the log recorded `used=1008`, `chars=1183`, `excluded=0`, `omitted=30`. The omission count and
rendered lines are separate counters, not a claimed partition of the earlier 36-line card. Source:
[PR #491](https://github.com/juev/memcue/pull/491).

Applying this shared budget to Claude Code contradicted #480:

| Repository | Before #487, split startup | 0.18.0 |
|---|---|---|
| memcue | 53 fact lines; 9,329 + 1,164 characters | 22 lines; 5,175 characters; 72 omitted |
| Anonymous work repository | 54 lines; 9,374 + 963 characters | 21 lines; 203 omitted |

[#495](https://github.com/juev/memcue/issues/495) restored stated facts outside the budget in split startup only.
[PR #496](https://github.com/juev/memcue/pull/496) rechecked both copied-base cards: stated lines matched #480;
one unstated fact per card was displaced by the omission hint (**45 / 174 omitted**). These counts are different
from the issue's pre-fix omissions. The card was later removed altogether, not merely made larger.

## Mirrors, notes and the move to agent-written memory

[#488](https://github.com/juev/memcue/issues/488) found **14** mirrored facts: **7 global**, **0 typed**. It motivated
kind/scope derivation at mirror time. [#489](https://github.com/juev/memcue/issues/489) measured **11 entries /
2,190 of 2,200 characters** in one note file, all verbatim in the base, plus a profile of **1,117/1,375 characters**.
The combined notes/profile/card block was **6,386 characters**. Its base had **417 live / 532 retired facts**.

A later [PR #492](https://github.com/juev/memcue/pull/492) probe of `memcue notes` found **15 of 17 entries** already
facts, **2,852 of 3,262 characters**; database size and mtime stayed unchanged. This is a different measurement,
not evidence that the requested three-entry residual note or 1,500-character reduction was achieved.

[#494](https://github.com/juev/memcue/issues/494), **26 October**, measured **3,618 live Claude Code facts**, of which
**3,015 (83%)** had note-file origins; the archive held **314 notes**. There had been **60** notes written in
1–19 October and **160** in August. The estimated **20–30 facts/day** from about ten facts/note was an extrapolation,
compared with extraction's reported **57/day**. Only **5 add calls** occurred in **1.5 days**, mostly tests. Vet retired
**206 of 527** extracted facts; extraction/review over 1.5 days used about **657k input / 178k output tokens**.
**16 of 31** global card rules came from notes.

These observations motivated the owner's decision to remove extraction without a shadow comparison. They did not
prove agent-written memory superior. The [follow-up decision](https://github.com/juev/memcue/issues/494#issuecomment-6415716911)
removed vet/suspect upkeep too; facts made wrong by an unobserved external change were no longer caught automatically.

## Failed or inconclusive synthetic checks

- [#509](https://github.com/juev/memcue/issues/509): an isolated fabricated global rule accepted as `source=user`
  reached the next card; this did not show fabricated rules in the live base. The
  [owner's decision](https://github.com/juev/memcue/issues/509#issuecomment-6435325777) trusted session-model
  attribution and declined a pseudo-verification gate, without claiming attribution was correct.
- [#511](https://github.com/juev/memcue/issues/511): the discarded E2E prototype had **64 answers without a valid
  verdict**, after two repair rounds. Pattern grading mishandled negation/paraphrases, existing versus newly captured
  facts and process errors. No correctness or no-harm result can be extracted from it. The
  [owner declined](https://github.com/juev/memcue/issues/511#issuecomment-6436047598) a separate E2E system;
  [#510](search-synthetic-510-2026-10.md) delivered search-only evidence.
- [#513](https://github.com/juev/memcue/issues/513): the existing Hermes filter dropped **4 of 4** synthetic
  contrasting/conditional rules. The proposed smarter patch was
  [not merged](https://github.com/juev/memcue/issues/513#issuecomment-6436048189). The actual filter-removal study,
  including the extra context cost, is [card-no-plugin-filter-456](card-no-plugin-filter-456-2026-10.md).
- [#515](https://github.com/juev/memcue/issues/515): a separate binary heuristic retained only the shorter of **2**
  distinct rules sharing the first **60 characters**, losing an appended instruction. Its live frequency was unknown;
  the [owner declined](https://github.com/juev/memcue/issues/515#issuecomment-6436177027) that change as well.

## Later card-admission checks, November 2026

[#637](https://github.com/juev/memcue/issues/637) later counted **97** active repository rules/decisions, **42** citing
issues; the session-start median was about **24,000 characters** over **9 sessions since 31 October**. On 3 November
the repository part took **93 of 112 lines**, while **10 of 18** agent-attributed global behaviour rules did not fit.
These counts motivated a tracker-backed-decision filter, but citation alone did not prove the issue contained the
decision: the [comment](https://github.com/juev/memcue/issues/637#issuecomment-6679384433) points out that #621's DSH
plan was narrowed only in PR #631/#630. The filter was not trialled; the later
[card/search split](card-search-split-636-2026-11.md) and #656 superseded it.

[#600](https://github.com/juev/memcue/issues/600) used one invented scenario, two conversations and seven fresh-session
probes on **2 November**: Sonnet 5.5 with memcue versus Letta Code on DeepSeek V4.1 Flash. A global decision was
stored but not on the card; the memcue probe did not search or mention it, while Letta asked about it. Different
models and one run per arm establish a mechanism, not a comparative success rate. The full seven-fact capture
comparison is in [preference-capture-601](preference-capture-601-2026-11.md).

[PR #603](https://github.com/juev/memcue/pull/603) counted **8 stated global decisions / 2,148 characters** on a copy;
**6** belonged to one project/task and were moved. With global decisions admitted, the same-copy card changed
**3,459 → 3,493 characters / 16 → 18 facts**. The isolated Sonnet probe then named the decision and asked before
acting; remote access was stubbed. That was a bounded repeat of one scenario.

[PR #629](https://github.com/juev/memcue/pull/629), for [#625](https://github.com/juev/memcue/issues/625), measured an
Opus `dream -run -all` on a copied base and state:

| Counter | Result |
|---|---|
| Initially unlabelled globals | 63: 30 user rules, 4 user decisions, 29 agent rules |
| Labelled after splits/promotions | 69 |
| Channels | 32 behaviour (46%); 15 repository, 9 command, 8 knowledge, 4 file, 1 outdated |
| Refused | 0 |
| Whole run | 12 passes, 68 calls, $17.81, also 48 scope moves and other backlog work |
| Three channel calls in pass 1 | About $0.85 estimated at $0.28/call, not separately measured |

The source separately reports behaviour in **13 of 32 user facts** and **18 of 29 agent facts**; these source subsets
do not account for every channel-labelled fact and must not replace the 69 denominator. On a session start with
**85 repository lines**, global lines changed **27 → 30**. The report describes those 30 as 31 eligible behaviour
facts minus one, while the whole-run table has 32 behaviour labels; it does not reconcile that selection difference.
No Hermes/DSH session-model dream was manually verified. Channel labelling ended with #656; the cost estimate above
must not be treated as a measured marginal task cost.

[#634](https://github.com/juev/memcue/issues/634) later observed **69** unlabelled global rules/decisions, **32**
agent-sourced, after installing 0.28.0. They did not by themselves make a dream due. That was a due-check observation,
not an answer-quality trial; [PR #650](https://github.com/juev/memcue/pull/650) added channel debt to the check, then
#656 removed the channel task altogether.
