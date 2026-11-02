"""Aggregate the #602 measurement from saved results: counts by arm and stratum, no text, no identifiers.

Run: python3 -I aggregate.py --queries Q.jsonl --run ARM=DIR [--run ARM=DIR ...] [--session-search COMPARISON.jsonl]
     [--labels L.jsonl] [--answer-arm ARM]

Every input is checked before anything is counted, and the run fails (exit 2) on a broken or repeated record: a query
file with a repeated qid; a results file that does not hold each query once, whose arm, query hash or query time
differs from the query, whose windows are not ranked 1..n, repeat a message, misstate their length or fall at or after
the query time; a label file with a repeated id or an unknown value; a comparison file of session_search that does not
hold each query once.

A label counts only when it binds: its id is the hash of query id, message and window text recomputed from the
results, and its seen_sha is the hash of that exact text as the reader saw it. Any other window is UNKNOWN, and so is
a label that binds to no window of the results given (it is reported as stale, never counted). Labels: A answers,
R related, N noise; outdated: newer, fact, none.

session_search is read from the comparison file of hermes_session_search.py, after its postfilter. The file must
carry each query's hash and time, every kept message must be written before the query time, and its character counts
must be non-negative integers that add up to the kept messages; otherwise the run fails rather than counting the row as
empty. An error there is UNKNOWN, not a miss. For each A window of --answer-arm, the run
checks whether the same text is visible in session_search's kept messages of the same query and message.
The cost table lists characters per query over the same queries for both; the units differ (parser windows against
whole shown messages), so it describes, it does not rank.
"""

import argparse
import hashlib
import json
import math
import statistics
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


class Bad(Exception):
    """A record the aggregate refuses to count."""


def jsonl(path: Path) -> list[dict]:
    rows = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if line.strip():
            try:
                row = json.loads(line)
            except ValueError:
                raise Bad(f"{path.name} line {n}: not JSON") from None
            if not isinstance(row, dict):
                raise Bad(f"{path.name} line {n}: not an object")
            rows.append(row)
    return rows


def sha(text: str, n: int) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:n]


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def when(value: str) -> float:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def med(xs):
    return statistics.median(xs) if xs else 0


def unique(rows: list[dict], key: str, what: str) -> dict:
    out = {}
    for r in rows:
        k = r.get(key)
        if not isinstance(k, str) or not k or k in out:
            raise Bad(f"{what}: missing or repeated {key}")
        out[k] = r
    return out


def load_queries(path: Path) -> dict:
    qs = unique(jsonl(path), "qid", "queries")
    for q in qs.values():
        if not isinstance(q.get("query"), str) or not isinstance(q.get("stratum"), str) or \
                isinstance(q.get("time"), bool) or not isinstance(q.get("time"), (int, float)) or \
                not math.isfinite(q["time"]):
            raise Bad("queries: a row lacks query, stratum or a finite numeric time")
        try:
            iso(q["time"])
        except (OverflowError, OSError, ValueError):
            raise Bad("queries: a time out of range") from None
    return qs


def load_run(arm: str, path: Path, queries: dict) -> dict:
    rows = unique(jsonl(path / "results.jsonl"), "qid", f"run {arm}")
    if set(rows) != set(queries):
        raise Bad(f"run {arm}: results do not hold each query once")
    for qid, r in rows.items():
        q = queries[qid]
        if r.get("arm") != arm or r.get("query_sha") != sha(q["query"], 16) or r.get("query_time") != iso(q["time"]):
            raise Bad(f"run {arm}: a result is not bound to its query")
        wins = r.get("windows")
        if not isinstance(wins, list):
            raise Bad(f"run {arm}: windows is not a list")
        if [w.get("rank") for w in wins] != list(range(1, len(wins) + 1)):
            raise Bad(f"run {arm}: windows are not ranked 1..n")
        if len({w.get("uid") for w in wins}) != len(wins):
            raise Bad(f"run {arm}: a message has two windows")
        for w in wins:
            if not isinstance(w.get("text"), str) or w.get("chars") != len(w["text"]) or not isinstance(w.get("uid"), str):
                raise Bad(f"run {arm}: a window misstates its text")
            try:
                late = when(w["ts"]) >= q["time"]
            except (KeyError, TypeError, ValueError):
                raise Bad(f"run {arm}: a window without a time") from None
            if late:
                raise Bad(f"run {arm}: a window at or after the query time")
            w["_iid"] = sha(f"{qid}\x00{w['uid']}\x00{w['text']}", 12)
            w["_seen"] = sha("  " + w["text"], 16)
    return rows


