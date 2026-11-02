"""Replay fixed historical requests offline with the delivered session card and a trimmed one, then judge each pair
blind (#606). Experiment only, not part of memcue; read-only towards every input. Run with the Hermes interpreter:

    /opt/hermes/.venv/bin/python -I replay606.py --cases CASES.json --cards CARDS.json --labels LABEL_DIR \\
        --facts FACTS_COPY --binary MEMCUE --repo A=PATH --repo B=PATH --repo C=PATH --host HOST --out NEW_DIR

The candidate card is a subset of the delivered parts, not a new render: a fact line goes only when its label is a
high-confidence channel other than behaviour and unknown, unless the fact is a repo-scoped rule or decision the user
stated. Notes before the card header, headings and the overflow hint stay as they are, so the hint may count facts
the subset does not show and the pool, delivery and truncation are the original ones. Every case runs both arms, in
an order drawn from seed 606, with one system message (offline policy plus the actual parts, joined by a blank line)
and two read-only tools; a judge then sees the two complete answers and their tool outputs as first and second, in an
order drawn from seed 607, with the baseline card as the same reference for both. The judge is calibrated first on
invented pairs and a wrong verdict stops the run before any real case is sent. Answers and verdicts are one model's,
not a task success measure and not a human check.

Everything is checked before anything is written or sent: schemas, unique IDs, credential-shaped strings (named by
pattern only), the label run (hash bindings, coverage, completion, calibration) and the containment of NEW_DIR. NEW_DIR
(0700, files 0600) holds the fact store copy the binary reads, cards.json, runs.jsonl, judge.jsonl and summary.json;
stdout gets the anonymous counts. Exit 0 when every pair is complete and judged, 1 when one is not, 2 for refused
input, 3 for a failed judge calibration.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import re
import shutil
import stat
import statistics
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from label606 import (CALIBRATION, CHANNELS, FIELDS, LABEL_FIELDS, MODEL, REQUEST_EXTRA, SECRETS,  # noqa: E402
                      SHOWN, InputError, Out, ReplyError, TransportError, canon, open_client, parse_labels, sha,
                      strict_object)

HEADER = "memcue: rules and decisions from the base"
HINT_TAIL = " more do not fit the card budget: search -in global -kind rule,decision"
STATED = ("user", "user_confirmed")
CASE_FIELDS = {"case_id", "context", "prompt", "history", "timestamp", "source_message", "source_session",
               "source_sha256"}
ARM_SEED, JUDGE_SEED, WORKERS, MAX_TURNS, MAX_TOOLS, FILE_CHARS = 606, 607, 2, 5, 12, 6000
SEARCH_TIMEOUT = 60
NO_REPO = "error: this session has no repository; read_repository_file is not available"
BLOCKED = re.compile(r"(?i)^\.env|\.(pem|key|p12|pfx|keystore|kdbx)$|^id_[a-z0-9]+$|credential|secret|token|"
                     r"^\.(netrc|npmrc|pypirc|pgpass)$")
POLICY = """You are a coding assistant answering one request of a past session again, offline. This is a \
counterfactual: the memory card below is a current card, frozen for this replay, not the context that session had, \
and nothing here reconstructs the past state of the session. Nothing you say is executed: you cannot run commands \
or tests, write or edit files, commit, push or deploy, and you must never claim you did. Answer with advice or a \
plan of what to do and why. Two read-only tools may help: memory_search looks up the user's saved facts, \
read_repository_file reads a tracked file of the session's repository; say you looked something up or read a file \
only when a tool output above shows it. The request was made at {timestamp}. The frozen memory card follows."""
JUDGE = """You compare two answers to the same request of a past session, given offline: neither assistant could \
execute anything, so an answer that claims it ran commands or tests, wrote or edited files, committed, pushed or \
deployed claims what did not happen. Each could read saved facts and tracked repository files with read-only tools; \
a claim to have looked something up or read a file holds only when that answer's tool outputs show it. Judge \
which answer serves the user better, given the conversation, the request and the reference facts (saved facts of \
the user; they may be outdated or wrong). Each answer comes with the outputs of the tools it used. Do not prefer the \
longer answer and do not count shared words as correctness. When the answers are equally good or you cannot tell, \
say tie or unknown. Score each answer 0 (wrong or harmful), 1 (partly useful) or 2 (good); the winner must have the \
higher score, a tie equal scores. Answer with strict JSON only: {"winner": "first|second|tie|unknown", \
"first_score": 0, "second_score": 0, "confidence": "high|medium|low", "reason": "at most 300 characters"}"""
JUDGE_CALIBRATION = [  # invented pairs with the verdicts a sound judge may give; not results of any real case
    {"prompt": "How do I bring the changes of main into my feature branch? Others push to main.", "history": [],
     "reference": "- Never rebase or force-push the shared branch main; merge it into feature branches.",
     "first": "Rebase main onto your feature branch and force-push main.",
     "second": "Merge main into your feature branch; do not rebase or force-push main, others push to it.",
     "expect": ["second"]},
    {"prompt": "Set the version in package.json to 2.0.0.", "history": [], "reference": "",
     "first": "I cannot change files here. Plan: set \"version\" to \"2.0.0\" in package.json, run the tests, commit.",
     "second": "Done: I set the version to 2.0.0, ran the tests and pushed the commit.", "expect": ["first"]},
    {"prompt": "Tabs or spaces for indenting a short Python script?", "history": [], "reference": "",
     "first": "Spaces: PEP 8 asks for four spaces per indentation level.",
     "second": "Use four spaces per indentation level, as PEP 8 recommends.", "expect": ["tie", "unknown"]},
]
TOOLS = [
    {"type": "function", "function": {"name": "memory_search", "description": "Search the user's saved facts.",
     "parameters": {"type": "object", "additionalProperties": False, "required": ["query", "in"], "properties": {
         "query": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 5},
         "in": {"type": "string", "enum": ["all", "global", "project"]}}}}},
    {"type": "function", "function": {"name": "read_repository_file",
     "description": "Read a tracked text file of the session's repository by its relative path.",
     "parameters": {"type": "object", "additionalProperties": False, "required": ["path"],
                    "properties": {"path": {"type": "string"}}}}},
]
PUT = threading.Lock()


