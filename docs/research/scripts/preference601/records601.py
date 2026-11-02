"""Records, grades and counts of the #601 measurement.

    python3 -I records601.py extract ROOT          compact records of every finished run into ROOT/records/
    python3 -I records601.py summary ROOT [--json OUT]   the counts of the report, from ROOT/records and ROOT/grades

A record is what a grader sees: the scenario's labels, the user's messages, the answers and, for a capture, the
changes to the fact base. It never names the arm. Its key is an opaque hash of the run's path, its sha256 the hash of
the record's canonical JSON; a grade counts only for the content it was given. Everything fails closed: a run that
did not finish, a stream without a result, a truncated stream, a grade that is not the exact JSON asked for, or a
grade of other content is an error or "unknown", never a "no". Every entry point that accepts a record recomputes its
sha256, and every accepted grade is parsed again from the grader's saved output against the record's fact ids; a
grade counts only if the grader's container and claude both exited 0. A run counts only if the docker_exit its
run.json saved is 0, whatever its own files say. A run directory was the agent's to write, so what is read from it may
not be a symlink or a special file, and a run that fails on a later extraction loses its record (moved aside as
.stale-<k>, not deleted). extract exits 1 when any run could not be extracted. Nothing here starts a container or a
model: these are offline checks of an archive the stand left.
"""

import argparse
import hashlib
import json
import os
import re
import secrets
import stat
import sys
from pathlib import Path

NOTE_END = "(memcue add / correct / retire)."
YES_NO = ("yes", "no")
SCHEMAS = {
    "durable": {"acknowledged": ("yes", "no", "unclear"), "preference_stored": ("yes", "partial", "no"),
                "preference_fact_ids": list, "extra_useful": int, "noise": int, "notes": str},
    "control": {"acknowledged": ("yes", "no", "unclear"), "durable_capture": YES_NO, "time_limited_capture": YES_NO,
                "extra_useful": int, "noise": int, "notes": str},
    "probe": {"applied": ("yes", "partial", "no", "unclear"), "evidence": str, "notes": str},
}
MEMCUE_CMD = re.compile(r"(^|[\s;&|(/])memcue\s")


class ExtractError(Exception):
    pass


class GradeError(Exception):
    pass


class TamperError(ExtractError):
    """A symlink, a special file or a hard link where the runner reads or writes its own files."""


class RecordError(Exception):
    """A record whose content does not hash to the sha256 it carries, or a set of records from mixed plans."""


def read_nofollow(path: Path) -> str:
    """The text of a regular file, opened without following a symlink in its last component."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "r", encoding="utf-8", errors="strict") as f:
        if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
            raise TamperError(f"{path.name} is not a regular file")
        return f.read()


def write_meta(d: Path, name: str, text: str) -> None:
    """Write d/name as a new file renamed into place. d is opened without following a symlink, a name that exists and
    is not a plain file with one link is refused (TamperError), and the rename replaces a name, never writes through
    it, so nothing outside d can be reached even if the agent planted links."""
    fd = os.open(d, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        try:
            st = os.stat(name, dir_fd=fd, follow_symlinks=False)
        except FileNotFoundError:
            st = None
        if st is not None and (not stat.S_ISREG(st.st_mode) or st.st_nlink != 1):
            raise TamperError(f"{name} in {d} is not a plain file; nothing written")
        tmp = f".{name}.{os.getpid()}.{secrets.token_hex(6)}.tmp"
        wfd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644, dir_fd=fd)
        with os.fdopen(wfd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, name, src_dir_fd=fd, dst_dir_fd=fd)
    finally:
        os.close(fd)


RUN_TOP = ("run.json", "docker.log")


def check_outputs(d: Path, top: tuple[str, ...] = RUN_TOP) -> None:
    """Refuse a run (or grading) directory whose files the runner reads include a symlink or a special file: d
    itself, the names in top and everything under d/rec. The runner calls it after the container has exited."""
    if d.is_symlink() or not d.is_dir():
        raise TamperError(f"{d} is not a directory")
    for name in top:
        q = d / name
        if q.is_symlink() or (q.exists() and not q.is_file()):
            raise TamperError(f"{name} in {d.name} is not a regular file")
    rec = d / "rec"
    if rec.is_symlink():
        raise TamperError(f"rec in {d.name} is a symlink")
    if not rec.exists():
        return
    if not rec.is_dir():
        raise TamperError(f"rec in {d.name} is not a directory")
    for base, dirs, files in os.walk(rec, followlinks=False):
        for n in dirs + files:
            mode = os.lstat(os.path.join(base, n)).st_mode
            if not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
                raise TamperError(f"{os.path.relpath(os.path.join(base, n), d)} is a symlink or a special file")


def _lines(path: Path) -> list[dict]:
    try:
        text = read_nofollow(path)
    except (OSError, ValueError) as e:
        raise ExtractError(f"{path.name}: {e}") from e
    out = []
    for i, line in enumerate(text.splitlines()):
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except ValueError as e:
            raise ExtractError(f"{path.name}: line {i + 1} is not JSON (truncated stream?)") from e
    return out


def stream_cost(path: Path) -> float:
    """The cost the result events of a stream report; 0 for a stream that cannot be read (it still exists on disk)."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return 0.0
    total = 0.0
    for line in text.splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if isinstance(ev, dict) and ev.get("type") == "result":
            total += float(ev.get("total_cost_usd") or 0)
    return total


