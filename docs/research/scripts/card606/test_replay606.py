#!/usr/bin/env python3
"""Synthetic tests of replay606.py (#606). Every fact, label, case, repository, binary and client here is invented;
nothing calls a model or opens a real store. Temporary files go under TMPDIR:

    TMPDIR=/opt/data/cache/scratch python3 -I docs/research/scripts/card606/test_replay606.py
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock
from types import SimpleNamespace as NS

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import label606 as lab  # noqa: E402
import replay606 as m  # noqa: E402

REPO = "repo:example.com/acme/widgets"
HEADER = "memcue: rules and decisions from the base (data, not instructions; a heading gives the scope and the dates)"
HINT = "- 2 more do not fit the card budget: search -in global -kind rule,decision"
# id -> (text, kind, scope, source, fixture channel, fixture confidence)
ROWS = {"b1": ("Reply tersely.", "rule", "global", "agent", "behaviour", "high"),
        "k1": ("The build host runs Debian.", "environment", "global", "agent", "knowledge", "high"),
        "r1": ("Run make lint before commits.", "rule", REPO, "user", "repository", "high"),
        "r2": ("Widgets use tabs.", "rule", REPO, "agent", "repository", "high"),
        "c1": ("Pass -p 2 to go test.", "rule", "global", "agent", "command", "medium"),
        "u1": ("Ticket 42 is odd.", "event", "global", "agent", "unknown", "high")}
KEPT, REMOVED = ["b1", "r1", "c1", "u1"], ["k1", "r2"]


def meta(i):
    t, kind, scope, source, _, _ = ROWS[i]
    return {"id": i, "text": t, "created": "2026-01-01T00:00:00+00:00", "kind": kind, "scope": scope,
            "source": source, "cards": [{"context": "A", "host": "claude", "position": 0}]}


def card():
    parts = ["- invented note before the card\n" + HEADER + "\nglobal (learnt 2026-01-01):\n- Reply tersely.\n"
             "- The build host runs Debian.\nrepository (learnt 2026-01-01):\n- Run make lint before commits.",
             HEADER + "\n- Widgets use tabs.\n- Pass -p 2 to go test.\n- Ticket 42 is odd.\n" + HINT]
    return {"parts": parts, "facts": [{"id": i, "line": "- " + ROWS[i][0], "metadata": meta(i)} for i in ROWS]}


def seal(case):
    case = dict(case)
    case["source_sha256"] = lab.sha(lab.canon({k: v for k, v in case.items() if k not in ("case_id", "source_sha256")}))
    return case


def reply(content=None, tool_calls=None, finish="stop", usage=(10, 5)):
    msg = NS(content=content, tool_calls=tool_calls)
    return NS(choices=[NS(message=msg, finish_reason=finish)], model="fake",
              usage=NS(prompt_tokens=usage[0], completion_tokens=usage[1], total_tokens=sum(usage)))


def call(name, args, i=0):
    return NS(id=f"call-{i}", type="function", function=NS(name=name, arguments=args if isinstance(args, str)
                                                                   else json.dumps(args)))


class FakeLabeler:
    def __init__(self):
        self.chat = NS(completions=NS(create=self.create))

    def create(self, **kw):
        facts = json.loads(kw["messages"][1]["content"])["facts"]
        cal = {r["id"]: r["expect"] for r in lab.CALIBRATION}
        out = [{"id": f["id"], "channel": cal.get(f["id"]) or ROWS[f["id"]][4], "programs": [], "reason": "fixture",
                "confidence": "high" if f["id"] in cal else ROWS[f["id"]][5]} for f in facts]
        return reply(json.dumps({"labels": out}))

    def close(self):
        pass


class FakeClient:
    """Answers with the number of fact lines its card shows after one memory_search; judges for the fewer lines."""

    def __init__(self, judge=None, answer=None, bad_grader=False):
        self.chat = NS(completions=NS(create=self.create))
        self.calls, self.closed, self.judge, self.answer, self.bad = [], False, judge, answer, bad_grader

    def create(self, **kw):
        self.calls.append(kw)
        msgs = kw["messages"]
        if "tools" not in kw:
            doc = json.loads(msgs[-1]["content"])
            for c in m.JUDGE_CALIBRATION:
                if c["prompt"] == doc["prompt"]:
                    right = {"second": c["second"], "first": c["first"]}.get(c["expect"][0])
                    w = "tie" if right is None else "first" if doc["first"]["answer"] == right else "second"
                    return reply(self.verdict("first" if self.bad else w, "high"))
            if self.judge:
                return reply(self.judge(doc))
            n = [int(doc[k]["answer"].split()[-1]) for k in ("first", "second")]
            return reply(self.verdict("first" if n[0] < n[1] else "second", "high"))
        if self.answer:
            return self.answer(msgs)
        if msgs[-1]["role"] != "tool":
            return reply(None, [call("memory_search", {"query": "lint", "in": "all", "limit": 2})], "tool_calls")
        lines = sum(1 for p in msgs[0]["content"].split("\n") if p.startswith("- "))
        return reply(f"Plan: card lines {lines}")

    @staticmethod
    def verdict(winner, conf):
        s = {"first": (2, 1), "second": (1, 2), "tie": (1, 1), "unknown": (0, 0)}[winner]
        return json.dumps({"winner": winner, "first_score": s[0], "second_score": s[1], "confidence": conf,
                           "reason": "fixture"})

    def close(self):
        self.closed = True


FAKE_BINARY = """#!{py}
import json, os, sys
with open(os.path.join(os.environ["MEMCUE_STATE_DIR"], "argv.jsonl"), "a") as f:
    f.write(json.dumps({{"argv": sys.argv[1:], "facts": os.environ["MEMCUE_FACTS"], "host": os.environ["MEMCUE_HOST"]}}) + "\\n")
