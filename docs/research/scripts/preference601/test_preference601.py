"""Tests of the #601 offline scripts: the SessionStart filter, records, grades, counts and the archive check. Run: python3 -I -m unittest test_preference601 (from this directory).

They use invented data only. The tests of the SessionStart filter run the memcue binary named by MEMCUE601_BIN when it
is set (a build of the checkout under study); without it they are skipped, and the run is not a full check.
"""

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


reminder = load("reminder601", HERE / "stand" / "reminder601.py")
arch = load("archive601", HERE / "archive601.py")
rec = load("records601", HERE / "records601.py")

REMINDER = (HERE / "candidate" / "reminder.md").read_text(encoding="utf-8").strip()
NOTE_END = "(memcue add / correct / retire)."


def hook_json(context: str) -> str:
    return json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": context}}) + "\n"


class ReminderFilter(unittest.TestCase):
    def test_inserts_once_after_the_note(self):
        ctx = "Long-term memory ...\n- When the user asks ... " + NOTE_END + "\n\nmemcue: rules and decisions\n- a rule"
        out, info = reminder.insert(hook_json(ctx), REMINDER)
        got = json.loads(out)["hookSpecificOutput"]["additionalContext"]
        self.assertTrue(info["inserted"])
        self.assertEqual(got, ctx.replace(NOTE_END, NOTE_END + "\n- " + REMINDER))
        self.assertEqual(got.count(REMINDER), 1)

    def test_no_anchor_leaves_output_unchanged(self):
        raw = hook_json("memcue: the binary is not installed")
        out, info = reminder.insert(raw, REMINDER)
        self.assertEqual(out, raw)
        self.assertFalse(info["inserted"])
        self.assertIn("anchor", info["reason"])

    def test_two_anchors_leave_output_unchanged(self):
        raw = hook_json(NOTE_END + " " + NOTE_END)
        out, info = reminder.insert(raw, REMINDER)
        self.assertEqual(out, raw)
        self.assertFalse(info["inserted"])

    def test_not_json_is_passed_through(self):
        out, info = reminder.insert("garbage", REMINDER)
        self.assertEqual(out, "garbage")
        self.assertFalse(info["inserted"])

    def test_empty_output_is_passed_through(self):
        out, info = reminder.insert("", REMINDER)
        self.assertEqual(out, "")
        self.assertFalse(info["inserted"])

    def test_part_over_budget_is_not_extended(self):
        raw = hook_json("x" * 9400 + NOTE_END)
        out, info = reminder.insert(raw, REMINDER)
        self.assertEqual(out, raw)
        self.assertIn("budget", info["reason"])