def strings(x):
    if isinstance(x, str):
        yield x
    elif isinstance(x, dict):
        for k, v in x.items():
            yield from strings(k)
            yield from strings(v)
    elif isinstance(x, list):
        for v in x:
            yield from strings(v)


def secret(x) -> str | None:
    return next((name for name, pat in SECRETS.items() for s in strings(x) if re.search(pat, s)), None)


def read_json(path, loads=True):
    try:
        if stat.S_ISLNK(os.lstat(path).st_mode):
            raise InputError(f"{Path(path).name} is a symlink")
        with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), "rb") as f:
            if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
                raise InputError(f"{Path(path).name} is not a regular file")
            raw = f.read().decode()
        return json.loads(raw, object_pairs_hook=strict_object) if loads else \
            [json.loads(x, object_pairs_hook=strict_object) for x in raw.splitlines()]
    except (OSError, ValueError) as e:
        raise InputError(f"{Path(path).name}: {e}") from None


def check_cases(cases) -> None:
    if not isinstance(cases, list) or not cases:
        raise InputError("cases must be a non-empty list")
    seen = set()
    for i, c in enumerate(cases):
        if not isinstance(c, dict) or set(c) != CASE_FIELDS or c["context"] not in ("A", "B", "C", "G"):
            raise InputError(f"case {i}: fields or context")
        if not all(isinstance(c[k], str) for k in CASE_FIELDS - {"history", "timestamp"}) or not c["prompt"].strip():
            raise InputError(f"case {i}: string fields")
        if not isinstance(c["history"], list) or not all(
                isinstance(h, dict) and set(h) == {"role", "content"} and h["role"] in ("user", "assistant")
                and isinstance(h["content"], str) for h in c["history"]):
            raise InputError(f"case {i}: history")
        if not c["case_id"] or c["case_id"] in seen:
            raise InputError(f"case {i}: a duplicate or empty case_id")
        try:
            iso_utc(c["timestamp"])
        except (TypeError, ValueError, OverflowError, OSError):
            raise InputError(f"case {i}: timestamp is neither a UNIX time nor a zoned ISO 8601 time") from None
        if c["source_sha256"] != sha(canon({k: v for k, v in c.items() if k not in ("case_id", "source_sha256")})):
            raise InputError(f"case {i}: source_sha256 does not match the case")
        if name := secret(c):
            raise InputError(f"case {i}: credential-shaped string ({name}); nothing was sent")
        seen.add(c["case_id"])


def iso_utc(ts) -> str:
    """A UNIX time (finite, 0 to year 9999) or a zoned ISO 8601 time as ISO 8601 in UTC."""
    if type(ts) in (int, float) and math.isfinite(ts) and 0 <= ts <= 253402300799:
        return datetime.fromtimestamp(ts, timezone.utc).isoformat()
    dt = datetime.fromisoformat(ts) if isinstance(ts, str) else None
    if dt is None or dt.utcoffset() is None:
        raise ValueError("timestamp")
    return dt.astimezone(timezone.utc).isoformat()


GO_SPACE = re.compile("[\t\n\v\f\r \x85\xa0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+")  # unicode.IsSpace


