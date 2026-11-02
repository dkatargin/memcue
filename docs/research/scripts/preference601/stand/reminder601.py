"""The #601 candidate: the shipped SessionStart part 1 with one more line at the end of the memory note.

The candidate plugin pipes `memcue.sh session-start -part 1` through this filter: python3 -I reminder601.py. It reads
the line from reminder.md beside it and inserts it as the note's last bullet, right after the note's closing bullet,
so it reaches the model in the same first part, before any hint or card. Nothing else changes: parts 2 and 3 do not
pass through here. When the hook output is not the expected JSON, the note's end is not found exactly once, or the
longer part would reach the per-hook budget of memcue's layout, the output passes through unchanged. Every call
appends what it did to $STAND601_HOOK_LOG when that is set, so the stand can tell a delivered line from a missing one.
"""

import hashlib
import json
import os
import sys
from pathlib import Path

NOTE_END = "(memcue add / correct / retire)."
PART_BUDGET = 9500  # memcue's partBudget: a part this long is beyond what the stand checked


def insert(raw: str, reminder: str) -> tuple[str, dict]:
    try:
        doc = json.loads(raw)
        ctx = doc["hookSpecificOutput"]["additionalContext"]
    except (ValueError, KeyError, TypeError):
        return raw, {"inserted": False, "reason": "not a SessionStart hook output"}
    if not isinstance(ctx, str) or ctx.count(NOTE_END) != 1:
        return raw, {"inserted": False, "reason": "the note's end anchor is not there exactly once"}
    new = ctx.replace(NOTE_END, NOTE_END + "\n- " + reminder, 1)
    if len(new) >= PART_BUDGET:
        return raw, {"inserted": False, "reason": "the part would reach the per-hook budget", "chars": len(ctx)}
    doc["hookSpecificOutput"]["additionalContext"] = new
    return json.dumps(doc, ensure_ascii=False) + "\n", {
        "inserted": True, "chars": len(new), "sha256": hashlib.sha256(new.encode()).hexdigest()}


def main() -> int:
    reminder = Path(__file__).with_name("reminder.md").read_text(encoding="utf-8").strip()
    raw = sys.stdin.read()
    out, info = insert(raw, reminder)
    sys.stdout.write(out)
    log = os.environ.get("STAND601_HOOK_LOG")
    if log:
        with open(log, "a", encoding="utf-8") as f:
            f.write(json.dumps(info) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
