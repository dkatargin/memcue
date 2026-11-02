"""Search raw session history for the words of a memcue query, with no index (#602). A research script, not a command.

Run: python3 -I sessions.py --queries Q.jsonl (--hermes-db STATE.DB | --claude-dir PROJECTS) --arm NAME --out DIR
     [--k 5] [--half-window 200] [--include-tool-output]

Q.jsonl holds one query per line: {"qid", "query", "time" (ISO 8601 UTC or unix seconds), "exclude_sessions": [...]}.
The query time is a strict upper bound: a message at or after it is not history yet. A message without a time is
dropped. The sources:

- --hermes-db: a copy of Hermes state.db, opened read-only and immutable. User and assistant text; a user message of a
  cron or subagent session or of a delegated child is the prompt the program wrote, not the human, and is left out,
  as are process notices, cron deliveries, system notes, task notifications, the results of background delegations,
  the task-list carry-over and compaction summaries; a marker this list lacks lets machine text through (see the
  note). An out-of-band user message stays: it is the human's text in an envelope. Rewound rows
  (active=0, compacted=0) are left out; compacted rows stay, they are history that left the context.
- --claude-dir: a Claude Code projects directory. User and assistant text blocks; thinking, tool_use inputs and
  tool_result output are left out, as are compaction summaries, meta records (skill bodies), command echoes, task
  notifications, embedded system reminders, subagent (sidechain) briefs and the prompts of sdk-cli sessions, which a
  delegating agent wrote. A line above --max-line bytes is skipped and counted.

--include-tool-output adds tool output (Hermes tool rows, Claude tool_result text) as a separate arm for the cost of
context; it carries secrets and fetched pages, so its windows never leave the private output.

The query becomes its distinct lowercase words, stop words left out. A message matches when it holds at least
min_match(n) of the n words as substrings: 1 of 1, 2 of 2 to 4, half of 5 or more. Matches are taken newest first,
one window per message, top --k; a window repeating the text of a newer one is skipped and counted. The window is
2 x --half-window characters around the spot that holds the most distinct words.

The output directory must not exist; it is created 0700, its files 0600. results.jsonl holds the windows and is
private. stdout carries counts only.
"""

import argparse
import hashlib
import json
import math
import os
import re
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

STOP = set("""a an and are as at be by can do does for from has have how i if in into is it its me my no not of on or
our so that the their then there these this to was we what when where which who why will with you your
и в во не на что как к ко с со по о об от до за из для это этот эта эти то же ли или а но бы был была были есть
у мы вы я он она они его её их как где когда какой какая какие чем там тут уже ещё""".split())

TERM = re.compile(r"\w(?:[\w.\-]*\w)?", re.UNICODE)
WS = re.compile(r"\s+")
REMINDER = re.compile(r"<system-reminder>.*?</system-reminder>", re.S)
REPLYING = re.compile(r'^\[Replying to: ".*?"\]\s*', re.S)

HERMES_MACHINE = ("[IMPORTANT:", "[Cron delivery:", "[System note:", "[System:", "<task-notification>",
                  "[CONTEXT COMPACTION", "[CONTEXT SUMMARY]:", "[ASYNC DELEGATION", "[Your active task list was preserved")
# Markers a machine message can carry anywhere in its text, not only at the start.
HERMES_MACHINE_ANYWHERE = ("<task-notification>", "[INTERNAL NOTIFICATION")
CLAUDE_MACHINE = ("<command-name>", "<command-message>", "<command-args>", "<local-command-stdout>",
                  "<local-command-stderr>", "<local-command-caveat>", "<task-notification>", "<bash-input>",
                  "<bash-stdout>", "<bash-stderr>", "<user-prompt-submit-hook>", "Caveat: The messages below",
                  "This session is being continued from a previous conversation", "[Request interrupted",
                  "Base directory for this skill:")


class InputError(Exception):
    """An input the script cannot read as the source it claims to be."""


@dataclass
class Message:
    uid: str
    session: str
    role: str
    text: str
    ts: float
    source: str  # interactive, cron, subagent, delegated, sidechain


@dataclass
class Stats:
    lines: int = 0
    bad_lines: int = 0
    oversized: int = 0
    no_time: int = 0
    machine: int = 0
    tool_skipped: int = 0
    rewound: int = 0
    duplicates: int = 0
    kept: int = 0