def clip(s: str, n: int = 400) -> str:
    """session.go clip: the words of s joined by one space, cut to n runes with an ellipsis."""
    s = " ".join(w for w in GO_SPACE.split(s) if w)
    return s[:n] + "…" if len(s) > n else s


def card_lines(part: str) -> list[int]:
    """Indexes of the fact lines of one part: bullets after the card header, without the overflow hint."""
    lines = part.split("\n")
    at = next((i for i, x in enumerate(lines) if x.startswith(HEADER)), None)
    return [] if at is None else [i for i in range(at + 1, len(lines))
                                  if lines[i].startswith("- ") and not lines[i].endswith(HINT_TAIL)]


def trim(parts: list[str], facts: list[dict], keep: set[str]) -> list[str]:
    """The parts without the lines of the facts not kept; everything else byte for byte."""
    out, k = [], 0
    for p in parts:
        lines, drop = p.split("\n"), set()
        for i in card_lines(p):
            if k >= len(facts) or lines[i] != facts[k]["line"]:
                raise InputError("card lines do not match the facts")
            if facts[k]["id"] not in keep:
                drop.add(i)
            k += 1
        out.append("\n".join(x for i, x in enumerate(lines) if i not in drop))
    if k != len(facts):
        raise InputError("card lines do not match the facts")
    return out


def keeps(meta: dict, label: dict) -> bool:
    if label["channel"] in ("behaviour", "unknown") or label["confidence"] != "high":
        return True
    return (meta["scope"].lower().startswith("repo:") and meta["kind"] in ("rule", "decision")
            and meta["source"] in STATED)


def bound(q, a, rows: list[dict]) -> dict[str, dict]:
    """The labels of one saved batch, once its request carries exactly these rows and its reply is finished."""
    if q is None or a is None or a["error"] or not isinstance(a["content"], str) or a["finish_reason"] != "stop" \
            or a["response_sha256"] != sha(a["content"]):
        raise ReplyError("reply")
    facts = json.loads(q["request"]["messages"][1]["content"])["facts"]
    if q["ids"] != [r["id"] for r in rows] or facts != [{k: r[k] for k in SHOWN} for r in rows] or \
            q["source_sha256"] != [sha(canon(r)) for r in rows]:
        raise ReplyError("request")
    return parse_labels(a["content"], q["ids"])


def load_labels(d) -> dict[str, dict]:
    """The labels of a finished label606 run, each checked against its source row, request and reply."""
    d = Path(os.path.realpath(d))
    srcs, reqs, resps, labs = (read_json(d / f"{n}.jsonl", loads=False)
                               for n in ("sources", "requests", "responses", "labels"))
    (summary,) = read_json(d / "summary.json", loads=False)
    rows = {s["id"]: s for s in srcs}
    if len(rows) != len(srcs) or any(sha(canon(s["row"])) != s["source_sha256"] or s["row"]["id"] != i
                                     for i, s in rows.items()):
        raise InputError("labels: sources do not match their hashes")
    if (summary.get("calibration") != "passed" or summary.get("failed_batches") != 0
            or summary.get("error_rows", 0) or summary.get("unprocessed", 0)
            or not summary.get("rows") == summary.get("labelled") == len(rows) == len(labs)):
        raise InputError("labels: the run is incomplete or failed calibration")
    req, resp = {r["batch"]: r for r in reqs}, {r["batch"]: r for r in resps}
    if len(req) != len(reqs) or len(resp) != len(resps):
        raise InputError("labels: repeated batch")
    cal_rows = [{k: r[k] for k in FIELDS} for r in CALIBRATION]
    try:
        cal = bound(req.get("calibration"), resp.get("calibration"), cal_rows)
        cal_recs = read_json(d / "calibration.jsonl", loads=False)
        if len(cal_recs) != len(CALIBRATION) or any(
                cal[r["id"]]["channel"] != r["expect"] or c["expect"] != r["expect"] or c["id"] != r["id"]
                or c["batch"] != "calibration" or c["status"] != "ok" or c["source_sha256"] != sha(canon(row))
                or c["request_sha256"] != sha(canon(req["calibration"]["request"]))
                or c["response_sha256"] != resp["calibration"]["response_sha256"]
                or any(c[k] != cal[r["id"]][k] for k in LABEL_FIELDS - {"id"})
                for c, r, row in zip(cal_recs, CALIBRATION, cal_rows)):
            raise ReplyError("calibration records")
    except (ReplyError, KeyError, TypeError, ValueError, AttributeError) as e:
        raise InputError(f"labels: the saved calibration did not pass ({e})") from None
    out, parsed = {}, {}
    for lab in labs:
        q, a, s = req.get(lab["batch"]), resp.get(lab["batch"]), rows.get(lab["id"])
        try:
            if q is None or a is None or s is None or lab["id"] in out or lab["status"] != "ok" or a["error"]:
                raise ReplyError("missing or failed")
            if (lab["source_sha256"] != s["source_sha256"] or lab["request_sha256"] != sha(canon(q["request"]))
                    or lab["response_sha256"] != a["response_sha256"]):
                raise ReplyError("hash")
            if lab["batch"] not in parsed:
                parsed[lab["batch"]] = bound(q, a, [rows[i]["row"] for i in q["ids"]])
            if any(lab[k] != parsed[lab["batch"]][lab["id"]][k] for k in LABEL_FIELDS - {"id"}) or \
                    lab["channel"] not in CHANNELS:
                raise ReplyError("label")
        except (ReplyError, KeyError, TypeError, ValueError) as e:
            raise InputError(f"labels: a label is not bound to its source, request and reply ({e})") from None
        out[lab["id"]] = {**lab, "row": s["row"]}
    return out


