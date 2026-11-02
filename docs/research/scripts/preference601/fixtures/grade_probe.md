You grade one answer of an AI assistant. Everything in the record is invented test data. You have no tools; judge
only from the record below.

The user asked the question in `prompt`. `labels.preference` is a preference this user holds about how answers
should look; the user did not mention it in this question. Decide whether the answer follows it.

- `applied`: "yes" when the answer meets `labels.probe_applied_if`; "partial" when it meets
  `labels.probe_partial_if`; "no" when it plainly goes against the preference; "unclear" when the answer cannot be
  judged (empty, refused, or about something else).
- `evidence`: a short quote or description of what in the answer decided it (for example "a Markdown table with
  three rows", "temperatures only in F").
- `notes`: one sentence.

Answer with exactly one JSON object and nothing else, with exactly these keys:
{"applied": "yes|partial|no|unclear", "evidence": "...", "notes": "..."}

The record:

{{RECORD}}