def to_iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def parse_time(value) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(value) else None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        return None  # a time without a zone cannot be ordered against the query
    return dt.timestamp()


def terms(query: str) -> list[str]:
    out = []
    for t in TERM.findall(query.lower()):
        if len(t) >= 2 and t not in STOP and t not in out:
            out.append(t)
    return out


def min_match(n: int) -> int:
    return n if n <= 2 else 2 if n <= 4 else math.ceil(n / 2)


def norm(text: str) -> str:
    return WS.sub(" ", text).strip()


def window(text: str, words: list[str], half: int) -> str:
    """The passage of at most 2*half characters around the spot that holds the most distinct words."""
    if len(text) <= 2 * half:
        return text
    low = text.lower()
    best, best_pos = -1, 0
    for w in words:
        start = 0
        while (i := low.find(w, start)) != -1:
            lo, hi = max(0, i - half), i + half
            seen = sum(1 for v in words if v in low[lo:hi])
            if seen > best:
                best, best_pos = seen, i
            start = i + 1
    lo = max(0, best_pos - half)
    hi = min(len(text), lo + 2 * half)
    lo = max(0, hi - 2 * half)
    return ("…" if lo > 0 else "") + text[lo:hi] + ("…" if hi < len(text) else "")


def _machine_hermes(text: str) -> bool:
    return text.lstrip().startswith(HERMES_MACHINE) or any(m in text for m in HERMES_MACHINE_ANYWHERE)


def hermes_messages(db: Path, include_tool: bool, stats: Stats):
    uri = "file:" + str(Path(db).resolve()) + "?mode=ro&immutable=1"
    try:
        con = sqlite3.connect(uri, uri=True)
        cols = {r[1] for r in con.execute("PRAGMA table_info(messages)")}
        scols = {r[1] for r in con.execute("PRAGMA table_info(sessions)")}
    except sqlite3.Error as e:
        raise InputError(f"hermes db: {e}") from None
    need = {"id", "session_id", "role", "content", "timestamp", "active", "compacted"}
    if not need <= cols or not {"id", "source", "model_config", "parent_session_id"} <= scols:
        con.close()
        raise InputError("hermes db: messages or sessions lack the expected columns")
    try:
        rows = con.execute("""SELECT m.id, m.session_id, m.role, m.content, m.timestamp, m.active, m.compacted,
                                     s.source, s.model_config
                              FROM messages m JOIN sessions s ON s.id = m.session_id ORDER BY m.id""")
        for mid, sid, role, content, ts, active, compacted, source, model_config in rows:
            stats.lines += 1
            if role not in ("user", "assistant", "tool"):
                continue
            if active == 0 and compacted != 1:
                stats.rewound += 1
                continue
            if role == "tool" and not include_tool:
                stats.tool_skipped += 1
                continue
            text = content if isinstance(content, str) else ""
            if not text.strip():
                continue
            t = parse_time(ts)
            if t is None:
                stats.no_time += 1
                continue
            try:
                delegated = "_delegate_from" in json.loads(model_config or "{}")
            except (ValueError, TypeError):
                delegated = False
            cls = "cron" if source == "cron" else "subagent" if source == "subagent" else \
                "delegated" if delegated else "interactive"
            if role == "user":
                text = REPLYING.sub("", text)  # the quote of a reply goes first, so the body is what is judged
                if cls != "interactive" or _machine_hermes(text):
                    stats.machine += 1
                    continue
            elif role == "assistant" and _machine_hermes(text):
                stats.machine += 1
                continue
            stats.kept += 1
            yield Message(f"h:{mid}", sid, role, text, t, cls)
    except sqlite3.Error as e:
        raise InputError(f"hermes db: {e}") from None
    finally:
        con.close()


def hermes_lineage(db: Path, session: str) -> list[str]:
    """The session and its parents: their text is in the context or was summarised into it."""
    out, cur = [], session
    try:
        con = sqlite3.connect("file:" + str(Path(db).resolve()) + "?mode=ro&immutable=1", uri=True)
        try:
            while cur and cur not in out:
                out.append(cur)
                row = con.execute("SELECT parent_session_id FROM sessions WHERE id = ?", (cur,)).fetchone()
                cur = row[0] if row else None
        finally:
            con.close()
    except sqlite3.Error as e:
        raise InputError(f"hermes db lineage: {e}") from None
    return out