def run_cost(rec_dir: Path) -> float:
    """The cost of one run. Claude Code reports a resumed session's cost cumulatively: the result of the second turn
    already holds the first, so a capture costs its second turn when that turn reported, else its first."""
    t2 = stream_cost(rec_dir / "turn2.jsonl")
    if t2 > 0:
        return t2
    return stream_cost(rec_dir / "turn1.jsonl") + stream_cost(rec_dir / "probe.jsonl")


def _text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(c.get("text", "") for c in content if isinstance(c, dict))
    return ""


def parse_stream(path: Path) -> dict:
    evs = _lines(path)
    init = next((e for e in evs if e.get("type") == "system" and e.get("subtype") == "init"), None)
    results = [e for e in evs if e.get("type") == "result"]
    if not results:
        raise ExtractError(f"{path.name}: no result event")
    res = results[-1]
    calls, outputs = [], {}
    for e in evs:
        msg = e.get("message") or {}
        for c in msg.get("content") or [] if isinstance(msg.get("content"), list) else []:
            if e.get("type") == "assistant" and c.get("type") == "tool_use":
                calls.append({"id": c.get("id"), "name": c.get("name"), "input": c.get("input") or {}})
            elif e.get("type") == "user" and c.get("type") == "tool_result":
                outputs[c.get("tool_use_id")] = _text(c.get("content"))
    for c in calls:
        c["output"] = outputs.get(c["id"])
    memcue = [{"command": c["input"].get("command", ""), "output": (c["output"] or "")[:800]}
              for c in calls if c["name"] == "Bash" and MEMCUE_CMD.search(" " + c["input"].get("command", ""))]
    hooks = [e for e in evs if e.get("type") == "system" and str(e.get("subtype", "")).startswith("hook")]
    return {
        "result": res.get("result") if isinstance(res.get("result"), str) else None,
        "subtype": res.get("subtype"),
        "is_error": bool(res.get("is_error")) or res.get("subtype") != "success" or not isinstance(
            res.get("result"), str),
        "cost_usd": float(res.get("total_cost_usd") or 0),
        "usage": res.get("usage") or {},
        "duration_ms": res.get("duration_ms"),
        "num_turns": res.get("num_turns"),
        "session_id": (init or {}).get("session_id") or res.get("session_id"),
        "models": sorted((res.get("modelUsage") or {}).keys()),
        "init": {k: (init or {}).get(k) for k in ("model", "claude_code_version", "plugins", "mcp_servers",
                                                   "permissionMode", "apiKeySource", "tools")},
        "tool_calls": [{"name": c["name"], "input": c["input"]} for c in calls],
        "memcue_calls": memcue,
        "hook_events": hooks,
    }


