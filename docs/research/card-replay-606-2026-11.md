# Session-card classification and exploratory replay (#606)

Follow-up to [the static audit](card-audit-606-2026-11.md). This note concerns an offline, current-card counterfactual, not reconstruction of the memory or repository state of a past session.

**Result: inconclusive; keep the current card.** The fixed 24-request comparison produced 13 ties and 11 UNKNOWN outcomes, with no scored win or loss. The missing outcomes do not establish absence of harm. #606 remains open; this note completes an exploratory pass, not the admission decision. Counts are in [the companion JSON](card-replay-606-2026-11.json).

## Inputs and boundaries

- Three repository contexts and one global-only context; 325 delivered fact occurrences, representing 157 unique facts.
- Twenty-four real transcript requests, selected before answer generation: A=3, B=8, C=8, G=5. The sample is exploratory, not a representative sample of all work.
- A/B/C are anonymous labels local to this follow-up. They must not be joined by letter to the independently randomized repository letters of the static audit.
- Cards and cases were frozen before generating answers. The current card is intentionally replayed against earlier requests; this does not establish what memory those original sessions received.
- Both answer arms have the same two read-only tools: search a private copied store and read an allowlisted tracked repository file. There is no shell execution, file modification, commit, push or deploy. These answers measure advice under this restricted interface, not end-to-end task completion.
- Real input and output remain private. Only anonymous counts, public code and invented fixtures are published.

## Semantic classification

One pinned OpenAI model, `gpt-6.1-sol`, classified the 157 unique facts. The channels are intended delivery categories, not new production kinds. A fact may be borderline or combine several instructions; one primary channel is an approximation.

Unique-fact counts:

- Standing behaviour: 44.
- Repository-specific moment: 84.
- Command moment: 8.
- File moment: 3.
- Searchable knowledge: 12.
- Outdated or one-off: 6.
- Semantic unknown: 0.

Confidence was high for 139 facts and medium for 18, with none low. These are the model's confidence labels, not calibrated accuracy or independent semantic ground truth.

Counting occurrences actually carried across the four contexts gives a different denominator: behaviour 155, repository 93, command 29, file 12, knowledge 24, outdated/one-off 12, unknown 0. A fact can occur in several cards; these counts must not be compared directly with the unique-fact counts.

All 157 accepted labels were checked against their source row, canonical SDK arguments, finished adapter reply and parsed label fields. Earlier failed attempts were retained: two real-batch timeouts and one synthetic-calibration timeout. No real fact received more than two primary classification attempts; successful labels were not regraded. This verifies evidence integrity, not the correctness of the model's interpretation.

## The fixed candidate

The candidate keeps behaviour, semantic unknowns and every non-high-confidence label. It also keeps repository `rule`/`decision` facts whose metadata says `user` or `user_confirmed`, regardless of their primary channel. That metadata is an attribution, not proof of authorship. Only the remaining high-confidence facts are removed.

Before any paired answers, this policy produced:

- A: 67 → 42 facts; 17,027 → 12,682 delivered characters.
- B: 72 → 50 facts; 19,296 → 14,983 delivered characters.
- C: 122 → 102 facts; 28,257 → 25,258 delivered characters.
- G: 64 → 46 facts; 16,480 → 13,504 delivered characters.

Across one card of each context, that is 325 → 240 occurrences and 81,060 → 66,427 characters: 85 occurrences and 14,633 characters removed, a character reduction of 18.05%. This is not a measured token, latency or answer-quality improvement. The 24-request mix has a different weighting, and tool use can add context back.

## Repository decisions attributed to the agent

This is the exact intersection of repository scope, kind `decision` and source `agent`, not a broader mixture of rules, decisions or tool-origin facts:

- A: 7 facts, all classified as repository-specific; all removed by the fixed candidate.
- B: 1 fact, classified as repository-specific; removed.
- C: 3 facts, all classified as knowledge; all removed.
- G: 0 facts.

There is no separate ablation for this intersection. A result for the full candidate cannot establish the causal effect of removing these decisions alone.

## Existing program-hook coverage

Among the 157 labelled facts, 11 have command/file as their primary channel: 8 command and 3 file facts. The measured local program integration cannot directly deliver any of those same IDs because its eligible fact kinds and the carried kinds are disjoint. The exact-ID count is therefore 0/11.

A real-binary, invented-only probe checked the distinction: three matching facts of different kinds yielded one through the card and the other two through the local hook, without executing the command. This does not establish whether different stored facts convey equivalent advice, and it does not verify the configuration of another device. The three file-labelled facts are candidates for the delivery question in #598, not measured proof that a Read hook would improve an answer. The eight command-labelled facts are not already handled merely because a program hook exists.

## Replay safeguards and verification