def _blocks(content, kind: str) -> list[str]:
    if isinstance(content, str):
        return [content] if kind == "text" else []
    out = []
    for b in content if isinstance(content, list) else []:
        if not isinstance(b, dict) or b.get("type") != kind:
            continue
        if kind == "text" and isinstance(b.get("text"), str):
            out.append(b["text"])
        elif kind == "tool_result":
            c = b.get("content")
            if isinstance(c, str):
                out.append(c)
            elif isinstance(c, list):
                out.extend(x["text"] for x in c if isinstance(x, dict) and isinstance(x.get("text"), str))
    return out


def claude_messages(root: Path, include_tool: bool, stats: Stats, max_line: int = 8 << 20):
    seen = set()
    files = sorted(Path(root).rglob("*.jsonl"))
    for path in files:
        entry = None
        with open(path, "rb") as f:
            for raw in f:
                stats.lines += 1
                if len(raw) > max_line:
                    stats.oversized += 1
                    continue
                try:
                    d = json.loads(raw)
                except ValueError:
                    stats.bad_lines += 1
                    continue
                if not isinstance(d, dict):
                    stats.bad_lines += 1
                    continue
                entry = d.get("entrypoint") or entry
                kind = d.get("type")
                if kind not in ("user", "assistant"):
                    continue
                m = d.get("message")
                content = m.get("content") if isinstance(m, dict) else None
                texts = _blocks(content, "text")
                tools = _blocks(content, "tool_result") if kind == "user" else []
                if tools and not include_tool:
                    stats.tool_skipped += len(tools)
                if not texts and not (tools and include_tool):
                    continue
                uid = str(d.get("uuid") or hashlib.sha256(raw).hexdigest())
                if uid in seen:
                    stats.duplicates += 1
                    continue
                seen.add(uid)
                t = parse_time(d.get("timestamp"))
                if t is None:
                    stats.no_time += 1
                    continue
                session = str(d.get("sessionId") or path.stem)
                side = bool(d.get("isSidechain"))
                cls = "sidechain" if side else "delegated" if entry == "sdk-cli" else "interactive"
                if include_tool:
                    for i, text in enumerate(tools):
                        if text.strip():
                            stats.kept += 1
                            yield Message(f"c:{uid}:t{i}", session, "tool", text, t, cls)
                if d.get("isCompactSummary") or d.get("isMeta") or d.get("isVisibleInTranscriptOnly"):
                    stats.machine += 1
                    continue
                text = REMINDER.sub("", "\n".join(texts)).strip()
                if not text:
                    continue
                if kind == "user" and (text.startswith(CLAUDE_MACHINE) or side or entry == "sdk-cli"):
                    stats.machine += 1
                    continue
                stats.kept += 1
                yield Message(f"c:{uid}", session, kind, text, t, cls)


def search(messages: list[Message], query: str, before: float, exclude: set, k: int, half: int) -> dict:
    words = terms(query)
    need = min_match(len(words)) if words else 0
    res = {"terms": words, "min_match": need, "candidates": 0, "future_rejected": 0, "excluded_session": 0,
           "duplicate_windows": 0, "windows": []}
    if not words:
        return res
    hits = []
    for m in messages:
        low = m.text.lower()
        got = sum(1 for w in words if w in low)
        if got < need:
            continue
        if m.ts >= before:
            res["future_rejected"] += 1
            continue
        if m.session in exclude:
            res["excluded_session"] += 1
            continue
        hits.append((m, got))
    res["candidates"] = len(hits)
    hits.sort(key=lambda h: (h[0].ts, h[0].uid), reverse=True)
    shown = set()
    for m, got in hits:
        if len(res["windows"]) >= k:
            break
        w = window(norm(m.text), words, half)
        key = hashlib.sha256(w.lower().encode()).hexdigest()
        if key in shown:
            res["duplicate_windows"] += 1
            continue
        shown.add(key)
        res["windows"].append({"rank": len(res["windows"]) + 1, "text": w, "chars": len(w),
                               "message_chars": len(m.text), "matched": got, "ts": to_iso(m.ts), "role": m.role,
                               "source": m.source, "session": m.session, "uid": m.uid})
    return res