def snapshot(facts_dir: Path) -> dict[str, list[dict]]:
    """Every fact of a text history with its versions, oldest first."""
    out: dict[str, list[dict]] = {}
    if not facts_dir.is_dir():
        return out
    for p in sorted(facts_dir.rglob("*.jsonl")):
        for line in read_nofollow(p).splitlines():
            if line.strip():
                v = json.loads(line)
                out.setdefault(v["id"], []).append(v)
    for vs in out.values():
        vs.sort(key=lambda v: v.get("version", 0))
    return out


def diff_facts(before: dict, after: dict) -> list[dict]:
    out = []
    for fid, vs in sorted(after.items()):
        old = before.get(fid, [])
        if len(vs) == len(old):
            continue
        last = vs[-1]
        if not old:
            change = "added"
        elif last.get("status") == "retired":
            change = "retired"
        else:
            change = "corrected"
        out.append({"id": fid, "change": change, "version": last.get("version"), "kind": last.get("kind", ""),
                    "scope": last.get("scope", ""), "source": last.get("source", ""),
                    "expires": last.get("expires", ""), "content": last.get("content", ""),
                    "keywords": last.get("keywords", [])})
    return out


def record_sha(record: dict) -> str:
    return hashlib.sha256(json.dumps(record, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _finished(d: Path, streams: tuple[str, ...]) -> list[dict]:
    check_outputs(d)
    try:
        meta = json.loads(read_nofollow(d / "run.json"))
    except (OSError, ValueError) as e:
        raise ExtractError(f"{d}: no readable run.json") from e
    # What the container left can look complete although the runner saw it fail or time out.
    if type(meta.get("docker_exit")) is not int or meta["docker_exit"] != 0:
        raise ExtractError(f"{d}: docker_exit {meta.get('docker_exit', 'missing')!r}, not 0")
    try:
        code = read_nofollow(d / "rec" / "exit").strip()
    except OSError as e:
        raise ExtractError(f"{d}: no exit file") from e
    if code != "0":
        raise ExtractError(f"{d}: exit {code}")
    out = [parse_stream(d / "rec" / s) for s in streams]
    for s, p in zip(streams, out):
        if p["is_error"]:
            raise ExtractError(f"{d}: {s} ended with {p['subtype']}")
    return out


def capture_record(d: Path, sc: dict, labels: dict) -> dict:
    t1, t2 = _finished(d, ("turn1.jsonl", "turn2.jsonl"))
    snaps = {}
    for name in ("before", "after1", "after2"):
        p = d / "rec" / f"base-{name}"
        if not p.is_dir():
            raise ExtractError(f"{d}: no snapshot base-{name}")
        snaps[name] = snapshot(p / "facts")
    record = {
        "scenario": sc["id"], "kind": sc["kind"], "labels": labels,
        "prompts": {"turn1": sc["turn1"], "turn2": sc["turn2"]},
        "answers": {"turn1": t1["result"], "turn2": t2["result"]},
        "base_changes": diff_facts(snaps["before"], snaps["after2"]),
        "memcue_calls": [dict(c, turn=1) for c in t1["memcue_calls"]] + [dict(c, turn=2) for c in t2["memcue_calls"]],
    }
    meta = {"streams": {"turn1": _meta(t1), "turn2": _meta(t2)},
            "changes_after_turn1": len(diff_facts(snaps["before"], snaps["after1"])),
            "facts_before": len(snaps["before"])}
    return {"record": record, "sha256": record_sha(record), "meta": meta}


def probe_record(d: Path, sc: dict, labels: dict) -> dict:
    (p,) = _finished(d, ("probe.jsonl",))
    lab = {k: labels.get(k) for k in ("preference", "probe_applied_if", "probe_partial_if")}
    record = {"scenario": sc["id"], "kind": "probe", "labels": lab, "prompt": sc["probe"]["prompt"],
              "answer": p["result"]}
    return {"record": record, "sha256": record_sha(record), "meta": {"streams": {"probe": _meta(p)}}}


def _meta(s: dict) -> dict:
    return {k: s[k] for k in ("cost_usd", "usage", "duration_ms", "num_turns", "session_id", "models", "init",
                              "subtype")} | {"memcue_calls": len(s["memcue_calls"]),
                                             "searches": sum("memcue search" in c["command"] for c in s[
                                                 "memcue_calls"]),
                                             "tool_calls": [c["name"] for c in s["tool_calls"]],
                                             "hooks": _hooks(s["hook_events"])}


def _hooks(events: list[dict]) -> list[dict]:
    """What each SessionStart hook handed the model, as the stream reports it: whether it carried the note's end and
    the candidate line, and its length; not the text."""
    out = []
    for e in events:
        blob = json.dumps(e, ensure_ascii=False)
        out.append({"subtype": e.get("subtype"), "hook_name": e.get("hook_name"), "hook_event": e.get("hook_event"),
                    "exit_code": e.get("exit_code"), "outcome": e.get("outcome"), "note_end": NOTE_END in blob,
                    "reminder": "standing rule of the user's" in blob, "chars": len(blob)})
    return out


def delivery(streams: dict) -> dict:
    """Whether every claude call of a run got the memory note, and the candidate line, from its SessionStart hooks."""
    def every(flag: str) -> bool:
        return bool(streams) and all(any(h["subtype"] == "hook_response" and h[flag] for h in s["hooks"])
                                     for s in streams.values())
    return {"note": every("note_end"), "reminder": every("reminder")}


def run_key(rel: str) -> str:
    return hashlib.sha256(("601:" + rel).encode()).hexdigest()[:20]


def quarantine(p: Path, tag: str) -> Path:
    """Move a record or grade aside as <key>.<tag>-<k>.json; nothing is deleted."""
    k = 1
    while p.with_name(f"{p.stem}.{tag}-{k}.json").exists():
        k += 1
    dest = p.with_name(f"{p.stem}.{tag}-{k}.json")
    p.rename(dest)
    return dest


def extract(root: Path) -> int:
    scs = {s["id"]: s for s in json.loads((root / "fixtures/scenarios.json").read_text(encoding="utf-8"))["scenarios"]}
    labels = json.loads((root / "fixtures/labels.json").read_text(encoding="utf-8"))
    out = root / "records"
    out.mkdir(exist_ok=True)
    produced, errors = set(), []
    for d in sorted((root / "runs").glob("*/*/*/r*")):
        if not d.name[1:].isdigit():
            continue  # an attempt moved aside
        phase, arm, sid = d.parts[-4], d.parts[-3], d.parts[-2]
        rel = str(d.relative_to(root))
        try:
            if phase == "capture":
                r = capture_record(d, scs[sid], labels[sid])
                kind = scs[sid]["kind"]
            else:
                r = probe_record(d, scs[sid], labels[sid])
                kind = "probe"
            r["meta"].update(json.loads(read_nofollow(d / "run.json")))
            r["meta"]["run"] = rel
            for name in ("hook601.log", "card.log", "preflight.json"):
                q = d / "rec" / name
                r["meta"][name] = read_nofollow(q)[-6000:] if q.is_file() else None
        except (ExtractError, OSError, ValueError, KeyError) as e:
            errors.append(f"{rel}: {type(e).__name__}: {e}")
            continue
        doc = {"key": run_key(rel), "sha256": r["sha256"], "grade_kind": kind, "record": r["record"],
               "meta": r["meta"]}
        dest = out / f"{doc['key']}.json"
        if dest.exists() and json.loads(dest.read_text(encoding="utf-8")).get("sha256") != doc["sha256"]:
            quarantine(dest, "replaced")
        write_meta(out, dest.name, json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
        produced.add(doc["key"])
    stale = [quarantine(p, "stale") for p in sorted(out.glob("*.json")) if "." not in p.stem
             and p.stem not in produced]
    print(json.dumps({"records": len(produced), "errors": len(errors), "stale_moved_aside": len(stale)}))
    for e in errors:
        print("error:", e)
    return 1 if errors else 0


def parse_grade(text: str, kind: str, ids: set[str] | None = None) -> dict:
    if kind not in SCHEMAS:
        raise GradeError(f"unknown grade kind {kind!r}")
    t = text.strip()
    m = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", t, re.S)
    if m:
        t = m.group(1)
    try:
        doc = json.loads(t)
    except ValueError as e:
        raise GradeError("the grade is not one JSON object") from e
    if not isinstance(doc, dict):
        raise GradeError("the grade is not a JSON object")
    schema = SCHEMAS[kind]
    if set(doc) != set(schema):
        raise GradeError(f"keys {sorted(doc)} are not {sorted(schema)}")
    for k, want in schema.items():
        v = doc[k]
        if isinstance(want, tuple):
            if v not in want:
                raise GradeError(f"{k}={v!r} is not one of {want}")
        elif want is int:
            if type(v) is not int or v < 0:
                raise GradeError(f"{k}={v!r} is not a count")
        elif want is list:
            if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
                raise GradeError(f"{k} is not a list of ids")
        elif not isinstance(v, want):
            raise GradeError(f"{k} is not {want.__name__}")
    if kind == "durable":
        stored = doc["preference_stored"] != "no"
        if stored != bool(doc["preference_fact_ids"]):
            raise GradeError("preference_fact_ids must name the facts exactly when the preference is stored")
        if ids is not None and not set(doc["preference_fact_ids"]) <= ids:
            raise GradeError("preference_fact_ids names a fact the record does not have")
    return doc


def grade_prompt(doc: dict, template: str) -> str:
    if template.count("{{RECORD}}") != 1:
        raise GradeError("the grading template must hold {{RECORD}} once")
    return template.replace("{{RECORD}}", json.dumps(doc["record"], indent=1, ensure_ascii=False))


def check_record(doc: dict) -> dict:
    if record_sha(doc["record"]) != doc.get("sha256"):
        raise RecordError(f"record {doc.get('key')}: its content does not hash to the sha256 it carries")
    return doc


def load_record(path: Path) -> dict:
    doc = json.loads(path.read_text(encoding="utf-8"))
    if doc.get("key") != path.stem:
        raise RecordError(f"{path.name}: key {doc.get('key')!r} does not match the file name")
    return check_record(doc)


def valid_grade(root: Path, pas: str, doc: dict) -> dict | None:
    """The grade of pass pas for the record doc, or None. It counts only if it names the record's sha256, the
    grader's container and claude exited 0, the grader's own saved output parses again under the schema and the
    record's fact ids, and that parse is the saved one."""
    try:
        g = json.loads((root / "grades" / pas / f"{doc['key']}.json").read_text(encoding="utf-8"))
        if g.get("record_sha256") != doc["sha256"] or g.get("error") or g.get("docker_exit") != 0:
            return None
        if not isinstance(g.get("parsed"), dict) or not isinstance(g.get("work"), str):
            return None
        work = (root / g["work"]).resolve()
        if root.resolve() not in work.parents:
            return None
        check_outputs(work, ("out.json", "exit"))
        if read_nofollow(work / "exit").strip() != "0":
            return None
        res = json.loads(read_nofollow(work / "out.json"))
        if res.get("is_error") or res.get("subtype") != "success" or not isinstance(res.get("result"), str):
            return None
        ids = {c["id"] for c in doc["record"].get("base_changes") or []}
        again = parse_grade(res["result"], doc["grade_kind"], ids)
    except (OSError, ValueError, KeyError, GradeError):
        return None
    return again if again == g["parsed"] else None


def combined(root: Path, doc: dict, passes: tuple[str, ...] = ("A", "B")) -> dict:
    check_record(doc)
    kind = doc["grade_kind"]
    gs = [valid_grade(root, p, doc) for p in passes]
    out = {}
    for k in SCHEMAS[kind]:
        if k in ("notes", "evidence"):
            continue
        if any(g is None for g in gs):
            out[k] = "unknown"
            continue
        vals = [sorted(g[k]) if isinstance(g[k], list) else g[k] for g in gs]
        out[k] = vals[0] if all(v == vals[0] for v in vals) else "disputed"
    return out


def count(rows: list[dict], field: str) -> dict:
    out: dict = {}
    for r in rows:
        v = r[field]
        v = json.dumps(v) if isinstance(v, list) else v
        out[v] = out.get(v, 0) + 1
    out["n"] = len(rows)
    return out


def summary(root: Path) -> dict:
    docs = [load_record(p) for p in sorted((root / "records").glob("*.json")) if "." not in p.stem]
    plans = {(d["meta"].get("plan_sha256"), d["meta"].get("inputs_sha256"), d["meta"].get("image")) for d in docs}
    if len(plans) > 1:
        raise RecordError(f"the records come from {len(plans)} different plans, inputs or images")
    rows = []
    for d in docs:
        m = d["meta"]
        c = combined(root, d)
        per_pass = {p: valid_grade(root, p, d) for p in ("A", "B")}
        streams = m["streams"].values()
        row = {"key": d["key"], "phase": m["phase"], "arm": m["arm"], "scenario": m["scenario"],
               "repeat": m["repeat"], "kind": d["grade_kind"], "sha256": d["sha256"], **c,
               "pass": {p: (None if g is None else {k: v for k, v in g.items() if k not in ("notes", "evidence")})
                        for p, g in per_pass.items()},
               "cost_usd": round(max(s["cost_usd"] for s in streams), 6),  # cumulative over a resumed session
               "seconds": round(sum((s["duration_ms"] or 0) for s in streams) / 1000, 1),
               "tokens": {k: sum(int(s["usage"].get(k) or 0) for s in streams) for k in (
                   "input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")},
               "models": sorted({x for s in streams for x in s["models"]}),
               "searches": sum(s["searches"] for s in streams),
               "memcue_calls": sum(s["memcue_calls"] for s in streams),
               "delivery": delivery(m["streams"])}
        if m["phase"] == "capture":
            ch = d["record"]["base_changes"]
            row["changes"] = len(ch)
            row["changes_after_turn1"] = m["changes_after_turn1"]
            ids = c.get("preference_fact_ids")
            pref = [x for x in ch if isinstance(ids, list) and x["id"] in ids]
            row["preference_facts"] = [{k: x[k] for k in ("kind", "scope", "source", "expires")} for x in pref]
        else:
            card = m.get("card.log") or ""
            row["card_ids"] = sorted({i for line in card.splitlines() if line.strip()
                                      for i in json.loads(line).get("facts") or []})
            row["base_copied"] = m.get("base_copied")
            row["capture_run"] = m.get("capture_run")
        rows.append(row)
    caps = {(r["arm"], r["scenario"], r["repeat"]): r for r in rows if r["phase"] == "capture"}
    for r in rows:
        if r["phase"] == "probe":
            cap = caps.get((r["arm"], r["scenario"], r["repeat"]))
            ids = cap.get("preference_fact_ids") if cap else None
            r["capture_preference_stored"] = cap.get("preference_stored") if cap else "unknown"
            r["card_has_preference"] = ("unknown" if not isinstance(ids, list)
                                        else bool(set(ids) & set(r["card_ids"])))
    return {"rows": rows, "aggregate": aggregate(rows)}


def _sum_agreed(rows: list[dict], field: str) -> tuple[int, int]:
    agreed = [r[field] for r in rows if type(r.get(field)) is int]
    return sum(agreed), len(rows) - len(agreed)


def _money(rows: list[dict]) -> dict:
    tok = {}
    for r in rows:
        for k, v in (r.get("tokens") or {}).items():
            tok[k] = tok.get(k, 0) + v
    return {"runs": len(rows), "cost_usd": round(sum(r["cost_usd"] for r in rows), 4),
            "mean_seconds": round(sum(r["seconds"] for r in rows) / len(rows), 1) if rows else None, "tokens": tok,
            "searched": sum(1 for r in rows if r.get("searches")),
            "note_delivered": sum(1 for r in rows if r["delivery"]["note"]),
            "reminder_delivered": sum(1 for r in rows if r["delivery"]["reminder"])}


def aggregate(rows: list[dict]) -> dict:
    """The counts of the report per arm. Unknown and disputed labels stay as they are; they are never folded into a
    "no"."""
    out: dict = {"capture_durable": {}, "capture_control": {}, "probe": {}, "reference": {}}
    for arm in sorted({r["arm"] for r in rows}):
        dur = [r for r in rows if r["arm"] == arm and r["phase"] == "capture" and r["kind"] == "durable"]
        if dur:
            stored = [r for r in dur if r["preference_stored"] in ("yes", "partial")]
            facts = [f for r in stored for f in r.get("preference_facts") or []]
            noise, noise_na = _sum_agreed(dur, "noise")
            extra, extra_na = _sum_agreed(dur, "extra_useful")
            out["capture_durable"][arm] = {
                "acknowledged": count(dur, "acknowledged"),
                "preference_stored": count(dur, "preference_stored"),
                "stored_when_acknowledged": count([r for r in dur if r["acknowledged"] == "yes"],
                                                  "preference_stored"),
                "stored_when_not_acknowledged": count([r for r in dur if r["acknowledged"] == "no"],
                                                      "preference_stored"),
                "stored_global": sum(1 for r in stored if any(f["scope"] == "global" for f in r[
                    "preference_facts"])),
                "stored_rule_user": sum(1 for r in stored if any(f["kind"] == "rule" and f["source"] == "user"
                                                                 for f in r["preference_facts"])),
                "preference_facts": len(facts),
                "fact_kinds": count([{"k": f"{f['kind'] or '-'}/{f['scope']}/{f['source']}"} for f in facts], "k"),
                "changes": sum(r["changes"] for r in dur),
                "extra_useful": extra, "extra_useful_not_agreed": extra_na,
                "noise": noise, "noise_not_agreed": noise_na,
                "money": _money(dur)}
        ctl = [r for r in rows if r["arm"] == arm and r["phase"] == "capture" and r["kind"] == "control"]
        if ctl:
            noise, noise_na = _sum_agreed(ctl, "noise")
            out["capture_control"][arm] = {
                "acknowledged": count(ctl, "acknowledged"), "durable_capture": count(ctl, "durable_capture"),
                "time_limited_capture": count(ctl, "time_limited_capture"),
                "runs_with_changes": sum(1 for r in ctl if r["changes"]), "changes": sum(r["changes"] for r in ctl),
                "noise": noise, "noise_not_agreed": noise_na, "money": _money(ctl)}
        for phase in ("probe", "reference"):
            pr = [r for r in rows if r["arm"] == arm and r["phase"] == phase]
            if pr:
                out[phase][arm] = {
                    "applied": count(pr, "applied"),
                    "applied_when_card_had_it": count([r for r in pr if r.get("card_has_preference") is True],
                                                      "applied"),
                    "applied_when_card_lacked_it": count([r for r in pr if r.get("card_has_preference") is False],
                                                         "applied"),
                    "money": _money(pr)}
    per = {}
    for r in rows:
        k = f"{r['phase']}/{r['scenario']}/{r['arm']}"
        f = {"capture": "preference_stored" if r["kind"] == "durable" else "durable_capture"}.get(r["phase"],
                                                                                                  "applied")
        per.setdefault(k, {"label": f, "values": [], "acknowledged": []})
        per[k]["values"].append(r[f])
        if r["phase"] == "capture":
            per[k]["acknowledged"].append(r["acknowledged"])
    out["per_scenario"] = per
    return out


META_KEYS = ("phase", "arm", "scenario", "repeat", "image", "inputs_sha256", "docker_exit", "seconds",
             "changes_after_turn1", "facts_before", "base_copied")
STREAM_KEYS = ("cost_usd", "usage", "duration_ms", "num_turns", "models", "subtype", "memcue_calls", "searches",
               "tool_calls", "hooks")


def public(doc: dict) -> dict:
    """A record for the repository: the graded record and an allowlist of its metadata; no session ids, logs or
    paths."""
    m = doc["meta"]
    streams = {}
    for name, st in m.get("streams", {}).items():
        x = {k: st.get(k) for k in STREAM_KEYS}
        init = st.get("init") or {}
        x["init"] = {"model": init.get("model"), "claude_code_version": init.get("claude_code_version"),
                     "plugins": [pl.get("name") for pl in init.get("plugins") or []],
                     "mcp_servers": init.get("mcp_servers"), "permissionMode": init.get("permissionMode"),
                     "tools": init.get("tools")}
        streams[name] = x
    card = [i for line in (m.get("card.log") or "").splitlines() if line.strip()
            for i in json.loads(line).get("facts") or []]
    meta = {k: m.get(k) for k in META_KEYS if k in m} | {"streams": streams, "card_ids": sorted(set(card))}
    return {"key": doc["key"], "sha256": doc["sha256"], "grade_kind": doc["grade_kind"], "record": doc["record"],
            "meta": meta}


def export(root: Path, dest: Path) -> int:
    """Public records, grades and the summary of ROOT into DEST (a new directory)."""
    dest.mkdir(parents=True)
    (dest / "records").mkdir()
    for p in sorted((root / "records").glob("*.json")):
        if "." in p.stem:
            continue
        doc = public(load_record(p))
        (dest / "records" / p.name).write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n",
                                               encoding="utf-8")
    for pas in sorted(x.name for x in (root / "grades").iterdir() if x.is_dir()):
        (dest / "grades" / pas).mkdir(parents=True)
        for p in sorted((root / "grades" / pas).glob("*.json")):
            if "." in p.stem:
                continue
            g = json.loads(p.read_text(encoding="utf-8"))
            keep = {k: g.get(k) for k in ("key", "record_sha256", "kind", "pass", "model", "parsed", "error",
                                          "cost_usd", "seconds", "docker_exit")}
            work = root / g["work"] if isinstance(g.get("work"), str) else None
            try:
                check_outputs(work, ("out.json", "exit"))
                keep["grader_exit"] = read_nofollow(work / "exit").strip()
                keep["raw_result"] = json.loads(read_nofollow(work / "out.json")).get("result")
            except (TypeError, OSError, ValueError, ExtractError):
                keep["grader_exit"], keep["raw_result"] = None, None
            (dest / "grades" / pas / p.name).write_text(json.dumps(keep, indent=1, ensure_ascii=False) + "\n",
                                                        encoding="utf-8")
    doc = summary(root)
    (dest / "summary.json").write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"records": len(list((dest / "records").glob("*.json"))), "dest": str(dest)}))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("extract")
    e.add_argument("root", type=Path)
    s = sub.add_parser("summary")
    s.add_argument("root", type=Path)
    s.add_argument("--json", type=Path)
    x = sub.add_parser("export")
    x.add_argument("root", type=Path)
    x.add_argument("dest", type=Path)
    a = ap.parse_args()
    if a.cmd == "export":
        return export(a.root.resolve(), a.dest)
    if a.cmd == "extract":
        return extract(a.root.resolve())
    try:
        doc = summary(a.root.resolve())
    except RecordError as e:
        print(f"summary refused: {e}", file=sys.stderr)
        return 1
    text = json.dumps(doc, indent=1, ensure_ascii=False)
    if a.json:
        a.json.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