q = sys.argv[-1]
if q == "boom":
    sys.exit(1)
if q == "hang":
    import signal
    signal.pause()
print({{"shape": '{{"oops": 1}}', "bare": '[{{"id": "x1", "content": "invented"}}]', "miss": '{{"facts": []}}',
       "token": '{{"facts": [{{"id": "x2", "content": "sk-' + 'Zq9x' * 8 + '"}}]}}'}}.get(q,
      '{{"facts": [{{"id": "x1", "content": "invented hit"}}], "hints": ["invented hint"]}}'))
"""


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def git_repo(self, name):
        r = self.d / name
        (r / "src").mkdir(parents=True)
        (r / "src" / "app.py").write_text("print('invented')\n" * 1000)
        (r / "bin.dat").write_bytes(b"\xff\xfe")
        (r / ".env").write_text("X=1\n")
        os.symlink("/etc/hostname", r / "link.py")
        (r / "docs").mkdir()
        (r / "docs" / "a.md").write_text("tracked\n")
        env = {"PATH": os.environ["PATH"], "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull}
        for cmd in (["init", "-q"], ["add", "src/app.py", "bin.dat", ".env", "link.py", "docs/a.md"]):
            subprocess.run(["git", "-C", str(r)] + cmd, check=True, env=env)
        (r / "untracked.txt").write_text("u\n")
        outside = self.d / f"outside-{name}"  # a tracked directory swapped for a link after git listed it
        outside.mkdir()
        (outside / "a.md").write_text("outside\n")
        (r / "docs" / "a.md").unlink()
        (r / "docs").rmdir()
        os.symlink(outside, r / "docs")
        return r

    def labels_dir(self):
        rows = self.d / "rows.json"
        rows.write_text(json.dumps([meta(i) for i in ROWS]))
        out = self.d / "labels"
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(lab.main(["--in", str(rows), "--out", str(out)], lambda: (FakeLabeler(), lab.MODEL)), 0)
        return out

    def tools(self, repo=None):
        binary = self.d / "memcue"
        binary.write_text(FAKE_BINARY.format(py=sys.executable))
        binary.chmod(0o700)
        state = self.d / "state"
        state.mkdir(exist_ok=True)
        env = {"PATH": os.environ["PATH"], "MEMCUE_STATE_DIR": str(state), "MEMCUE_FACTS": "/invented/facts",
               "MEMCUE_HOST": "invented-host"}
        repos = {"A": str(repo)} if repo else {}
        return m.Tools(str(binary), env, {"A": str(repo or self.d), "G": str(self.d)}, repos,
                       {k: m.tracked_files(v) for k, v in repos.items()}), state


class Trim(unittest.TestCase):
    def test_subset_keeps_text_order_notes_headings_and_hint(self):
        c = card()
        labels = {i: {"channel": ROWS[i][4], "confidence": ROWS[i][5]} for i in ROWS}
        kept = [f["id"] for f in c["facts"] if m.keeps(f["metadata"], labels[f["id"]])]
        self.assertEqual(kept, KEPT)
        got = m.trim(c["parts"], c["facts"], set(kept))
        want = [p.replace("\n- The build host runs Debian.", "").replace("\n- Widgets use tabs.", "")
                for p in c["parts"]]
        self.assertEqual(got, want)

    def test_mismatch_fails(self):
        for edit in (lambda c: c["facts"].reverse(), lambda c: c["facts"].pop(),
                     lambda c: c["parts"].__setitem__(1, c["parts"][1].replace(HEADER, "other header"))):
            c = card()
            edit(c)
            with self.assertRaises(m.InputError):
                m.trim(c["parts"], c["facts"], set())


class Bindings(Base):
    def plan(self, cards=None):
        return m.plan_cards(cards or {"A": card()}, m.load_labels(self.d / "labels"))

    def test_plan_from_bound_labels(self):
        self.labels_dir()
        p = self.plan()["A"]
        self.assertEqual((p["kept"], p["removed"]), (KEPT, REMOVED))
        self.assertEqual(p["chars"]["baseline"] - p["chars"]["candidate"], sum(len(ROWS[i][0]) + 3 for i in REMOVED))

    def rewrite(self, name, fn):
        p = self.d / "labels" / name
        recs = [json.loads(x) for x in p.read_text().splitlines()]
        p.write_text("".join(json.dumps(r) + "\n" for r in fn(recs)))

    def test_tampered_stale_or_incomplete_labels_refused(self):
        def set_channel(rs):
            rs[0]["channel"] = "outdated"
            return rs

        def set_content(rs):
            rs[-1]["content"] = rs[-1]["content"].replace("knowledge", "behaviour")
            return rs

        def set_failed(rs):
            rs[0]["failed_batches"] = 1
            return rs
        for name, fn in (("labels.jsonl", set_channel), ("responses.jsonl", set_content),
                         ("labels.jsonl", lambda rs: rs[:-1]), ("summary.json", set_failed)):
            with self.subTest(name=name):
                self.tearDown(); self.setUp()  # noqa: E702
                self.labels_dir()
                self.rewrite(name, fn)
                with self.assertRaises(m.InputError):
                    self.plan()
        c = card()
        c["facts"][1]["metadata"]["text"] = "edited after labelling"
        with self.assertRaises(m.InputError):
            self.plan({"A": c})

    def test_calibration_and_every_label_field_rechecked(self):
        def field(k, v, at=0):
            def fn(rs):
                rs[at][k] = v
                return rs
            return fn

        def forged_failed_calibration(_):  # a wrong calibration channel, rehashed everywhere; summary still passed
            def resp(rs):
                doc = json.loads(rs[0]["content"])
                doc["labels"][0]["channel"] = "knowledge"
                rs[0]["content"] = json.dumps(doc)
                rs[0]["response_sha256"] = lab.sha(rs[0]["content"])
                return rs
            self.rewrite("responses.jsonl", resp)
            h = json.loads((self.d / "labels" / "responses.jsonl").read_text().splitlines()[0])["response_sha256"]
            self.rewrite("calibration.jsonl", lambda rs: [{**r, "response_sha256": h, "channel": "knowledge"}
                                                          if i == 0 else {**r, "response_sha256": h}
                                                          for i, r in enumerate(rs)])
            return None
        for name, fn in (("labels.jsonl", field("reason", "edited")), ("labels.jsonl", field("programs", ["rm"])),
                         ("calibration.jsonl", field("reason", "edited")), ("calibration.jsonl", lambda rs: rs[1:]),
                         ("calibration.jsonl", field("channel", "knowledge")),
                         ("calibration.jsonl", field("expect", "knowledge")), (None, forged_failed_calibration)):
            with self.subTest(name=name, fn=fn):
                self.tearDown(); self.setUp()  # noqa: E702
                self.labels_dir()
                self.plan()
                if name:
                    self.rewrite(name, fn)
                else:
                    fn(None)
                with self.assertRaises(m.InputError):
                    self.plan()

    def test_line_must_be_the_clipped_text(self):
        self.assertEqual(m.clip("a \t b\u00a0\u3000c\x1cd\n"), "a b c\x1cd")
        self.assertEqual(m.clip("é" * 400), "é" * 400)
        self.assertEqual(m.clip("é" * 401), "é" * 400 + "…")
        self.labels_dir()
        c = card()  # the line and the part forged together, the metadata left bound
        c["facts"][1]["line"] = "- The build host runs Ubuntu."
        c["parts"] = [x.replace("runs Debian.", "runs Ubuntu.") for x in c["parts"]]
        with self.assertRaises(m.InputError):
            self.plan({"A": c})


class ToolCalls(Base):
    def test_memory_search_errors_are_not_misses(self):
        t, state = self.tools()
        ok, rec = t.call("A", "memory_search", json.dumps({"query": "lint", "in": "project", "limit": 3}))
        self.assertEqual(json.loads(ok), {"facts": [{"id": "x1", "content": "invented hit"}], "hints": ["invented hint"]})
        argv = json.loads((state / "argv.jsonl").read_text().splitlines()[0])
        self.assertEqual(argv["argv"], ["search", "-json", "-n", "3", "-cwd", t.cwds["A"], "-in", "project", "--",
                                        "lint"])
        self.assertEqual(json.loads(t.call("A", "memory_search", '{"query": "miss", "in": "all"}')[0]), {"facts": []})
        self.assertEqual(len(json.loads(t.call("A", "memory_search", '{"query": "bare", "in": "all"}')[0])["facts"]), 1)
        for q in ("boom", "shape", "token"):
            text, rec = t.call("A", "memory_search", json.dumps({"query": q, "in": "all"}))
            self.assertTrue(text.startswith("error:"), text)
            self.assertNotIn("Zq9x", text)
        before = len((state / "argv.jsonl").read_text().splitlines())
        for name, args in (("shell", "{}"), ("memory_search", "not json"), ("memory_search", '{"query": "x"}'),
                           ("memory_search", '{"query": "x", "in": "everywhere"}'),
                           ("memory_search", '{"query": "x", "in": "all", "limit": 6}'),
                           ("memory_search", '{"query": "x", "in": "all", "rm": 1}')):
            self.assertTrue(t.call("A", name, args)[0].startswith("error:"), (name, args))
        self.assertEqual(len((state / "argv.jsonl").read_text().splitlines()), before)

    def test_read_repository_file_guard(self):
        t, _ = self.tools(self.git_repo("widgets"))
        text, _ = t.call("A", "read_repository_file", '{"path": "src/app.py"}')
        self.assertTrue(text.startswith("print('invented')"))
        self.assertIn("[truncated: first 6000 of 18000 characters]", text)
        for p in ("../widgets/src/app.py", "/etc/hostname", ".git/config", ".env", "untracked.txt", "link.py",
                  "bin.dat", "src/./app.py", "src", "docs/a.md"):
            self.assertTrue(t.call("A", "read_repository_file", json.dumps({"path": p}))[0].startswith("error:"), p)
        self.assertEqual(t.call("G", "read_repository_file", '{"path": "src/app.py"}')[0], m.NO_REPO)


class Arms(Base):
    CASE = {"case_id": "case-1", "context": "A", "prompt": "How do I lint?", "timestamp": "2026-01-02T00:00:00+00:00",
            "history": [{"role": "user", "content": "hi"}, {"role": "user", "content": "again"},
                        {"role": "assistant", "content": "hello"}],
            "source_message": "msg-1", "source_session": "sess-1", "source_sha256": ""}
    CASE = seal(CASE)

    def test_one_system_message_merged_history_and_ok(self):
        t, _ = self.tools()
        c = FakeClient()
        rec = m.run_arm(c, lab.MODEL, self.CASE, ["PART ONE", "PART TWO"], t)
        self.assertEqual((rec["status"], rec["model_calls"], rec["tool_calls"]), ("ok", 2, 1))
        msgs = c.calls[0]["messages"]
        self.assertEqual([x["role"] for x in msgs], ["system", "user", "assistant", "user"])
        self.assertIn("PART ONE\n\nPART TWO", msgs[0]["content"])
        self.assertEqual((msgs[1]["content"], msgs[3]["content"]), ("hi\n\nagain", "How do I lint?"))
        self.assertEqual(rec["turns"][0]["request_sha256"], lab.sha(lab.canon(c.calls[0])))
        case = seal({**self.CASE, "timestamp": "2026-01-02T03:00:00+03:00"})
        before = json.dumps(case)
        m.run_arm(FakeClient(), lab.MODEL, case, ["P"], t)
        self.assertEqual(json.dumps(case), before)
        self.assertEqual((m.iso_utc(case["timestamp"]), m.iso_utc(86400.5)),
                         ("2026-01-02T00:00:00+00:00", "1970-01-02T00:00:00.500000+00:00"))

    def test_policy_is_a_frozen_card_counterfactual(self):
        for text in (m.POLICY, m.JUDGE):
            self.assertNotIn("checked anything", text)
            self.assertNotIn("ran, changed or checked", text)
        self.assertIn("counterfactual", m.POLICY)
        self.assertNotIn("given at its start", m.POLICY)
        for text in (m.POLICY, m.JUDGE):
            self.assertIn("tool output", text)

    def test_caps_and_unfinished_replies_are_errors(self):
        t, state = self.tools()
        many = [call("memory_search", {"query": f"q{i}", "in": "all"}, i) for i in range(3)]
        cases = {"turn limit": lambda msgs: reply(None, many, "tool_calls"),
                 "finish": lambda msgs: reply("half", None, "length"),
                 "empty": lambda msgs: reply("  ", None, "stop"),
                 "tool finish": lambda msgs: reply("x", many[:1], "stop")}
        for name, fn in cases.items():
            with self.subTest(name=name):
                rec = m.run_arm(FakeClient(answer=fn), lab.MODEL, self.CASE, ["P"], t)
                self.assertEqual(rec["status"], "error")
                self.assertIsNone(rec["answer"])
        rec = m.run_arm(FakeClient(answer=cases["turn limit"]), lab.MODEL, self.CASE, ["P"], t)
        self.assertEqual((rec["model_calls"], rec["tool_calls"]), (5, 12))
        self.assertTrue(all(x["result"].startswith("error: tool call limit") for x in rec["tools"][12:]))


    def test_tool_failures_end_the_arm(self):
        t, _ = self.tools()

        def search_then_answer(q, n=1):
            return lambda msgs: (reply("Plan: done") if msgs[-1]["role"] == "tool" else reply(None, [
                call("memory_search", {"query": q, "in": "all"}, i) for i in range(n)], "tool_calls"))
        with mock.patch.object(m, "SEARCH_TIMEOUT", 0.5, create=True):
            for q, cause in (("boom", "memory_search failed (exit 1)"), ("shape", "unexpected shape"),
                             ("hang", "memory_search timed out"), ("lint", "tool call limit (12) reached")):
                with self.subTest(q=q):
                    c = FakeClient(answer=search_then_answer(q, 13 if q == "lint" else 1))
                    rec = m.run_arm(c, lab.MODEL, self.CASE, ["P"], t)
                    self.assertEqual((rec["status"], rec["answer"], len(c.calls)), ("error", None, 1))
                    self.assertIn(cause, rec["error"])
        rec = m.run_arm(FakeClient(answer=search_then_answer("lint", 12)), lab.MODEL, self.CASE, ["P"], t)
        self.assertEqual((rec["status"], rec["tool_calls"], rec["model_calls"]), ("ok", 12, 2))
        no_repo = lambda msgs: (reply("Plan: read nothing") if msgs[-1]["role"] == "tool" else  # noqa: E731
                                reply(None, [call("read_repository_file", {"path": "src/app.py"})], "tool_calls"))
        rec = m.run_arm(FakeClient(answer=no_repo), lab.MODEL, self.CASE, ["P"], t)
        self.assertEqual((rec["status"], rec["tools"][0]["result"]), ("ok", m.NO_REPO))


class Verdicts(unittest.TestCase):
    def test_reverse_mapping_and_strictness(self):
        v = json.loads(FakeClient.verdict("first", "low"))
        self.assertEqual(m.relative(m.parse_verdict(json.dumps(v)), candidate_first=True), "win")
        self.assertEqual(m.relative(m.parse_verdict(json.dumps(v)), candidate_first=False), "loss")
        for bad in ({**v, "first_score": 0}, {**v, "winner": "both"}, {**v, "first_score": True}, {**v, "x": 1},
                    {**v, "reason": "r" * 301}):
            with self.assertRaises(lab.ReplyError):
                m.parse_verdict(json.dumps(bad))


class Tokens(unittest.TestCase):
    def test_missing_or_bogus_usage_is_never_zero(self):
        good = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
        self.assertEqual(m.tokens([good, good])["total_tokens"], {"known": 30, "missing": 0, "total": 30})
        for bad in (None, True, float("nan"), float("inf"), -1, 2.0):
            with self.subTest(bad=bad):
                t = m.tokens([good, {**good, "total_tokens": bad}, None])
                self.assertEqual(t["total_tokens"], {"known": 15, "missing": 2, "total": None})
                self.assertEqual(t["prompt_tokens"], {"known": 20, "missing": 1, "total": None})
                self.assertEqual(t["calls"], 3)


class Main(Base):
    def run_main(self, client_fn, tamper=None):
        repos = {k: self.git_repo(f"repo{k}") for k in "ABC"}
        self.labels_dir()
        cases = [seal({**Arms.CASE, "case_id": f"case-{k}", "context": k}) for k in "ABCG"]
        if tamper:
            tamper(cases)
        (self.d / "cases.json").write_text(json.dumps(cases))
        (self.d / "cards.json").write_text(json.dumps({k: card() for k in "ABCG"}))
        (self.d / "facts").mkdir()
        (self.d / "facts" / "f.md").write_text("invented\n")
        t, _ = self.tools()
        argv = ["--cases", str(self.d / "cases.json"), "--cards", str(self.d / "cards.json"), "--labels",
                str(self.d / "labels"), "--facts", str(self.d / "facts"), "--binary", t.binary, "--host", "inv-host",
                "--out", str(self.d / "out")] + [x for k, r in repos.items() for x in ("--repo", f"{k}={r}")]
        clients = []

        def factory():
            clients.append(client_fn())
            return clients[-1], lab.MODEL
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = m.main(argv, factory)
        return code, buf.getvalue(), clients

    def test_pairs_blind_judge_and_summary(self):
        code, out, clients = self.run_main(FakeClient)
        self.assertEqual(code, 0)
        s = json.loads(out)
        self.assertEqual((s["complete_pairs"], s["error_pairs"]), (4, 0))
        self.assertEqual(s["candidate"], {"win": 4, "tie": 0, "loss": 0, "unknown": 0})
        self.assertEqual((s["worse"], s["low_confidence"]["win"]), (0, 0))
        self.assertTrue(all(c.closed for c in clients))
        self.assertNotIn("case-", out)
        firsts = [json.loads(x)["candidate_first"] for x in (self.d / "out" / "judge.jsonl").read_text().splitlines()]
        self.assertEqual(set(firsts), {True, False})
        self.assertEqual(oct((self.d / "out").stat().st_mode & 0o777), "0o700")
        for f in (self.d / "out").iterdir():
            if f.is_file():
                self.assertEqual(oct(f.stat().st_mode & 0o777), "0o600", f.name)
        argv = json.loads((self.d / "out" / "state" / "argv.jsonl").read_text().splitlines()[0])
        self.assertEqual((argv["facts"], argv["host"]), (str(self.d / "out" / "facts"), "inv-host"))

    def test_low_confidence_and_unknown_kept_apart(self):
        verdicts = iter([FakeClient.verdict("first", "low"), "not json", FakeClient.verdict("tie", "high"),
                         FakeClient.verdict("second", "low")])
        code, out, _ = self.run_main(lambda: FakeClient(judge=lambda doc: next(verdicts)))
        s = json.loads(out)
        self.assertEqual(code, 1)
        self.assertEqual(sum(s["candidate"].values()), 4)
        self.assertEqual((s["candidate"]["unknown"], s["candidate"]["tie"], s["judge_errors"]), (1, 1, 1))
        self.assertEqual(s["low_confidence"]["win"] + s["low_confidence"]["loss"], 2)
        self.assertEqual(s["conclusive"], {"win": 0, "loss": 0})

    def real_judge_calls(self, clients):
        prompts = {c["prompt"] for c in m.JUDGE_CALIBRATION}
        return [k for c in clients for k in c.calls
                if "tools" not in k and json.loads(k["messages"][-1]["content"])["prompt"] not in prompts]

    def test_failed_tools_make_the_pair_unknown_and_unjudged(self):
        def budget(msgs):  # thirteen calls in one turn, then a finished answer
            if msgs[-1]["role"] == "tool":
                return reply("Plan: card lines 1")
            return reply(None, [call("memory_search", {"query": "lint", "in": "all"}, i) for i in range(13)],
                         "tool_calls")
        code, out, clients = self.run_main(lambda: FakeClient(answer=budget))
        s = json.loads(out)
        self.assertEqual((code, s["complete_pairs"], s["error_pairs"], s["judge_errors"]), (1, 0, 4, 0))
        self.assertEqual(s["candidate"], {"win": 0, "tie": 0, "loss": 0, "unknown": 4})
        self.assertEqual(self.real_judge_calls(clients), [])
        runs = [json.loads(x) for x in (self.d / "out" / "runs.jsonl").read_text().splitlines()]
        self.assertEqual({r["error"] for r in runs}, {"tool call limit (12) reached; answer now"})

    def test_search_timeout_makes_only_its_pair_unknown(self):
        hung, lock = [], threading.Lock()

        def answer(msgs):  # the first arm to search hangs the binary; every other arm searches normally
            if msgs[-1]["role"] == "tool":
                lines = sum(1 for p in msgs[0]["content"].split("\n") if p.startswith("- "))
                return reply(f"Plan: card lines {lines}")
            with lock:
                q = "lint" if hung else "hang"
                hung.append(q)
            return reply(None, [call("memory_search", {"query": q, "in": "all"})], "tool_calls")
        with mock.patch.object(m, "SEARCH_TIMEOUT", 0.5, create=True):
            code, out, clients = self.run_main(lambda: FakeClient(answer=answer))
        s = json.loads(out)
        self.assertEqual((code, s["complete_pairs"], s["error_pairs"], s["judge_errors"]), (1, 3, 1, 0))
        self.assertEqual(s["candidate"], {"win": 3, "tie": 0, "loss": 0, "unknown": 1})
        self.assertEqual(len(self.real_judge_calls(clients)), 3)
        runs = [json.loads(x) for x in (self.d / "out" / "runs.jsonl").read_text().splitlines()]
        self.assertEqual([r["error"] for r in runs if r["status"] != "ok"], ["memory_search timed out"])
        judged = [json.loads(x) for x in (self.d / "out" / "judge.jsonl").read_text().splitlines()]
        self.assertEqual([j["error"] for j in judged if j["result"] == "unknown"], ["incomplete pair"])

    def test_bad_grader_stops_before_real_cases(self):
        code, out, clients = self.run_main(lambda: FakeClient(bad_grader=True))
        self.assertEqual((code, json.loads(out)["calibration"]), (3, "failed"))
        prompts = {c["prompt"] for c in m.JUDGE_CALIBRATION}
        sent = [json.loads(k["messages"][-1]["content"])["prompt"] for c in clients for k in c.calls]
        self.assertTrue(sent and set(sent) <= prompts)
        self.assertTrue(all(c.closed for c in clients))

    def test_refusals_before_output(self):
        repos = {k: self.git_repo(f"repo{k}") for k in "ABC"}
        cases = [seal({**Arms.CASE, "prompt": "key " + "ghp_" + "a1B2" * 9})]
        (self.d / "cases.json").write_text(json.dumps(cases))
        with self.assertRaises(m.InputError) as e:
            m.check_cases(m.read_json(self.d / "cases.json"))
        self.assertNotIn("a1B2", str(e.exception))
        with self.assertRaises(m.InputError):
            m.check_cases([Arms.CASE, Arms.CASE])
        with self.assertRaises(m.InputError):
            m.check_out(str(repos["A"] / "out"), [str(r) for r in repos.values()])

    def test_timestamps_and_source_hash(self):
        for ts in ("2026-01-02T00:00:00Z", "2026-01-02T03:00:00+03:00", 1767312000, 1767312000.25):
            m.check_cases([seal({**Arms.CASE, "timestamp": ts})])
        for ts in (True, float("nan"), float("inf"), -1, 1e20, "2026-01-02T00:00:00", "yesterday", None):
            with self.subTest(ts=ts), self.assertRaises(m.InputError):
                m.check_cases([seal({**Arms.CASE, "timestamp": ts})])
        for k, v in (("prompt", "edited"), ("context", "B"), ("timestamp", "2026-01-03T00:00:00+00:00"),
                     ("history", []), ("source_sha256", "a" * 64)):
            with self.subTest(k=k), self.assertRaises(m.InputError):
                m.check_cases([{**Arms.CASE, k: v}])

    def test_stale_case_hash_refused_before_output_and_client(self):
        code, _, clients = self.run_main(FakeClient, tamper=lambda cs: cs[0].update(prompt="edited later"))
        self.assertEqual((code, clients, (self.d / "out").exists()), (2, [], False))


if __name__ == "__main__":
    unittest.main()