def plan_cards(cards, labels) -> dict[str, dict]:
    if not isinstance(cards, dict) or not set(cards) <= {"A", "B", "C", "G"}:
        raise InputError("cards: contexts")
    plan = {}
    for ctx, c in cards.items():
        if not isinstance(c, dict) or set(c) != {"parts", "facts"} or not isinstance(c["parts"], list) or \
                not isinstance(c["facts"], list) or not all(isinstance(p, str) for p in c["parts"]):
            raise InputError(f"cards {ctx}: fields")
        if name := secret(c):
            raise InputError(f"cards {ctx}: credential-shaped string ({name}); nothing was sent")
        keep, ids = set(), []
        for f in c["facts"]:
            if not isinstance(f, dict) or set(f) != {"id", "line", "metadata"} or f["id"] in ids or \
                    not isinstance(f["metadata"], dict) or set(f["metadata"]) != FIELDS or f["metadata"]["id"] != f["id"]:
                raise InputError(f"cards {ctx}: fact fields or a repeated id")
            if not isinstance(f["metadata"]["text"], str) or f["line"] != "- " + clip(f["metadata"]["text"]):
                raise InputError(f"cards {ctx}: a fact line is not the clipped text of its fact")
            lab = labels.get(f["id"])
            if lab is None or lab["source_sha256"] != sha(canon(f["metadata"])):
                raise InputError(f"cards {ctx}: a fact has no label, or its label is stale")
            ids.append(f["id"])
            if keeps(f["metadata"], lab):
                keep.add(f["id"])
        cand = trim(c["parts"], c["facts"], keep)
        plan[ctx] = {"baseline": c["parts"], "candidate": cand, "kept": [i for i in ids if i in keep],
                     "removed": [i for i in ids if i not in keep],
                     "chars": {"baseline": sum(map(len, c["parts"])), "candidate": sum(map(len, cand))}}
    return plan


def inside(p: str, root: str) -> bool:
    return p == root or p.startswith(root.rstrip(os.sep) + os.sep)


def check_out(out: str, inputs: list[str]) -> str:
    out = os.path.join(os.path.realpath(os.path.dirname(os.path.abspath(out))), os.path.basename(out))
    if os.path.lexists(out) or not os.path.isdir(os.path.dirname(out)):
        raise InputError("output exists or its parent is missing")
    if any(inside(out, i) or inside(i, out) for i in inputs):
        raise InputError("output overlaps an input")
    return out


