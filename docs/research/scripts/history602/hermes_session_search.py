"""Run the Hermes session_search tool on a copy of state.db for each query of sessions.py (#602). Research only.

Run with the Hermes interpreter, HOME and HERMES_HOME pointing at an empty scratch directory:
  env -i PATH=/usr/bin:/bin HOME=SCRATCH HERMES_HOME=SCRATCH HERMES_PY hermes_session_search.py \
      --hermes-root HERMES --db COPY/state.db --queries Q.jsonl --out DIR [--limit 5] [--detail adaptive]

The call is the tool's own discovery shape: session_search(query, limit, db=SessionDB(COPY, read_only=True),
current_session_id=<the query's session>, before=<query time>). The tool is not changed. Its before bound is on the
start of a session, not on the time of a message, so this script applies a POSTFILTER to the answer: every message the
answer shows (matched message, window, bookends) must carry a finite timestamp before the query time, or it is
dropped and counted; a result whose matched message is not before the query is dropped whole. The real tool has no
such boundary; the filter exists only here, for the comparison.

Output, a new directory 0700 with files 0600: responses.jsonl, the tool's answer as it came; comparison.jsonl, the
filtered answer, bound to the query by its hash and time (status ok or error; an error is unknown, not a miss);
manifest.json, the hashes of the Hermes modules
run. The run exits 3 when any query's answer is an error or does not have the documented shape.
The copy's directory gets -wal and -shm files when the copy is opened; never point --db at a live base.
"""

import argparse
import hashlib
import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

MODULES = ("tools/session_search_tool.py", "hermes_state.py", "hermes_state_search.py", "hermes_state_messages.py")
SHOWN = ("messages", "bookend_start", "bookend_end")


def check(raw: str) -> tuple[dict | None, str | None]:
    """The tool's answer when it is a successful discovery answer of the documented shape, else the reason."""
    try:
        doc = json.loads(raw)
    except (TypeError, ValueError):
        return None, "not JSON"
    if not isinstance(doc, dict) or doc.get("success") is not True:
        return None, "no success"
    results = doc.get("results")
    if not isinstance(results, list) or not isinstance(doc.get("count"), int) or doc["count"] != len(results):
        return None, "results and count disagree"
    for r in results:
        if not isinstance(r, dict) or not all(isinstance(r.get(k, []), list) for k in SHOWN):
            return None, "a result of another shape"
    return doc, None


def _ts(m) -> float | None:
    t = m.get("timestamp") if isinstance(m, dict) else None
    if isinstance(t, bool) or not isinstance(t, (int, float)) or not math.isfinite(t):
        return None
    return float(t)


def postfilter(doc: dict, before: float) -> dict:
    """Keep only what was written before the query; count what was dropped."""
    out, total = [], 0
    for rank, r in enumerate(doc["results"], 1):
        anchor = r.get("match_message_id")
        shown = [m for k in SHOWN for m in r.get(k) or []]
        anchor_ts = next((_ts(m) for m in shown if isinstance(m, dict) and m.get("id") == anchor), None)
        entry = {"rank": rank, "anchor": anchor, "session": r.get("session_id"), "source": r.get("source"),
                 "anchor_after_query": anchor_ts is None or anchor_ts >= before, "kept": [],
                 "dropped_after_query": 0, "dropped_no_time": 0}
        seen = set()
        for m in shown:
            t = _ts(m)
            if t is None:
                entry["dropped_no_time"] += 1
            elif t >= before:
                entry["dropped_after_query"] += 1
            elif not entry["anchor_after_query"] and m.get("id") not in seen:
                seen.add(m.get("id"))
                text = m.get("content") if isinstance(m.get("content"), str) else ""
                calls = json.dumps(m["tool_calls"], ensure_ascii=False) if m.get("tool_calls") else ""
                entry["kept"].append({"id": m.get("id"), "role": m.get("role"), "timestamp": t, "content": text,
                                      "tool_calls": calls, "truncated": bool(m.get("content_truncated"))})
        entry["visible_chars"] = sum(len(m["content"]) + len(m["tool_calls"]) for m in entry["kept"])
        total += entry["visible_chars"]
        out.append(entry)
    return {"results": out, "visible_chars": total}


def write_private(path: Path, text: str) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hermes-root", required=True, type=Path)
    ap.add_argument("--db", required=True, type=Path)
    ap.add_argument("--queries", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--limit", type=int, default=5)
    ap.add_argument("--detail", default="adaptive")
    a = ap.parse_args()
    for p in (a.hermes_root, a.db, a.queries):
        if not p.exists():
            print(f"missing input: {p.name}", file=sys.stderr)
            return 2
    out = a.out.resolve()
    if out.exists() or a.db.resolve().parent in (out, *out.parents):
        print("output exists or overlaps the copy", file=sys.stderr)
        return 2
    queries = [json.loads(line) for line in a.queries.read_text(encoding="utf-8").splitlines() if line.strip()]
    qids = [q.get("qid") for q in queries]
    if len(set(qids)) != len(qids) or not all(isinstance(q.get("time"), (int, float)) and math.isfinite(q["time"])
                                             and isinstance(q.get("exclude_sessions"), list) and q["exclude_sessions"]
                                             for q in queries):
        print("queries: repeated qid, a time that is not a finite number, or no session", file=sys.stderr)
        return 2
    modules = {m: hashlib.sha256((a.hermes_root / m).read_bytes()).hexdigest()
               for m in MODULES if (a.hermes_root / m).is_file()}
    sys.path.insert(0, str(a.hermes_root))
    from hermes_state import SessionDB  # noqa: E402
    from tools.session_search_tool import session_search  # noqa: E402

    db = SessionDB(db_path=a.db, read_only=True)
    raws, rows = [], []
    try:
        for q in queries:
            ts = float(q["time"])
            before = datetime.fromtimestamp(ts, timezone.utc).isoformat()
            try:
                raw = session_search(query=q["query"], limit=a.limit, db=db, current_session_id=q["exclude_sessions"][0],
                                     before=before, detail=a.detail)
            except Exception as e:  # the tool failing is an unknown answer, recorded as such
                raw = json.dumps({"success": False, "error": f"raised {type(e).__name__}"})
            raws.append({"qid": q["qid"], "raw": raw})
            bind = {"qid": q["qid"], "query_sha": hashlib.sha256(q["query"].encode()).hexdigest()[:16],
                    "query_time": datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")}
            doc, err = check(raw)
            if doc is None:
                rows.append({**bind, "status": "error", "error": err, "results": [], "visible_chars": 0})
                continue
            rows.append({**bind, "status": "ok", "count": doc["count"], "response_chars": len(raw),
                         **postfilter(doc, ts)})
    finally:
        db.close()
    os.mkdir(out, 0o700)
    os.chmod(out, 0o700)
    write_private(out / "responses.jsonl", "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in raws))
    write_private(out / "comparison.jsonl", "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    write_private(out / "manifest.json", json.dumps({"modules": modules, "limit": a.limit, "detail": a.detail,
                                                     "postfilter": "every shown message before the query time"},
                                                    indent=1) + "\n")
    errors = sum(1 for r in rows if r["status"] != "ok")
    kept = sum(1 for r in rows if any(x["kept"] for x in r["results"]))
    print(f"{len(rows)} queries, {errors} errors, {kept} with a message kept before the query")
    return 3 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