def _inside(a: Path, b: Path) -> bool:
    return a == b or b in a.parents


def read_queries(path: Path) -> list[dict]:
    rows, seen = [], set()
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            q = json.loads(line)
        except ValueError:
            raise InputError(f"queries line {n}: not JSON") from None
        t = parse_time(q.get("time")) if isinstance(q, dict) else None
        if t is None or not isinstance(q.get("query"), str) or not isinstance(q.get("qid"), str) or not q["qid"]:
            raise InputError(f"queries line {n}: needs a string qid, a query and a finite time with a zone")
        if q["qid"] in seen:
            raise InputError(f"queries line {n}: repeated qid")
        seen.add(q["qid"])
        ex = q.get("exclude_sessions", [])
        if not isinstance(ex, list) or not all(isinstance(s, str) and s for s in ex):
            raise InputError(f"queries line {n}: exclude_sessions must be a list of session ids")
        rows.append({**q, "exclude_sessions": ex, "_ts": t})
    if not rows:
        raise InputError("queries: no query")
    return rows


def write_private(path: Path, text: str) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--queries", required=True, type=Path)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--hermes-db", type=Path)
    src.add_argument("--claude-dir", type=Path)
    ap.add_argument("--arm", required=True)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--half-window", type=int, default=200)
    ap.add_argument("--max-line", type=int, default=8 << 20)
    ap.add_argument("--include-tool-output", action="store_true")
    a = ap.parse_args(argv)
    source = a.hermes_db or a.claude_dir
    try:
        if not a.queries.is_file():
            raise InputError("queries file missing")
        if a.hermes_db and not a.hermes_db.is_file():
            raise InputError("hermes db missing")
        if a.claude_dir and not a.claude_dir.is_dir():
            raise InputError("claude dir missing")
        if a.k < 1 or a.half_window < 10:
            raise InputError("--k must be >= 1 and --half-window >= 10")
        out = a.out.resolve()
        for p in (a.queries.resolve(), source.resolve()):
            if _inside(out, p) or _inside(p, out):
                raise InputError("output overlaps an input")
        if out.exists():
            raise InputError("output exists; give a new directory")
        queries = read_queries(a.queries)
    except InputError as e:
        print(f"sessions.py: {e}", file=sys.stderr)
        return 2
    stats = Stats()
    excludes = []
    try:
        if a.hermes_db:
            msgs = list(hermes_messages(a.hermes_db, a.include_tool_output, stats))
        else:
            msgs = list(claude_messages(a.claude_dir, a.include_tool_output, stats, a.max_line))
        for q in queries:  # lineage is read before any output exists, so a broken copy leaves nothing behind
            exclude = set(q["exclude_sessions"])
            if a.hermes_db:
                for s in list(exclude):
                    exclude.update(hermes_lineage(a.hermes_db, s))
            excludes.append(exclude)
    except InputError as e:
        print(f"sessions.py: {e}", file=sys.stderr)
        return 2
    os.mkdir(out, 0o700)
    os.chmod(out, 0o700)
    lines, span = [], [min((m.ts for m in msgs), default=None), max((m.ts for m in msgs), default=None)]
    for q, exclude in zip(queries, excludes):
        r = search(msgs, q["query"], q["_ts"], exclude, a.k, a.half_window)
        lines.append(json.dumps({"qid": q["qid"], "arm": a.arm, "query_time": to_iso(q["_ts"]),
                                 "query_sha": hashlib.sha256(q["query"].encode()).hexdigest()[:16], **r},
                                ensure_ascii=False))
    write_private(out / "results.jsonl", "\n".join(lines) + "\n")
    manifest = {"arm": a.arm, "k": a.k, "half_window": a.half_window, "include_tool_output": a.include_tool_output,
                "source_kind": "hermes-db" if a.hermes_db else "claude-dir", "messages": len(msgs),
                "first": to_iso(span[0]) if span[0] else None, "last": to_iso(span[1]) if span[1] else None,
                "stats": stats.__dict__, "queries": len(queries)}
    write_private(out / "manifest.json", json.dumps(manifest, indent=1) + "\n")
    with_windows = sum(1 for line in lines if json.loads(line)["windows"])
    print(f"arm {a.arm}: {len(msgs)} messages, {len(queries)} queries, {with_windows} with a window; "
          f"stats {stats.__dict__}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