@unittest.skipUnless(os.environ.get("MEMCUE601_BIN"), "MEMCUE601_BIN names no memcue build")
class ReminderOnTheRealBinary(unittest.TestCase):
    """Both plugins of make_inputs.py run on a real memcue build, through their own hooks: the candidate's part 1 is
    the shipped part 1 plus one line, its parts 2 and 3 are the shipped ones byte for byte, neither plugin asks for
    part 0 (the whole text in one block), and part 0 still opens with the same note."""

    REPO = HERE.parents[3]

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.t = Path(self.tmp.name)
        subprocess.run([sys.executable, "-I", str(HERE / "stand" / "make_inputs.py"), str(self.REPO),
                        os.environ["MEMCUE601_BIN"], str(self.t / "inputs")], check=True, capture_output=True)

    def tearDown(self):
        self.tmp.cleanup()

    def env(self, tag: str) -> dict:
        return {"PATH": "/usr/bin:/bin", "HOME": str(self.t / "home"), "MEMCUE_FACTS": str(self.t / "base" / "facts"),
                "MEMCUE_STATE_DIR": str(self.t / f"state-{tag}"), "MEMCUE_DREAM_BACKGROUND": "0",
                "MEMCUE_AUTO_INSTALL": "0", "MEMCUE_BIN": os.environ["MEMCUE601_BIN"],
                "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1"}

    def seed(self, ws: Path, facts: int) -> None:
        ws.mkdir()
        subprocess.run(["git", "-C", str(ws), "init", "-q"], check=True)
        for i in range(facts):
            subprocess.run([os.environ["MEMCUE601_BIN"], "add", "-kind", "rule", "-scope", "global", "-source",
                            "user", "-keywords", f"invented, rule{i}", "--",
                            f"Invented rule {i}: the user wants every report about the fictional Quillmoor "
                            f"service to name its owner, rule number {i}, padded to fill the card. " * 2],
                           env=self.env("seed"), cwd=ws, check=True, capture_output=True)

    def contexts(self, arm: str, ws: Path) -> list[str]:
        plugin = self.t / "inputs" / f"plugin-{arm}"
        hooks = json.loads((plugin / "hooks" / "hooks.json").read_text())["hooks"]["SessionStart"]
        payload = json.dumps({"session_id": "t", "source": "startup", "cwd": str(ws)})
        out = []
        for g in hooks:
            cmd = g["hooks"][0]["command"]
            self.assertNotIn("-part 0", cmd)
            p = subprocess.run(["sh", "-c", cmd], input=payload, cwd=ws, capture_output=True, text=True,
                               env=dict(self.env(arm), CLAUDE_PLUGIN_ROOT=str(plugin)), check=True)
            out.append(json.loads(p.stdout)["hookSpecificOutput"]["additionalContext"] if p.stdout.strip() else "")
        return out

    def binary_part(self, part: int, ws: Path) -> str:
        payload = json.dumps({"session_id": "t", "source": "startup", "cwd": str(ws)})
        p = subprocess.run([os.environ["MEMCUE601_BIN"], "session-start", "-part", str(part)], input=payload,
                           cwd=ws, capture_output=True, text=True, env=self.env("bin"), check=True)
        return json.loads(p.stdout)["hookSpecificOutput"]["additionalContext"] if p.stdout.strip() else ""

    def test_parts_0_to_3(self):
        for facts in (0, 1, 60):
            with self.subTest(facts=facts):
                for x in ("base", "home", "ws"):
                    shutil.rmtree(self.t / x, ignore_errors=True)
                ws = self.t / "ws"
                self.seed(ws, facts)
                base, cand = self.contexts("base", ws), self.contexts("cand", ws)
                self.assertEqual(len(base), 3)
                self.assertEqual(base, [self.binary_part(n, ws) for n in (1, 2, 3)])  # the plugin passes through
                self.assertEqual(cand[1:], base[1:])
                note = base[0][:base[0].index(NOTE_END) + len(NOTE_END)]
                self.assertTrue(self.binary_part(0, ws).startswith(note))
                if len(base[0]) + len(REMINDER) + 3 >= reminder.PART_BUDGET:
                    self.assertEqual(cand[0], base[0])  # a full part is left as it is; such a run is invalid
                    continue
                self.assertEqual(cand[0], base[0].replace(NOTE_END, NOTE_END + "\n- " + REMINDER, 1))
                card = lambda parts: sorted(l for x in parts for l in x.splitlines() if "Invented rule" in l)
                self.assertEqual(card(cand), card(base))
                if facts == 60:
                    self.assertTrue(base[1], "60 facts must spill into part 2, or the split is not exercised")


def stream_lines(result: str = "done", cost: float = 0.01, sid: str = "s1", subtype: str = "success") -> list[str]:
    return [json.dumps({"type": "system", "subtype": "init", "session_id": sid, "model": "claude-sonnet-5-5",
                        "plugins": [{"name": "memcue", "path": "/opt/p601/plugin"}], "claude_code_version": "2.1.312"}),
            json.dumps({"type": "assistant", "message": {"content": [
                {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "memcue search \"lists\""}}]}}),
            json.dumps({"type": "user", "message": {"content": [
                {"type": "tool_result", "tool_use_id": "t1", "content": "no facts"}]}}),
            json.dumps({"type": "result", "subtype": subtype, "is_error": subtype != "success", "result": result,
                        "total_cost_usd": cost, "duration_ms": 1200, "num_turns": 2, "session_id": sid,
                        "usage": {"input_tokens": 10, "output_tokens": 20, "cache_read_input_tokens": 30,
                                  "cache_creation_input_tokens": 40},
                        "modelUsage": {"claude-sonnet-5-5": {"costUSD": cost}}})]


def run_dir(root: Path, phase: str, arm: str, sid: str, repeat: int) -> Path:
    return root / "runs" / phase / arm / sid / f"r{repeat}"


MISSING = object()