The answer and judge calls pin the existing OpenAI Codex client, model and official HTTPS origin. Redirects, SDK retries and provider fallback are disabled. Synthetic judge calibration must pass before real requests are submitted. Arm and judge order are counterbalanced with fixed seeds; the candidate is not selected from answer outcomes.

A search infrastructure failure, exhausted tool budget, unfinished answer or invalid judgment cannot become a win. An independent reviewer reproduced a bug where a later final answer masked a failed tool; the corrected version stops the arm and leaves the pair UNKNOWN and unjudged. Exactly 12 successful tool calls followed by a finished answer remain valid. Ordinary policy refusals and successful empty searches are distinct from infrastructure failures.

The final synthetic suites executed 50 tests: audit 17, labels 11, replay 22, with an empty HOME and blocked Python sockets. The older static-audit tests still emit ResourceWarnings about unclosed handles. Real-binary copied-store probes checked nonempty/empty search, tracked-file reads and path refusal. Independent finite reviews approved the transport/accounting boundaries and final eligibility correction.

Credential-shaped refusals are a finite regex screen, not comprehensive secret detection. Request hashes bind canonical SDK arguments; reply hashes bind adapter-returned text, not raw HTTP/SSE bytes. Tool allowlists and separate HOME/state directories are not an OS/network sandbox.

## Paired outcome

The first attempt stopped at a synthetic judge-calibration TimeoutError before any real cases. One bounded fresh attempt used the same evaluator settings, passed calibration and attempted the fixed 24 cases. Its exit code was 1, not a successful full run.

- Both arms completed for 14 pairs. Ten pairs were incomplete: the 48 arm records contain 28 completed answers, 10 TimeoutError outcomes and 10 APIConnectionError outcomes.
- Of the 14 complete pairs, the judge returned 13 valid ties and one APIError. The full denominator is therefore **0 wins, 13 ties, 0 losses, 11 UNKNOWN**. Incomplete pairs were not sent to ordinary judging.
- A: 0 ties, 3 UNKNOWN; B: 5 ties, 3 UNKNOWN; C: 3 ties, 5 UNKNOWN; G: 5 ties, 0 UNKNOWN. No pair in A was graded. Generalizing the scored subset to all three repositories would be unwarranted.
- Eleven scored pairs received 2:2 and two received 1:1. These are one blind model judge's scores, not human-confirmed task outcomes.

At the actual case mix, baseline card characters summed to 513,905 and candidate characters to 427,494, a reduction of 16.81%. Recorded SDK attempts were 46 versus 41, and read-only tool calls 22 versus 17. These counts include failures and do not show that the candidate needs fewer calls in successful work.

Usage was missing for 10 calls in each answer arm and one judge call. Every full token total is therefore `null`; the companion JSON retains known subtotals for audit, not as comparable complete costs. Per-arm latency was not instrumented. No token-cost or latency improvement is claimed.

The parent recomputed the summary from all 48 arm records and 24 pair records, checked record/request/reply/answer hashes and the judge's exact case/reference/answer bindings, and rechecked frozen input hashes. Tracked repository sources were clean and their HEADs unchanged before and after the run. Thirty returned card-fact occurrences also matched their frozen full source text. Recorded request hosts were only `chatgpt.com`.

## Answers to the four questions

1. **Does trimming improve or worsen answers?** Among the 13 scored pairs, neither improvement nor worsening was observed: all tied. The 11 UNKNOWN cases, including every A case, prevent an absence-of-harm conclusion. Character savings alone do not justify a default change.
2. **Flag, confirmed dream proposal, or a new kind?** Zero production admission interfaces were compared. The 18 medium-confidence labels were conservatively retained rather than sent to user curation, but that does not establish which write-time or dream-time interface keeps the class small. No flag, kind or confirmation workflow is recommended for implementation from this pass; this design question remains open.
3. **Should agent-attributed repository decisions leave the card?** All 11 such decisions were removed as part of the larger candidate. With no separate ablation and 11 UNKNOWN pairs, this does not justify blanket removal. They remain a plausible targeted research subset, not a demonstrated product change.
4. **Does the existing hook already cover command/file facts?** Exact-ID coverage in the measured local integration is 0/11. Semantic substitutes remain unmeasured. The 3 file-labelled facts can inform #598; the 8 command-labelled facts cannot be assumed delivered by the current program integration. Another device's configuration was not verified.

## Recommendation and remaining work

Keep production selection, kinds and budgets unchanged. Do not silently drop command/file safeguards on the assumption that a hook will restore them. No implementation issue is created because this pass does not recommend changing the card.

#606 stays open for a lower-error matched comparison and an evidence-backed admission decision. Preserve this fixed sample and the failed attempts; do not report UNKNOWN as ties or rerun semantic outcomes until a preferred result appears. Any continuation should distinguish infrastructure recovery from changing the evaluator or the candidate. This does not settle the separate device-corpus requirements of #598 or #602.