def load_labels(path: Path) -> dict:
    labels = unique(jsonl(path), "iid", "labels")
    for lab in labels.values():
        if lab.get("label") not in ("A", "R", "N") or lab.get("outdated") not in ("none", "newer", "fact") or \
                not isinstance(lab.get("seen_sha"), str):
            raise Bad("labels: a row with an unknown value")
    return labels


def count(value) -> bool:
    """A character or result count: a non-negative int, never a bool, a string or a float."""
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def load_comparison(path: Path, queries: dict) -> dict:
    """The comparison must be of these queries (hash and time), hold only messages written before each query, and
    state character counts that add up to the messages it kept."""
    rows = unique(jsonl(path), "qid", "session_search")
    if set(rows) != set(queries):
        raise Bad("session_search: the comparison does not hold each query once")
    for qid, r in rows.items():
        q = queries[qid]
        if r.get("query_sha") != sha(q["query"], 16) or r.get("query_time") != iso(q["time"]):
            raise Bad("session_search: a row is not bound to its query")
        if r.get("status") not in ("ok", "error") or not isinstance(r.get("results"), list):
            raise Bad("session_search: a row of another shape")
        if r["status"] == "error":
            if r["results"] or r.get("visible_chars") != 0 or not count(r.get("visible_chars")):
                raise Bad("session_search: an error row carries results")
            continue
        if not count(r.get("count")) or r["count"] != len(r["results"]) or not count(r.get("response_chars")):
            raise Bad("session_search: invalid counts or declared count differs from results")
        total = 0
        for x in r["results"]:
            if not isinstance(x, dict) or not isinstance(x.get("kept"), list) or not count(x.get("visible_chars")):
                raise Bad("session_search: a result of another shape")
            chars = 0
            for m in x["kept"]:
                t = m.get("timestamp") if isinstance(m, dict) else None
                if isinstance(t, bool) or not isinstance(t, (int, float)) or not math.isfinite(t) or t >= q["time"]:
                    raise Bad("session_search: a kept message is not written before the query")
                if not isinstance(m.get("content"), str) or not isinstance(m.get("tool_calls"), str):
                    raise Bad("session_search: a kept message of another shape")
                chars += len(m["content"]) + len(m["tool_calls"])
            if x["visible_chars"] != chars:
                raise Bad("session_search: a result misstates its characters")
            total += chars
        if not count(r.get("visible_chars")) or r["visible_chars"] != total:
            raise Bad("session_search: a row misstates its characters")
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--queries", required=True, type=Path)
    ap.add_argument("--run", action="append", default=[])
    ap.add_argument("--session-search", type=Path)
    ap.add_argument("--labels", type=Path)
    ap.add_argument("--answer-arm", default="hermes-text")
    a = ap.parse_args()
    try:
        queries = load_queries(a.queries)
        runs = {}
        for spec in a.run:
            arm, _, path = spec.partition("=")
            if not path or arm in runs:
                raise Bad("--run takes ARM=DIR, each arm once")
            runs[arm] = load_run(arm, Path(path), queries)
        labels = load_labels(a.labels) if a.labels else {}
        ss = load_comparison(a.session_search, queries) if a.session_search else None
    except (Bad, OSError) as e:
        print(f"aggregate.py: {e}", file=sys.stderr)
        return 2
    strata = sorted({q["stratum"] for q in queries.values()})
    print(f"queries: {len(queries)}; by stratum " + ", ".join(
        f"{s} {sum(1 for q in queries.values() if q['stratum'] == s)}" for s in strata))

    bound = set()
    print("\n| arm | stratum | queries | with a window | windows A/R/N (bound) | windows UNKNOWN | "
          "queries with a bound answer | queries with no bound answer but an UNKNOWN window | bound answers outdated | "
          "median chars per window |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for arm, rows in runs.items():
        for s in strata:
            rs = [rows[q] for q in queries if queries[q]["stratum"] == s]
            c, unknown, answered, maybe, outdated = Counter(), 0, 0, 0, 0
            for r in rs:
                got = unk = False
                for w in r["windows"]:
                    lab = labels.get(w["_iid"])
                    if lab is None or lab["seen_sha"] != w["_seen"]:
                        unknown += 1
                        unk = True
                        continue
                    bound.add(w["_iid"])
                    c[lab["label"]] += 1
                    if lab["label"] == "A":
                        got = True
                        outdated += lab["outdated"] != "none"
                answered += got
                maybe += unk and not got
            wins = [w for r in rs for w in r["windows"]]
            print(f"| {arm} | {s} | {len(rs)} | {sum(1 for r in rs if r['windows'])} | {c['A']}/{c['R']}/{c['N']} | "
                  f"{unknown} | {answered} | {maybe} | {outdated} | {med([w['chars'] for w in wins])} |")
    if labels:
        print(f"\nlabels given {len(labels)}, bound to a window of these runs {len(bound)}, "
              f"stale (bound to nothing here, not counted) {len(set(labels) - bound)}")

    if ss is not None:
        print("\n| session_search after the postfilter | queries | ok | error (UNKNOWN) | ok with a kept message | "
              "results with the matched message at or after the query | messages dropped at or after the query | "
              "messages dropped without a time |")
        print("|---|---|---|---|---|---|---|---|")
        for s in strata:
            rs = [ss[q] for q in queries if queries[q]["stratum"] == s]
            ok = [r for r in rs if r["status"] == "ok"]
            print(f"| {s} | {len(rs)} | {len(ok)} | {len(rs) - len(ok)} | "
                  f"{sum(1 for r in ok if any(x.get('kept') for x in r['results']))} | "
                  f"{sum(1 for r in ok for x in r['results'] if x.get('anchor_after_query'))} | "
                  f"{sum(x.get('dropped_after_query', 0) for r in ok for x in r['results'])} | "
                  f"{sum(x.get('dropped_no_time', 0) for r in ok for x in r['results'])} |")
        arm = runs.get(a.answer_arm)
        if arm is not None:
            print(f"\n| stratum | bound A windows of {a.answer_arm} | same text visible in session_search | "
                  f"message shown but text cut or absent | message not shown | session_search UNKNOWN |")
            print("|---|---|---|---|---|---|")
            for s in strata:
                n = vis = cut = miss = unk = 0
                for q in queries:
                    if queries[q]["stratum"] != s:
                        continue
                    for w in arm[q]["windows"]:
                        lab = labels.get(w["_iid"])
                        if lab is None or lab["seen_sha"] != w["_seen"] or lab["label"] != "A":
                            continue
                        n += 1
                        if ss[q]["status"] != "ok":
                            unk += 1
                            continue
                        mid = int(w["uid"][2:]) if w["uid"].startswith("h:") and w["uid"][2:].isdigit() else None
                        shown = [m for x in ss[q]["results"] for m in x.get("kept", []) if m.get("id") == mid]
                        core = " ".join(w["text"].strip("…").split())
                        if any(core in " ".join(m.get("content", "").split()) for m in shown):
                            vis += 1
                        elif shown:
                            cut += 1
                        else:
                            miss += 1
                print(f"| {s} | {n} | {vis} | {cut} | {miss} | {unk} |")
        print("\n| stratum | queries paired (session_search ok) | parser chars per query, median | "
              "session_search chars per query after the postfilter, median |")
        print("|---|---|---|---|")
        for s in strata:
            qs = [q for q in queries if queries[q]["stratum"] == s and ss[q]["status"] == "ok"]
            parser = [sum(w["chars"] for w in arm[q]["windows"]) for q in qs] if arm is not None else []
            print(f"| {s} | {len(qs)} | {med(parser)} | {med([ss[q]['visible_chars'] for q in qs])} |")
    return 0


if __name__ == "__main__":
    sys.exit(main())