def write_capture(d: Path, exit_code: str = "0", turn2: bool = True, facts_after: list | None = None,
                  docker_exit=0) -> None:
    """A capture run as the stand left it: rec/ from the container, run.json from the runner."""
    (d / "rec").mkdir(parents=True)
    meta = {"phase": "capture", "arm": d.parts[-3] if len(d.parts) > 3 else "base", "scenario": "D1", "repeat": 1,
            "image": "sha256:i", "inputs_sha256": "h"}
    if docker_exit is not MISSING:
        meta["docker_exit"] = docker_exit
    (d / "run.json").write_text(json.dumps(meta))
    (d / "rec" / "turn1.jsonl").write_text("\n".join(stream_lines("first")) + "\n")
    if turn2:
        (d / "rec" / "turn2.jsonl").write_text("\n".join(stream_lines("second", sid="s1")) + "\n")
    for snap, facts in (("before", []), ("after1", []), ("after2", facts_after or [])):
        fdir = d / "rec" / f"base-{snap}" / "facts"
        fdir.mkdir(parents=True)
        for f in facts:
            p = fdir / f["id"][:1] / f"{f['id']}.jsonl"
            p.parent.mkdir(exist_ok=True)
            with p.open("a") as fh:
                fh.write(json.dumps(f) + "\n")
    (d / "rec" / "exit").write_text(exit_code + "\n")