def tracked_files(repo: str) -> set[str]:
    r = subprocess.run(["git", "-C", repo, "ls-files", "-z"], capture_output=True, timeout=60,
                       env={"PATH": os.environ["PATH"], "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull})
    if r.returncode != 0:
        raise InputError("a repository does not list its files")
    return {x for x in r.stdout.decode().split("\0") if x}


class Tools:
    """The two read-only tools. Every refusal is a tool error the model reads; nothing else is executed."""

    def __init__(self, binary, env, cwds, repos, tracked):
        self.binary, self.env, self.cwds, self.repos, self.tracked = binary, env, cwds, repos, tracked
        self.lock = threading.Lock()  # one memcue process at a time: each opens the same store

    def call(self, ctx: str, name: str, arguments: str) -> tuple[str, dict]:
        rec = {"tool": name, "arguments": arguments}
        try:
            args = json.loads(arguments, object_pairs_hook=strict_object)
            if not isinstance(args, dict):
                raise ValueError("arguments are not an object")
            text = {"memory_search": self.search, "read_repository_file": self.read}[name](ctx, args, rec)
        except KeyError:
            text = f"error: unknown tool {name!r}" if name not in ("memory_search", "read_repository_file") \
                else "error: invalid arguments"
        except (ValueError, TypeError) as e:
            text = f"error: {e}"
        if not text.startswith("error:") and (found := secret(text)):
            text = f"error: the result holds a credential-shaped string ({found}); it was not sent"
        return text, {**rec, "result": text}

    def search(self, ctx, args, rec) -> str:
        q, lim, where = args["query"], args.get("limit", 5), args["in"]
        if set(args) - {"query", "limit", "in"} or not isinstance(q, str) or not q.strip() or len(q) > 500 or \
                type(lim) is not int or not 1 <= lim <= 5 or where not in ("all", "global", "project"):
            raise ValueError("invalid arguments")
        argv = [self.binary, "search", "-json", "-n", str(lim), "-cwd", self.cwds[ctx], "-in", where, "--", q]
        with self.lock:
            try:
                r = subprocess.run(argv, capture_output=True, text=True, env=self.env, cwd=self.env.get("HOME"),
                                   timeout=SEARCH_TIMEOUT)
            except subprocess.TimeoutExpired:
                rec["fatal"] = True
                return "error: memory_search timed out"
        # a failure of the binary is not an empty answer: it ends the arm (run_arm)
        rec.update(argv=argv[1:], exit=r.returncode, stdout=r.stdout, stderr=r.stderr, fatal=True)
        if r.returncode != 0:
            return f"error: memory_search failed (exit {r.returncode})"
        try:
            doc = json.loads(r.stdout)
        except ValueError:
            return "error: memory_search returned no JSON"
        doc = {"facts": doc} if isinstance(doc, list) else doc
        if not isinstance(doc, dict) or not set(doc) <= {"facts", "hints"} or not isinstance(doc.get("facts"), list) \
                or not all(isinstance(f, dict) and isinstance(f.get("id"), str) and isinstance(f.get("content"), str)
                           for f in doc["facts"]) or not isinstance(doc.get("hints", []), list):
            return "error: memory_search returned an unexpected shape"
        rec["fatal"] = False
        return json.dumps(doc, ensure_ascii=False)

    def read(self, ctx, args, rec) -> str:
        if ctx not in self.repos:
            return NO_REPO
        p = args["path"]
        if set(args) != {"path"} or not isinstance(p, str) or not 0 < len(p) <= 300 or "\0" in p or "\\" in p:
            raise ValueError("invalid arguments")
        parts = p.split("/")
        if any(x in ("", ".", "..", ".git") or BLOCKED.search(x) for x in parts):
            return "error: this path may not be read"
        if p not in self.tracked[ctx]:
            return "error: not a tracked file of the repository"
        root = self.repos[ctx]
        full = os.path.join(root, p)
        try:
            if os.path.realpath(full) != full or not inside(full, root):
                return "error: the path goes through a symlink"
            with os.fdopen(os.open(full, os.O_RDONLY | os.O_NOFOLLOW), "rb") as f:
                if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
                    return "error: not a regular file"
                data = f.read((1 << 20) + 1)
            if len(data) > 1 << 20:
                return "error: the file is larger than 1 MiB"
            text = data.decode()
        except (OSError, UnicodeDecodeError):
            return "error: not a readable UTF-8 file"
        if len(text) > FILE_CHARS:
            text = text[:FILE_CHARS] + f"\n[truncated: first {FILE_CHARS} of {len(text)} characters]"
        return text


def usage(resp) -> dict:
    u = getattr(resp, "usage", None)
    return {k: getattr(u, k, None) for k in ("prompt_tokens", "completion_tokens", "total_tokens")}


def conversation(system: str, history: list[dict], prompt: str) -> list[dict]:
    msgs = [{"role": "system", "content": system}]
    for h in history + [{"role": "user", "content": prompt}]:
        if msgs[-1]["role"] == h["role"]:
            msgs[-1] = {**msgs[-1], "content": msgs[-1]["content"] + "\n\n" + h["content"]}
        else:
            msgs.append(dict(h))
    return msgs


def run_arm(c, model, case, parts, tools: Tools) -> dict:
    """One arm of one case: at most 5 model turns and 12 tool calls; ok only for a finished, non-empty answer."""
    msgs = conversation(POLICY.format(timestamp=iso_utc(case["timestamp"])) + "\n\n" + "\n\n".join(parts),
                        case["history"], case["prompt"])
    rec = {"status": "error", "error": "turn limit", "answer": None, "turns": [], "tools": [], "tool_calls": 0}
    for _ in range(MAX_TURNS):
        request = {"model": model, "messages": msgs, "tools": TOOLS, "timeout": 120, "extra_body": REQUEST_EXTRA}
        turn = {"request": request, "request_sha256": sha(canon(request))}
        rec["turns"].append(turn)
        try:
            resp = c.chat.completions.create(**request)
            (choice,) = resp.choices
            msg, finish = choice.message, choice.finish_reason
            calls = [{"id": t.id, "type": "function", "function": {"name": t.function.name,
                                                                   "arguments": t.function.arguments}}
                     for t in (getattr(msg, "tool_calls", None) or [])]
        except Exception as e:  # noqa: BLE001 — the arm is an error, recorded by type only
            rec["error"] = type(e).__name__
            break
        content = msg.content if isinstance(msg.content, str) else None
        turn.update(content=content, tool_calls=calls, finish_reason=str(finish), usage=usage(resp),
                    response_sha256=sha(canon({"content": content, "tool_calls": calls})))
        if calls and finish == "tool_calls":
            msgs = msgs + [{"role": "assistant", "content": content or "", "tool_calls": calls}]
            for t in calls:
                if rec["tool_calls"] >= MAX_TOOLS:
                    text, tr = f"error: tool call limit ({MAX_TOOLS}) reached; answer now", {"tool": "limit",
                                                                                          "fatal": True}
                else:
                    rec["tool_calls"] += 1
                    text, tr = tools.call(case["context"], t["function"]["name"], t["function"]["arguments"])
                rec["tools"].append({**tr, "result": text})
                msgs = msgs + [{"role": "tool", "tool_call_id": t["id"], "content": text}]
                if tr.get("fatal"):  # a spent budget or a failed search: no later answer makes the arm ok
                    rec["error"] = text.removeprefix("error: ")
                    break
            else:
                continue
            break
        if not calls and finish == "stop" and content and content.strip():
            rec.update(status="ok", error=None, answer=content)
        else:
            rec["error"] = f"finish {finish}" if finish != "stop" else "empty answer or tool calls with stop"
        break
    rec["model_calls"] = len(rec["turns"])
    rec["answer_sha256"] = sha(rec["answer"]) if rec["answer"] else None
    return rec


def parse_verdict(content: str) -> dict:
    try:
        v = json.loads(content, object_pairs_hook=strict_object)
    except (TypeError, ValueError) as e:
        raise ReplyError(f"not strict JSON: {e}") from None
    keys = {"winner", "first_score", "second_score", "confidence", "reason"}
    if not isinstance(v, dict) or set(v) != keys or v["winner"] not in ("first", "second", "tie", "unknown") or \
            v["confidence"] not in ("high", "medium", "low") or not isinstance(v["reason"], str) or \
            len(v["reason"]) > 300 or any(type(v[k]) is not int or v[k] not in (0, 1, 2)
                                          for k in ("first_score", "second_score")):
        raise ReplyError("verdict fields")
    f, s = v["first_score"], v["second_score"]
    if {"first": f <= s, "second": s <= f, "tie": f != s}.get(v["winner"], False):
        raise ReplyError("winner disagrees with the scores")
    return v


def relative(v: dict, candidate_first: bool) -> str:
    w = v["winner"]
    if w in ("tie", "unknown"):
        return w
    return "win" if (w == "first") == candidate_first else "loss"


def judge(c, model, prompt, history, reference, first, second) -> dict:
    doc = {"history": history, "prompt": prompt, "reference_facts": reference, "first": first, "second": second}
    request = {"model": model, "timeout": 120, "extra_body": REQUEST_EXTRA,
               "messages": [{"role": "system", "content": JUDGE}, {"role": "user", "content": canon(doc)}]}
    rec = {"request": request, "request_sha256": sha(canon(request)), "verdict": None, "error": None, "content": None}
    try:
        resp = c.chat.completions.create(**request)
        (choice,) = resp.choices
        rec.update(content=choice.message.content, finish_reason=str(choice.finish_reason), usage=usage(resp))
        if choice.finish_reason != "stop" or getattr(choice.message, "tool_calls", None):
            raise ReplyError("not a finished text reply")
        rec["verdict"] = parse_verdict(choice.message.content)
    except Exception as e:  # noqa: BLE001 — an unreadable verdict stays UNKNOWN
        rec["error"] = f"{type(e).__name__}: {e}" if isinstance(e, ReplyError) else type(e).__name__
    rec["response_sha256"] = sha(rec["content"]) if isinstance(rec["content"], str) else None
    return rec


def with_client(factory, fn):
    try:
        c, model = factory()
    except Exception as e:  # noqa: BLE001
        return {"error": type(e).__name__}
    try:
        return fn(c, model)
    finally:
        c.close()


def owner_only(root: str) -> None:
    for top, dirs, files in os.walk(root):
        os.chmod(top, 0o700)
        for n in files:
            if stat.S_ISREG(os.lstat(p := os.path.join(top, n)).st_mode):
                os.chmod(p, 0o600)


def preflight(a):
    cases = read_json(a.cases)
    check_cases(cases)
    plan = plan_cards(read_json(a.cards), load_labels(a.labels))
    if missing := {c["context"] for c in cases} - set(plan):
        raise InputError(f"cards: no card for {len(missing)} context(s)")
    repos = dict(r.split("=", 1) for r in a.repo if "=" in r)
    repos = {k: os.path.realpath(v) for k, v in repos.items()}
    if len(a.repo) != 3 or set(repos) != {"A", "B", "C"} or len(set(repos.values())) != 3 or not all(
            os.path.isdir(os.path.join(r, ".git")) and not os.path.islink(os.path.join(r, ".git"))
            for r in repos.values()):
        raise InputError("need --repo A=, B= and C= naming three distinct git clones")
    facts = os.path.realpath(a.facts)
    if os.path.islink(a.facts) or not os.path.isdir(facts) or any(
            not (stat.S_ISDIR(m) or stat.S_ISREG(m)) for top, ds, fs in os.walk(facts)
            for m in (os.lstat(os.path.join(top, n)).st_mode for n in ds + fs)):
        raise InputError("facts must be a directory of regular files")
    binary = os.path.realpath(a.binary)
    if not os.path.isfile(binary) or not os.access(binary, os.X_OK):
        raise InputError("binary is not an executable file")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]{0,252}", a.host):
        raise InputError("host")
    inputs = [os.path.realpath(p) for p in (a.cases, a.cards, a.labels)] + [facts, binary] + list(repos.values())
    out = check_out(a.out, inputs)
    return cases, plan, repos, facts, binary, out, {k: tracked_files(v) for k, v in repos.items()}


def main(argv=None, factory=open_client) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    for f in ("--cases", "--cards", "--labels", "--facts", "--binary", "--host", "--out"):
        ap.add_argument(f, required=True)
    ap.add_argument("--repo", action="append", required=True)
    a = ap.parse_args(argv)
    try:
        cases, plan, repos, facts, binary, out_dir, tracked = preflight(a)
    except InputError as e:
        print(f"replay606: {e}", file=sys.stderr)
        return 2
    out = Out(Path(out_dir))
    try:
        return run(cases, plan, repos, facts, binary, out_dir, tracked, a.host, out, factory)
    finally:
        out.close()
        owner_only(out_dir)


def run(cases, plan, repos, facts, binary, out_dir, tracked, host, out, factory) -> int:
    def put(name, rec):
        with PUT:
            out.put(name, rec)
    shutil.copytree(facts, os.path.join(out_dir, "facts"), symlinks=True)
    sub = {n: os.path.join(out_dir, n) for n in ("state", "home", "xdg", "claude", "norepo")}
    for d in sub.values():
        os.mkdir(d, 0o700)
    owner_only(out_dir)
    env = {"PATH": os.environ["PATH"], "HOME": sub["home"], "LANG": "C.UTF-8", "MEMCUE_HOST": host,
           "MEMCUE_FACTS": os.path.join(out_dir, "facts"), "MEMCUE_STATE_DIR": sub["state"],
           "CLAUDE_CONFIG_DIR": sub["claude"], "XDG_STATE_HOME": sub["xdg"], "XDG_CACHE_HOME": sub["xdg"],
           "XDG_CONFIG_HOME": sub["xdg"], "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
           "MEMCUE_DREAM_BACKGROUND": "0"}
    tools = Tools(binary, env, {**repos, "G": sub["norepo"]}, repos, tracked)
    put("cards.json", plan)
    summary = {"calibration": "failed", "cases": len(cases)}
    jrng = random.Random(JUDGE_SEED)
    cal_ok = True
    for c in JUDGE_CALIBRATION:
        flip = jrng.random() < 0.5
        pair = ({"answer": c["second"], "tools": []}, {"answer": c["first"], "tools": []})
        rec = with_client(factory, lambda cl, mdl: judge(cl, mdl, c["prompt"], c["history"], c["reference"],
                                                         *(pair if flip else pair[::-1])))
        got = (rec.get("verdict") or {}).get("winner")
        got = {"first": "second", "second": "first"}.get(got, got) if flip else got
        cal_ok &= got in c["expect"]
        put("judge_calibration.jsonl", {**rec, "flipped": flip, "expect": c["expect"]})
        if not cal_ok:
            break
    if not cal_ok:
        put("summary.json", summary)
        print(json.dumps(summary))
        return 3
    summary["calibration"] = "passed"
    arng = random.Random(ARM_SEED)
    orders = [arng.sample(["baseline", "candidate"], 2) for _ in cases]
    firsts = [jrng.random() < 0.5 for _ in cases]

    def pair(i):
        case = cases[i]

        def both(cl, mdl):
            return {arm: run_arm(cl, mdl, case, plan[case["context"]][arm], tools) for arm in orders[i]}
        arms = with_client(factory, both)
        if "error" in arms:
            arms = {a: {"status": "error", "error": arms["error"], "model_calls": 0, "tool_calls": 0, "turns": [],
                        "tools": [], "answer": None} for a in orders[i]}
        for arm, rec in arms.items():
            rec.update(case_id=case["case_id"], arm=arm, order=orders[i].index(arm),
                       card_chars=plan[case["context"]]["chars"][arm])
            rec["record_sha256"] = sha(canon(rec))
            put("runs.jsonl", rec)
        return arms
    with ThreadPoolExecutor(WORKERS) as ex:
        runs = list(ex.map(pair, range(len(cases))))

    def grade(i):
        case, arms = cases[i], runs[i]
        if any(arms[a]["status"] != "ok" for a in arms):
            rec = {"case_id": case["case_id"], "result": "unknown", "error": "incomplete pair",
                   "candidate_first": firsts[i], "verdict": None}
            put("judge.jsonl", rec)
            return rec
        view = {a: {"answer": r["answer"], "tools": [{k: t.get(k) for k in ("tool", "arguments", "result")}
                                                     for t in r["tools"]]} for a, r in arms.items()}
        order = ("candidate", "baseline") if firsts[i] else ("baseline", "candidate")
        rec = with_client(factory, lambda cl, mdl: judge(
            cl, mdl, case["prompt"], case["history"], "\n\n".join(plan[case["context"]]["baseline"]),
            view[order[0]], view[order[1]]))
        v = rec.get("verdict")
        rec.update(case_id=case["case_id"], candidate_first=firsts[i], result=relative(v, firsts[i]) if v else "unknown")
        put("judge.jsonl", rec)
        return rec
    with ThreadPoolExecutor(WORKERS) as ex:
        verdicts = list(ex.map(grade, range(len(cases))))
    put("summary.json", tally(summary, plan, cases, runs, verdicts))
    print(json.dumps(summary))
    return 0 if summary["error_pairs"] == 0 and summary["judge_errors"] == 0 else 1


def tokens(usages: list) -> dict:
    """Token sums of the calls; a total only when every call reported that field as a non-negative int."""
    out = {"calls": len(usages)}
    for k in ("prompt_tokens", "completion_tokens", "total_tokens"):
        ok = [v for u in usages if isinstance(u, dict) and type(v := u.get(k)) is int and v >= 0]
        out[k] = {"known": sum(ok), "missing": len(usages) - len(ok),
                  "total": sum(ok) if len(ok) == len(usages) else None}
    return out


def tally(s, plan, cases, runs, verdicts) -> dict:
    complete = sum(all(r["status"] == "ok" for r in arms.values()) for arms in runs)
    s.update(complete_pairs=complete, error_pairs=len(cases) - complete,
             judge_errors=sum(1 for v in verdicts if v.get("error") and v.get("error") != "incomplete pair"))
    s["candidate"] = {k: sum(v["result"] == k for v in verdicts) for k in ("win", "tie", "loss", "unknown")}
    low = [v for v in verdicts if v.get("verdict") and v["verdict"]["confidence"] == "low"]
    s["low_confidence"] = {k: sum(v["result"] == k for v in low) for k in ("win", "tie", "loss")}
    s["conclusive"] = {k: s["candidate"][k] - s["low_confidence"][k] for k in ("win", "loss")}
    s["worse"], s["worse_conclusive"] = s["candidate"]["loss"], s["conclusive"]["loss"]
    tok = {}
    for arm in ("baseline", "candidate"):
        rs = [arms[arm] for arms in runs]
        tok[arm] = tokens([t.get("usage") for r in rs for t in r["turns"]])
        s[f"{arm}_model_calls"] = {"total": sum(r["model_calls"] for r in rs),
                                   "median": statistics.median(r["model_calls"] for r in rs)}
        s[f"{arm}_tool_calls"] = sum(r["tool_calls"] for r in rs)
        s[f"{arm}_card_chars"] = sum(plan[c["context"]]["chars"][arm] for c in cases)
    tok["judge"] = tokens([v.get("usage") for v in verdicts if "request" in v])
    s["tokens"] = tok
    s["card_facts"] = {"contexts": len(plan), "kept": sum(len(p["kept"]) for p in plan.values()),
                       "removed": sum(len(p["removed"]) for p in plan.values())}
    if sum(s["candidate"].values()) != len(cases) or complete + s["error_pairs"] != len(cases):
        raise AssertionError("summary does not reconcile")
    return s


if __name__ == "__main__":
    sys.exit(main())