class Cost(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_capture_cost_is_the_resumed_turn_not_the_sum(self):
        d = self.root / "run"
        (d / "rec").mkdir(parents=True)
        (d / "rec" / "turn1.jsonl").write_text("\n".join(stream_lines(cost=0.03)) + "\n")
        (d / "rec" / "turn2.jsonl").write_text("\n".join(stream_lines(cost=0.07)) + "\n")
        self.assertAlmostEqual(rec.run_cost(d / "rec"), 0.07, places=6)
        (d / "rec" / "turn2.jsonl").write_text("")  # a second turn that never reported: the first one's cost stays
        self.assertAlmostEqual(rec.run_cost(d / "rec"), 0.03, places=6)
        (d / "rec" / "turn1.jsonl").unlink()
        (d / "rec" / "turn2.jsonl").unlink()
        (d / "rec" / "probe.jsonl").write_text("\n".join(stream_lines(cost=0.02)) + "\n")
        self.assertAlmostEqual(rec.run_cost(d / "rec"), 0.02, places=6)


class Extract(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name) / "run"

    def tearDown(self):
        self.tmp.cleanup()

    FACT = {"id": "01ABC", "version": 1, "created": "2026-11-02T10:00:00Z", "status": "active",
            "content": "The user prefers lists to tables.", "keywords": ["lists"], "origin": "o", "kind": "rule",
            "scope": "global", "source": "user"}

    def test_stream_parse(self):
        self.d.mkdir()
        p = self.d / "s.jsonl"
        p.write_text("\n".join(stream_lines("answer", cost=0.02)) + "\n")
        s = rec.parse_stream(p)
        self.assertEqual((s["result"], s["cost_usd"], s["session_id"]), ("answer", 0.02, "s1"))
        self.assertEqual(s["models"], ["claude-sonnet-5-5"])
        self.assertEqual(s["memcue_calls"][0]["command"], 'memcue search "lists"')
        self.assertEqual(s["memcue_calls"][0]["output"], "no facts")

    def test_stream_without_result_is_an_error(self):
        self.d.mkdir()
        p = self.d / "s.jsonl"
        p.write_text(stream_lines()[0] + "\n")
        with self.assertRaises(rec.ExtractError):
            rec.parse_stream(p)

    def test_missing_stream_is_an_error(self):
        with self.assertRaises(rec.ExtractError):
            rec.parse_stream(self.d / "none.jsonl")

    def test_capture_record_lists_added_facts(self):
        write_capture(self.d, facts_after=[self.FACT])
        sc = {"id": "D1", "kind": "durable", "turn1": "t1", "turn2": "t2"}
        r = rec.capture_record(self.d, sc, {"purpose": "p", "preference": "lists"})
        self.assertEqual(r["record"]["answers"], {"turn1": "first", "turn2": "second"})
        self.assertEqual(len(r["record"]["base_changes"]), 1)
        ch = r["record"]["base_changes"][0]
        self.assertEqual((ch["id"], ch["kind"], ch["scope"], ch["source"], ch["change"]),
                         ("01ABC", "rule", "global", "user", "added"))
        self.assertNotIn("arm", json.dumps(r["record"]))
        self.assertEqual(r["sha256"], rec.record_sha(r["record"]))

    def test_capture_record_of_a_failed_run_is_an_error(self):
        write_capture(self.d, exit_code="1")
        with self.assertRaises(rec.ExtractError):
            rec.capture_record(self.d, {"id": "D1", "kind": "durable", "turn1": "a", "turn2": "b"}, {})

    def test_correction_is_a_change(self):
        f2 = dict(self.FACT, version=2, content="The user prefers bullet lists to tables.")
        before = {"01ABC": [self.FACT]}
        after = {"01ABC": [self.FACT, f2]}
        ch = rec.diff_facts(before, after)
        self.assertEqual([(c["id"], c["change"], c["content"]) for c in ch],
                         [("01ABC", "corrected", "The user prefers bullet lists to tables.")])


class Delivery(unittest.TestCase):
    def hooks(self, note: bool, reminder: bool) -> list[dict]:
        return [{"subtype": "hook_started", "note_end": False, "reminder": False},
                {"subtype": "hook_response", "note_end": note, "reminder": reminder}]

    def test_every_call_must_carry_it(self):
        both = {"turn1": {"hooks": self.hooks(True, True)}, "turn2": {"hooks": self.hooks(True, True)}}
        self.assertEqual(rec.delivery(both), {"note": True, "reminder": True})
        one = {"turn1": {"hooks": self.hooks(True, True)}, "turn2": {"hooks": self.hooks(True, False)}}
        self.assertEqual(rec.delivery(one), {"note": True, "reminder": False})

    def test_no_hook_events_is_not_delivered(self):
        self.assertEqual(rec.delivery({"probe": {"hooks": []}}), {"note": False, "reminder": False})


CAPTURE_OK = {"acknowledged": "yes", "preference_stored": "yes", "preference_fact_ids": ["01ABC"],
              "extra_useful": 0, "noise": 0, "notes": "ok"}
CONTROL_OK = {"acknowledged": "yes", "durable_capture": "no", "time_limited_capture": "no", "extra_useful": 0,
              "noise": 0, "notes": "ok"}
PROBE_OK = {"applied": "yes", "evidence": "no table", "notes": "ok"}


class Grades(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(rec.parse_grade(json.dumps(CAPTURE_OK), "durable")["preference_stored"], "yes")
        self.assertEqual(rec.parse_grade("```json\n" + json.dumps(PROBE_OK) + "\n```", "probe")["applied"], "yes")
        self.assertEqual(rec.parse_grade(json.dumps(CONTROL_OK), "control")["durable_capture"], "no")

    def test_fail_closed(self):
        bad = [
            "",
            "I think it was stored.",
            json.dumps(CAPTURE_OK)[:-5],  # truncated
            json.dumps(dict(CAPTURE_OK, preference_stored="maybe")),
            json.dumps({k: v for k, v in CAPTURE_OK.items() if k != "acknowledged"}),
            json.dumps(dict(CAPTURE_OK, noise=-1)),
            json.dumps(dict(CAPTURE_OK, noise="0")),
            json.dumps(dict(CAPTURE_OK, preference_fact_ids="01ABC")),
            json.dumps([CAPTURE_OK]),
        ]
        for text in bad:
            with self.subTest(text=text[:40]), self.assertRaises(rec.GradeError):
                rec.parse_grade(text, "durable")

    def test_stored_without_ids_is_invalid(self):
        with self.assertRaises(rec.GradeError):
            rec.parse_grade(json.dumps(dict(CAPTURE_OK, preference_fact_ids=[])), "durable")

    def test_unknown_kind(self):
        with self.assertRaises(rec.GradeError):
            rec.parse_grade(json.dumps(PROBE_OK), "other")


FACT_ID = "01ABC"


def record_doc(key: str = "k", answer: str = "second", ids: tuple = (FACT_ID,)) -> dict:
    record = {"scenario": "D1", "kind": "durable", "labels": {}, "prompts": {"turn1": "a", "turn2": "b"},
              "answers": {"turn1": "first", "turn2": answer},
              "base_changes": [{"id": i, "change": "added", "version": 1, "kind": "rule", "scope": "global",
                                "source": "user", "expires": "", "content": "c", "keywords": []} for i in ids],
              "memcue_calls": []}
    return {"key": key, "sha256": rec.record_sha(record), "grade_kind": "durable", "record": record, "meta": {}}


def grade_file(root: Path, pas: str, doc: dict, parsed: dict | None, error: str | None = None,
               raw: str | None = None, docker_exit=0, grader_exit: str = "0", sha: str | None = None) -> None:
    """A saved grade as grade_unit writes it, with the grader's own output in its work directory."""
    work = root / "grading" / pas / f"{doc['key']}-1"
    work.mkdir(parents=True, exist_ok=True)
    text = raw if raw is not None else json.dumps(parsed)
    (work / "out.json").write_text(json.dumps({"type": "result", "subtype": "success", "is_error": False,
                                               "result": text, "total_cost_usd": 0.01}))
    (work / "exit").write_text(grader_exit + "\n")
    (root / "grades" / pas).mkdir(parents=True, exist_ok=True)
    (root / "grades" / pas / f"{doc['key']}.json").write_text(json.dumps({
        "key": doc["key"], "record_sha256": sha or doc["sha256"], "kind": doc["grade_kind"], "parsed": parsed,
        "error": error, "cost_usd": 0.01, "work": str(work.relative_to(root)), "docker_exit": docker_exit}))


class Combine(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.g = Path(self.tmp.name)
        self.doc = record_doc()

    def tearDown(self):
        self.tmp.cleanup()

    def test_agreement_and_dispute(self):
        grade_file(self.g, "A", self.doc, CAPTURE_OK)
        grade_file(self.g, "B", self.doc, dict(CAPTURE_OK, acknowledged="no"))
        c = rec.combined(self.g, self.doc)
        self.assertEqual(c["preference_stored"], "yes")
        self.assertEqual(c["acknowledged"], "disputed")

    def test_missing_pass_is_unknown(self):
        grade_file(self.g, "A", self.doc, CAPTURE_OK)
        self.assertEqual(rec.combined(self.g, self.doc)["preference_stored"], "unknown")

    def test_grade_of_another_content_is_unknown(self):
        grade_file(self.g, "A", self.doc, CAPTURE_OK, sha="old")
        grade_file(self.g, "B", self.doc, CAPTURE_OK)
        self.assertEqual(rec.combined(self.g, self.doc)["preference_stored"], "unknown")

    def test_errored_grade_is_unknown(self):
        grade_file(self.g, "A", self.doc, None, error="not JSON", raw="not JSON")
        grade_file(self.g, "B", self.doc, CAPTURE_OK)
        self.assertEqual(rec.combined(self.g, self.doc)["preference_stored"], "unknown")

    def test_saved_grade_naming_a_nonexistent_fact_is_unknown(self):
        bad = dict(CAPTURE_OK, preference_fact_ids=["01NONEXISTENT"])
        grade_file(self.g, "A", self.doc, bad)
        grade_file(self.g, "B", self.doc, CAPTURE_OK)
        self.assertEqual(rec.combined(self.g, self.doc)["preference_stored"], "unknown")

    def test_saved_label_outside_the_schema_is_unknown(self):
        bad = dict(CAPTURE_OK, preference_stored="not-a-verdict")
        grade_file(self.g, "A", self.doc, bad)
        grade_file(self.g, "B", self.doc, CAPTURE_OK)
        self.assertEqual(rec.combined(self.g, self.doc)["preference_stored"], "unknown")

    def test_saved_parse_that_the_raw_output_does_not_give_is_unknown(self):
        grade_file(self.g, "A", self.doc, CAPTURE_OK, raw=json.dumps(dict(CAPTURE_OK, preference_stored="no",
                                                                         preference_fact_ids=[])))
        grade_file(self.g, "B", self.doc, CAPTURE_OK)
        self.assertEqual(rec.combined(self.g, self.doc)["preference_stored"], "unknown")

    def test_failed_grader_process_is_unknown(self):
        for kw in ({"docker_exit": 9}, {"grader_exit": "9"}, {"docker_exit": "timeout"}):
            with self.subTest(**kw):
                grade_file(self.g, "A", self.doc, CAPTURE_OK, **kw)
                grade_file(self.g, "B", self.doc, CAPTURE_OK)
                self.assertEqual(rec.combined(self.g, self.doc)["preference_stored"], "unknown")

    def test_edited_record_with_the_old_digest_is_rejected(self):
        grade_file(self.g, "A", self.doc, CAPTURE_OK)
        grade_file(self.g, "B", self.doc, CAPTURE_OK)
        forged = json.loads(json.dumps(self.doc))
        forged["record"]["answers"]["turn2"] = "an edited answer"
        with self.assertRaises(rec.RecordError):
            rec.combined(self.g, forged)
        (self.g / "records").mkdir()
        (self.g / "records" / "k.json").write_text(json.dumps(forged))
        with self.assertRaises(rec.RecordError):
            rec.summary(self.g)

    def test_counts_do_not_treat_unknown_as_no(self):
        rows = [{"preference_stored": "yes"}, {"preference_stored": "no"}, {"preference_stored": "unknown"},
                {"preference_stored": "disputed"}]
        self.assertEqual(rec.count(rows, "preference_stored"),
                         {"yes": 1, "no": 1, "unknown": 1, "disputed": 1, "n": 4})



class Aggregate(unittest.TestCase):
    def row(self, **kw):
        base = {"phase": "capture", "arm": "base", "scenario": "D1", "repeat": 1, "kind": "durable",
                "acknowledged": "yes", "preference_stored": "no", "preference_facts": [], "changes": 0,
                "extra_useful": 0, "noise": 0, "cost_usd": 0.1, "seconds": 10.0, "searches": 0,
                "tokens": {"input_tokens": 1, "output_tokens": 2, "cache_read_input_tokens": 3,
                           "cache_creation_input_tokens": 4}, "delivery": {"note": True, "reminder": False}}
        base.update(kw)
        return base

    def test_capture_counts_split_by_acknowledgement(self):
        rows = [self.row(preference_stored="yes", preference_facts=[{"kind": "rule", "scope": "global",
                                                                     "source": "user", "expires": ""}]),
                self.row(acknowledged="no", preference_stored="yes", preference_facts=[
                    {"kind": "", "scope": "example.com/acme/kettles", "source": "agent", "expires": ""}]),
                self.row(acknowledged="unknown", preference_stored="unknown"),
                self.row(arm="cand", preference_stored="disputed")]
        a = rec.aggregate(rows)["capture_durable"]
        self.assertEqual(a["base"]["preference_stored"], {"yes": 2, "unknown": 1, "n": 3})
        self.assertEqual(a["base"]["stored_when_acknowledged"], {"yes": 1, "n": 1})
        self.assertEqual(a["base"]["stored_global"], 1)
        self.assertEqual(a["base"]["stored_rule_user"], 1)
        self.assertEqual(a["cand"]["preference_stored"], {"disputed": 1, "n": 1})

    def test_noise_sums_skip_disputed(self):
        rows = [self.row(noise=2), self.row(noise="disputed"), self.row(noise="unknown")]
        a = rec.aggregate(rows)["capture_durable"]["base"]
        self.assertEqual((a["noise"], a["noise_not_agreed"]), (2, 2))

    def test_probe_split_by_card(self):
        rows = [{"phase": "probe", "arm": "cand", "scenario": "D1", "repeat": 1, "kind": "probe", "applied": "yes",
                 "card_has_preference": True, "capture_preference_stored": "yes", "cost_usd": 0.03, "seconds": 9.0,
                 "searches": 1, "tokens": {}, "delivery": {"note": True, "reminder": True}},
                {"phase": "probe", "arm": "cand", "scenario": "D1", "repeat": 2, "kind": "probe", "applied": "no",
                 "card_has_preference": False, "capture_preference_stored": "no", "cost_usd": 0.03, "seconds": 9.0,
                 "searches": 0, "tokens": {}, "delivery": {"note": True, "reminder": True}}]
        a = rec.aggregate(rows)["probe"]["cand"]
        self.assertEqual(a["applied"], {"yes": 1, "no": 1, "n": 2})
        self.assertEqual(a["applied_when_card_had_it"], {"yes": 1, "n": 1})
        self.assertEqual(a["applied_when_card_lacked_it"], {"no": 1, "n": 1})


class Export(unittest.TestCase):
    def test_public_record_keeps_only_listed_fields(self):
        doc = {"key": "k", "sha256": "h", "grade_kind": "probe", "record": {"answer": "a"},
               "meta": {"phase": "probe", "arm": "cand", "scenario": "D1", "repeat": 1, "seconds": 3.0,
                        "run": "runs/probe/cand/D1/r1", "capture_run": "runs/capture/cand/D1/r1",
                        "preflight.json": "/home/someone/secret", "hook601.log": "x", "container": "c",
                        "card.log": json.dumps({"session": "s", "tier": "t", "facts": ["01A"]}) + "\n",
                        "streams": {"probe": {"cost_usd": 0.1, "usage": {}, "duration_ms": 1, "num_turns": 1,
                                              "session_id": "sid", "models": ["m"], "subtype": "success",
                                              "init": {"model": "m", "plugins": [{"name": "memcue",
                                                                                   "path": "/opt/p601/plugin"}],
                                                       "tools": ["Bash"]},
                                              "memcue_calls": 0, "searches": 0, "tool_calls": ["Read"],
                                              "hooks": []}}}}
        out = rec.public(doc)
        text = json.dumps(out)
        self.assertNotIn("/home/someone", text)
        self.assertNotIn("sid", text)
        self.assertNotIn('"session"', text)
        self.assertEqual(out["meta"]["card_ids"], ["01A"])
        self.assertEqual(out["meta"]["streams"]["probe"]["init"]["plugins"], ["memcue"])
        self.assertEqual(out["record"], {"answer": "a"})


def make_root(root: Path) -> None:
    """A stand root with one durable scenario, its labels and grading template, and a minimal inputs set."""
    (root / "fixtures" / "workspaces" / "w").mkdir(parents=True)
    (root / "fixtures" / "workspaces" / "w" / "f.md").write_text("invented\n")
    (root / "fixtures" / "scenarios.json").write_text(json.dumps({"scenarios": [
        {"id": "D1", "kind": "durable", "workspace": "w", "turn1": "t1", "turn2": "t2",
         "probe": {"workspace": "w", "prompt": "p"}}]}))
    (root / "fixtures" / "labels.json").write_text(json.dumps({"D1": {"purpose": "p", "preference": "lists"}}))
    (root / "fixtures" / "grade_durable.md").write_text("grade this\n{{RECORD}}\n")
    inp = root / "inputs"
    for name in ("memcue", "agent601.sh", "grade601.sh"):
        (inp / name).parent.mkdir(parents=True, exist_ok=True)
        (inp / name).write_text(name)
    for arm in ("base", "cand"):
        (inp / f"plugin-{arm}").mkdir()
        (inp / f"plugin-{arm}" / "hooks.json").write_text(arm)
    files = arch.file_hashes(inp)
    (inp / "manifest.json").write_text(json.dumps({"files": files, "sha256": arch.digest(files)}))


class ExtractRerun(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        make_root(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_source_that_fails_later_loses_its_record(self):
        d = run_dir(self.root, "capture", "base", "D1", 1)
        write_capture(d)
        self.assertEqual(rec.extract(self.root), 0)
        self.assertEqual(len(list((self.root / "records").glob("*.json"))), 1)
        (d / "rec" / "exit").write_text("1\n")
        self.assertNotEqual(rec.extract(self.root), 0)
        live = [x for x in (self.root / "records").glob("*.json") if "." not in x.stem]
        self.assertEqual(live, [])
        self.assertEqual(len(list((self.root / "records").glob("*.stale-*.json"))), 1)  # kept, not deleted
        self.assertEqual(rec.summary(self.root)["rows"], [])


    def test_container_exit_other_than_zero_is_not_extracted(self):
        """rec/exit and the streams look fine, but the runner saw the container fail, time out, or saved nothing."""
        for docker_exit in (9, "timeout", None, "0", True, MISSING):
            with self.subTest(docker_exit=docker_exit):
                shutil.rmtree(self.root / "runs", ignore_errors=True)
                shutil.rmtree(self.root / "records", ignore_errors=True)
                write_capture(run_dir(self.root, "capture", "base", "D1", 1), docker_exit=docker_exit)
                self.assertNotEqual(rec.extract(self.root), 0)
                self.assertEqual(list((self.root / "records").glob("*.json")), [])

    def test_container_exit_zero_is_extracted(self):
        write_capture(run_dir(self.root, "capture", "base", "D1", 1), docker_exit=0)
        self.assertEqual(rec.extract(self.root), 0)

    def test_symlinked_output_is_not_extracted(self):
        d = run_dir(self.root, "capture", "base", "D1", 1)
        write_capture(d)
        victim = self.root / "victim.txt"
        victim.write_text("host file\n")
        (d / "rec" / "turn1.jsonl").unlink()
        (d / "rec" / "turn1.jsonl").symlink_to(victim)
        self.assertNotEqual(rec.extract(self.root), 0)
        self.assertEqual(list((self.root / "records").glob("*.json")), [])


class WriteMeta(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name) / "run"
        self.d.mkdir()
        self.victim = Path(self.tmp.name) / "victim.txt"
        self.victim.write_text("host file\n")

    def tearDown(self):
        self.tmp.cleanup()

    def test_refuses_a_symlink_and_leaves_the_target(self):
        (self.d / "run.json").symlink_to(self.victim)
        with self.assertRaises(rec.TamperError):
            rec.write_meta(self.d, "run.json", "{}")
        self.assertEqual(self.victim.read_text(), "host file\n")

    def test_refuses_a_hard_link(self):
        os.link(self.victim, self.d / "run.json")
        with self.assertRaises(rec.TamperError):
            rec.write_meta(self.d, "run.json", "{}")
        self.assertEqual(self.victim.read_text(), "host file\n")

    def test_replaces_a_regular_file(self):
        (self.d / "run.json").write_text("old")
        rec.write_meta(self.d, "run.json", "new")
        self.assertEqual((self.d / "run.json").read_text(), "new")
        self.assertEqual(sorted(x.name for x in self.d.iterdir()), ["run.json"])


class Archive(unittest.TestCase):
    """archive601.verify recomputes every hash it relies on, from the files, and checks the archive offline."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "root"
        make_root(self.root)
        self.d = run_dir(self.root, "capture", "base", "D1", 1)
        write_capture(self.d)
        man = json.loads((self.root / "inputs" / "manifest.json").read_text())
        meta = json.loads((self.d / "run.json").read_text())
        meta["inputs_sha256"] = man["sha256"]
        (self.d / "run.json").write_text(json.dumps(meta))
        self.frozen = {"inputs_manifest_sha256": man["sha256"], "inputs": {"memcue": man["files"]["memcue"]},
                       "fixtures": {f"fixtures/{k}": v for k, v in arch.file_hashes(self.root / "fixtures").items()}}

    def tearDown(self):
        self.tmp.cleanup()

    def problems(self, expect=None) -> str:
        return " | ".join(arch.verify(self.root, self.frozen, expect)["problems"])

    def test_a_matching_archive_passes(self):
        r = arch.verify(self.root, self.frozen)
        self.assertEqual(r["problems"], [])
        self.assertEqual(r["images"], ["sha256:i"])
        self.assertIn("not inspected", r["image_check"])
        self.assertIn("reconstructed", r["plan"])
        self.assertEqual(arch.verify(self.root, self.frozen, r)["problems"], [])

    def test_a_changed_binary_with_an_updated_file_list_and_the_old_digest_fails(self):
        (self.root / "inputs" / "memcue").write_text("DIFFERENT BINARY")
        man = json.loads((self.root / "inputs" / "manifest.json").read_text())
        man["files"] = arch.file_hashes(self.root / "inputs")  # the forger updates the list, keeps the digest
        (self.root / "inputs" / "manifest.json").write_text(json.dumps(man))
        probs = self.problems()
        self.assertIn("memcue", probs)
        self.assertIn("digest", probs)

    def test_a_changed_file_behind_an_unchanged_manifest_fails(self):
        (self.root / "inputs" / "agent601.sh").write_text("changed")
        self.assertIn("agent601.sh", self.problems())

    def test_a_changed_fixture_or_a_mixed_image_fails(self):
        (self.root / "fixtures" / "labels.json").write_text("{}")
        e = run_dir(self.root, "capture", "cand", "D1", 1)
        write_capture(e)
        meta = json.loads((self.d / "run.json").read_text())
        (e / "run.json").write_text(json.dumps(dict(meta, arm="cand", image="sha256:other")))
        probs = self.problems()
        self.assertIn("fixtures/labels.json", probs)
        self.assertIn("image", probs)

    def test_a_container_that_did_not_exit_zero_fails(self):
        for docker_exit in (9, "timeout", MISSING):
            with self.subTest(docker_exit=docker_exit):
                meta = json.loads((self.d / "run.json").read_text())
                meta.pop("docker_exit", None)
                if docker_exit is not MISSING:
                    meta["docker_exit"] = docker_exit
                (self.d / "run.json").write_text(json.dumps(meta))
                self.assertIn("docker_exit", self.problems())

    def test_a_symlink_in_a_run_fails(self):
        victim = self.root / "victim.txt"
        victim.write_text("x")
        (self.d / "rec" / "turn2.jsonl").unlink()
        (self.d / "rec" / "turn2.jsonl").symlink_to(victim)
        self.assertTrue(self.problems())

    def test_a_published_manifest_that_differs_fails(self):
        r = arch.verify(self.root, self.frozen)
        forged = json.loads(json.dumps(r))
        forged["inputs"]["memcue"] = "0" * 64
        self.assertIn("ARCHIVE_MANIFEST", self.problems(forged))


if __name__ == "__main__":
    unittest.main()
