"""Tests of sessions.py on invented transcripts. Run: TMPDIR=<private scratch> python3 -I test_sessions.py; the
fixtures are written under TMPDIR and removed after each test."""

import json
import os
import sqlite3
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sessions  # noqa: E402

HERE = Path(__file__).resolve().parent
T0 = 1_800_000_000.0  # an invented epoch; every fixture time is relative to it


def iso(ts: float) -> str:
    return sessions.to_iso(ts)


def claude_line(kind: str, text, ts, session="s1", uuid=None, **extra) -> str:
    rec = {"type": kind, "sessionId": session, "uuid": uuid or f"{session}-{ts}-{kind}",
           "message": {"role": kind, "content": text}, **extra}
    if ts is not None:
        rec["timestamp"] = iso(ts)
    return json.dumps(rec)


def hermes_db(path: Path, sessions_rows, messages_rows) -> None:
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE sessions (id TEXT PRIMARY KEY, source TEXT, model_config TEXT, parent_session_id TEXT);
        CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id TEXT, role TEXT, content TEXT, timestamp REAL,
                               active INTEGER, compacted INTEGER);
    """)
    con.executemany("INSERT INTO sessions VALUES (?,?,?,?)", sessions_rows)
    con.executemany("INSERT INTO messages VALUES (?,?,?,?,?,?,?)", messages_rows)
    con.commit()
    con.close()


class Terms(unittest.TestCase):
    def test_lowercase_dedup_stopwords(self):
        self.assertEqual(sessions.terms("The Widget widget and the gizmo-tool v2.1"), ["widget", "gizmo-tool", "v2.1"])

    def test_cyrillic(self):
        self.assertEqual(sessions.terms("Как настроить ШЛЮЗ для виджета"), ["настроить", "шлюз", "виджета"])

    def test_min_match(self):
        self.assertEqual([sessions.min_match(n) for n in range(1, 9)], [1, 2, 2, 2, 3, 3, 4, 4])


class Window(unittest.TestCase):
    def test_bounded_and_centred_on_densest_spot(self):
        text = "alpha " + "x" * 1000 + " widget gizmo " + "y" * 1000
        w = sessions.window(text, ["widget", "gizmo"], 50)
        self.assertIn("widget gizmo", w)
        self.assertLessEqual(len(w), 2 * 50 + 2)

    def test_short_text_whole(self):
        self.assertEqual(sessions.window("a widget here", ["widget"], 50), "a widget here")


class ClaudeParse(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name) / "projects"
        (self.dir / "p").mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, lines):
        (self.dir / "p" / name).write_text("\n".join(lines) + "\n", encoding="utf-8")

    def test_keeps_plain_text_drops_machine_text_and_tools(self):
        self.write("a.jsonl", [
            claude_line("user", "how do I set up the widget gateway", T0),
            claude_line("assistant", [{"type": "thinking", "thinking": "widget gateway secret plan"},
                                      {"type": "text", "text": "The widget gateway listens on port 7000"},
                                      {"type": "tool_use", "name": "Bash", "input": {"command": "widget gateway"}}],
                        T0 + 1),
            claude_line("user", [{"type": "tool_result", "tool_use_id": "x", "content": "widget gateway TOKEN=abc"}],
                        T0 + 2),
            claude_line("user", "<task-notification>widget gateway done</task-notification>", T0 + 3),
            claude_line("user", "Base directory for this skill: /x\nwidget gateway skill body", T0 + 4),
            claude_line("user", "This session is being continued from a previous conversation. widget gateway", T0 + 5),
            claude_line("user", "widget gateway summary", T0 + 6, isCompactSummary=True),
            claude_line("user", "widget gateway meta", T0 + 7, isMeta=True),
            claude_line("user", "<command-name>/widget</command-name> gateway", T0 + 8),
            claude_line("user", "brief: widget gateway", T0 + 9, isSidechain=True),
            json.dumps({"type": "summary", "summary": "widget gateway"}),
        ])
        stats = sessions.Stats()
        msgs = list(sessions.claude_messages(self.dir, include_tool=False, stats=stats))
        texts = sorted(m.text for m in msgs)
        self.assertEqual(texts, ["The widget gateway listens on port 7000", "how do I set up the widget gateway"])
        self.assertGreaterEqual(stats.machine, 7)
        self.assertEqual(stats.tool_skipped, 1)

    def test_strips_embedded_system_reminder(self):
        self.write("a.jsonl", [claude_line("user", "fix the widget<system-reminder>gateway rules</system-reminder>",
                                           T0)])
        msgs = list(sessions.claude_messages(self.dir, include_tool=False, stats=sessions.Stats()))
        self.assertEqual([m.text for m in msgs], ["fix the widget"])

    def test_tool_arm_keeps_tool_output(self):
        self.write("a.jsonl", [claude_line("user", [{"type": "tool_result", "tool_use_id": "x",
                                                      "content": [{"type": "text", "text": "widget output"}]}], T0)])
        msgs = list(sessions.claude_messages(self.dir, include_tool=True, stats=sessions.Stats()))
        self.assertEqual([(m.role, m.text) for m in msgs], [("tool", "widget output")])

    def test_delegated_entrypoint_user_is_brief(self):
        self.write("a.jsonl", [claude_line("user", "widget brief from a parent agent", T0, entrypoint="sdk-cli"),
                               claude_line("assistant", [{"type": "text", "text": "widget answer"}], T0 + 1,
                                           entrypoint="sdk-cli")])
        msgs = list(sessions.claude_messages(self.dir, include_tool=False, stats=sessions.Stats()))
        self.assertEqual([m.text for m in msgs], ["widget answer"])

    def test_bad_lines_missing_time_and_duplicates(self):
        self.write("a.jsonl", ["{not json", "[1,2]", claude_line("user", "widget one", None),
                               claude_line("user", "widget two", T0, uuid="u1")])
        self.write("b.jsonl", [claude_line("user", "widget two", T0, uuid="u1")])  # a resumed copy of the same record
        stats = sessions.Stats()
        msgs = list(sessions.claude_messages(self.dir, include_tool=False, stats=stats))
        self.assertEqual([m.text for m in msgs], ["widget two"])
        self.assertEqual((stats.bad_lines, stats.no_time, stats.duplicates), (2, 1, 1))

    def test_oversized_line_skipped(self):
        self.write("a.jsonl", [claude_line("user", "widget " + "z" * 5000, T0)])
        stats = sessions.Stats()
        msgs = list(sessions.claude_messages(self.dir, include_tool=False, stats=stats, max_line=1000))
        self.assertEqual((msgs, stats.oversized), ([], 1))


class HermesParse(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "state.db"
        hermes_db(self.db, [("i1", "telegram", "{}", None), ("c1", "cron", "{}", None),
                            ("d1", "matrix", json.dumps({"_delegate_from": "i1"}), None),
                            ("k1", "telegram", "{}", "i1")], [
            (1, "i1", "user", "where is the widget gateway", T0, 1, 0),
            (2, "i1", "assistant", "the widget gateway is on port 7000", T0 + 1, 1, 0),
            (3, "i1", "tool", "widget gateway TOKEN=abc", T0 + 2, 1, 0),
            (4, "i1", "user", "[IMPORTANT: Background process done] widget gateway", T0 + 3, 1, 0),
            (5, "i1", "user", "[CONTEXT COMPACTION] widget gateway", T0 + 4, 1, 0),
            (6, "c1", "user", "cron job prompt about the widget gateway", T0 + 5, 1, 0),
            (7, "c1", "assistant", "cron found the widget gateway", T0 + 6, 1, 0),
            (8, "d1", "user", "delegated brief widget gateway", T0 + 7, 1, 0),
            (9, "i1", "user", "rewound widget gateway", T0 + 8, 0, 0),
            (10, "i1", "user", "compacted widget gateway", T0 + 9, 0, 1),
            (11, "i1", "user", '[Replying to: "old widget text"]\n\nwidget gateway again', T0 + 10, 1, 0),
            (12, "i1", "assistant", "", T0 + 11, 1, 0),
            (13, "i1", "user", "[Cron delivery: digest] widget gateway", T0 + 12, 1, 0),
            (14, "i1", "user", "[ASYNC DELEGATION BATCH COMPLETE — d1] widget gateway", T0 + 13, 1, 0),
            (15, "i1", "user", "widget gateway result [INTERNAL NOTIFICATION — not a human]", T0 + 14, 1, 0),
            (16, "i1", "user", "[ASYNC DELEGATION COMPLETE — d2] widget gateway", T0 + 15, 1, 0),
            (17, "i1", "user", "[IMPORTANT: 2 background processes completed.] widget gateway", T0 + 16, 1, 0),
            (18, "i1", "user", "[Your active task list was preserved across compaction] widget gateway", T0 + 17, 1, 0),
        ])

    def tearDown(self):
        self.tmp.cleanup()

    def test_classes(self):
        stats = sessions.Stats()
        msgs = {m.text: m for m in sessions.hermes_messages(self.db, include_tool=False, stats=stats)}
        self.assertEqual(sorted(msgs), ["compacted widget gateway", "cron found the widget gateway",
                                        "the widget gateway is on port 7000", "where is the widget gateway",
                                        "widget gateway again"])
        self.assertEqual(msgs["cron found the widget gateway"].source, "cron")
        self.assertEqual(stats.rewound, 1)
        self.assertEqual(stats.machine, 10)

    def test_tool_arm(self):
        msgs = list(sessions.hermes_messages(self.db, include_tool=True, stats=sessions.Stats()))
        self.assertIn("widget gateway TOKEN=abc", [m.text for m in msgs])

    def test_lineage(self):
        self.assertEqual(sessions.hermes_lineage(self.db, "k1"), ["k1", "i1"])

    def test_schema_error(self):
        bad = Path(self.tmp.name) / "bad.db"
        sqlite3.connect(bad).execute("CREATE TABLE other (x)").connection.close()
        with self.assertRaises(sessions.InputError):
            list(sessions.hermes_messages(bad, include_tool=False, stats=sessions.Stats()))

    def test_db_not_written(self):
        before = (self.db.stat().st_mtime_ns, self.db.read_bytes())
        list(sessions.hermes_messages(self.db, include_tool=True, stats=sessions.Stats()))
        self.assertEqual(before, (self.db.stat().st_mtime_ns, self.db.read_bytes()))
        self.assertFalse(Path(str(self.db) + "-wal").exists())


def msg(text, ts, session="s", role="user", source="interactive", uid=None):
    return sessions.Message(uid or f"{session}:{ts}", session, role, text, ts, source)


class Search(unittest.TestCase):
    def test_strictly_before_and_newest_first(self):
        msgs = [msg("widget gateway old", T0), msg("widget gateway newer", T0 + 10),
                msg("widget gateway at query time", T0 + 20), msg("widget gateway future", T0 + 30)]
        r = sessions.search(msgs, "widget gateway", T0 + 20, set(), k=5, half=100)
        self.assertEqual([w["text"] for w in r["windows"]], ["widget gateway newer", "widget gateway old"])
        self.assertEqual(r["future_rejected"], 2)

    def test_threshold_and_top_k(self):
        msgs = [msg(f"widget gateway {i}", T0 + i) for i in range(8)] + [msg("only widget", T0 + 50)]
        r = sessions.search(msgs, "widget gateway", T0 + 100, set(), k=5, half=100)
        self.assertEqual(r["candidates"], 8)
        self.assertEqual(len(r["windows"]), 5)
        self.assertEqual(r["windows"][0]["text"], "widget gateway 7")

    def test_excluded_session_and_duplicate_text(self):
        msgs = [msg("widget gateway same", T0, session="a"), msg("widget gateway same", T0 + 1, session="b"),
                msg("widget gateway own", T0 + 2, session="own")]
        r = sessions.search(msgs, "widget gateway", T0 + 100, {"own"}, k=5, half=100)
        self.assertEqual(len(r["windows"]), 1)
        self.assertEqual(r["windows"][0]["session"], "b")
        self.assertEqual((r["duplicate_windows"], r["excluded_session"]), (1, 1))

    def test_empty_query(self):
        r = sessions.search([msg("anything", T0)], "the and", T0 + 1, set(), k=5, half=100)
        self.assertEqual((r["terms"], r["windows"]), ([], []))


class Cli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.cdir = self.root / "projects"
        (self.cdir / "p").mkdir(parents=True)
        (self.cdir / "p" / "a.jsonl").write_text(claude_line("user", "widget gateway here", T0) + "\n")
        self.queries = self.root / "queries.jsonl"
        self.queries.write_text(json.dumps({"qid": "q1", "query": "widget gateway", "time": iso(T0 + 5)}) + "\n")

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *args):
        return subprocess.run([sys.executable, "-I", str(HERE / "sessions.py"), *args], capture_output=True,
                              text=True)

    def test_writes_private_results(self):
        out = self.root / "out"
        p = self.run_cli("--queries", str(self.queries), "--claude-dir", str(self.cdir), "--arm", "claude",
                         "--out", str(out))
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(stat.S_IMODE(out.stat().st_mode), 0o700)
        for f in out.iterdir():
            self.assertEqual(stat.S_IMODE(f.stat().st_mode), 0o600, f.name)
        rows = [json.loads(line) for line in (out / "results.jsonl").read_text().splitlines()]
        self.assertEqual([w["text"] for w in rows[0]["windows"]], ["widget gateway here"])
        self.assertNotIn("widget", p.stdout)  # stdout carries counts, not text

    def test_refuses_existing_out_and_aliasing(self):
        out = self.root / "out"
        out.mkdir()
        (out / "x").write_text("keep")
        p = self.run_cli("--queries", str(self.queries), "--claude-dir", str(self.cdir), "--arm", "c", "--out",
                         str(out))
        self.assertNotEqual(p.returncode, 0)
        self.assertEqual((out / "x").read_text(), "keep")
        for bad in (self.cdir / "out", self.cdir):
            p = self.run_cli("--queries", str(self.queries), "--claude-dir", str(self.cdir), "--arm", "c", "--out",
                             str(bad))
            self.assertNotEqual(p.returncode, 0, bad)
        self.assertFalse((self.cdir / "out").exists())

    def test_missing_input_creates_nothing(self):
        out = self.root / "out2"
        p = self.run_cli("--queries", str(self.root / "missing.jsonl"), "--claude-dir", str(self.cdir), "--arm", "c",
                         "--out", str(out))
        self.assertNotEqual(p.returncode, 0)
        self.assertFalse(out.exists())

    def test_invalid_query_rows(self):
        self.queries.write_text(json.dumps({"qid": "q1", "query": "widget"}) + "\n")  # no time
        p = self.run_cli("--queries", str(self.queries), "--claude-dir", str(self.cdir), "--arm", "c", "--out",
                         str(self.root / "out3"))
        self.assertNotEqual(p.returncode, 0)
        self.assertFalse((self.root / "out3").exists())
        self.queries.write_text("")
        p = self.run_cli("--queries", str(self.queries), "--claude-dir", str(self.cdir), "--arm", "c", "--out",
                         str(self.root / "out4"))
        self.assertNotEqual(p.returncode, 0)


class QueryInput(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "q.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def rejects(self, rows):
        self.path.write_text("".join(json.dumps(r) + "\n" for r in rows))
        with self.assertRaises(sessions.InputError):
            sessions.read_queries(self.path)

    def test_non_finite_time(self):
        self.assertIsNone(sessions.parse_time(float("nan")))
        self.assertIsNone(sessions.parse_time(float("inf")))
        self.path.write_text('{"qid": "q", "query": "widget", "time": NaN}\n')
        with self.assertRaises(sessions.InputError):
            sessions.read_queries(self.path)

    def test_duplicate_qid(self):
        self.rejects([{"qid": "q", "query": "widget", "time": T0}, {"qid": "q", "query": "gizmo", "time": T0}])

    def test_exclusions_must_be_a_list_of_strings(self):
        self.rejects([{"qid": "q", "query": "widget", "time": T0, "exclude_sessions": "self"}])
        self.rejects([{"qid": "q", "query": "widget", "time": T0, "exclude_sessions": [1]}])


class HermesStrict(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_reply_wrapper_around_machine_text(self):
        db = self.root / "state.db"
        hermes_db(db, [("i1", "telegram", "{}", None)], [
            (1, "i1", "user", '[Replying to: "quoted"]\n\n[System note: restarted] widget gateway', T0, 1, 0),
            (2, "i1", "user", '[Replying to: "quoted"]\n\n[ASYNC DELEGATION BATCH COMPLETE — d] widget', T0, 1, 0),
            (3, "i1", "user", '[Replying to: "quoted"]\n\nplain widget', T0, 1, 0)])
        msgs = list(sessions.hermes_messages(db, include_tool=False, stats=sessions.Stats()))
        self.assertEqual([m.text for m in msgs], ["plain widget"])

    def test_sessions_without_parent_column(self):
        db = self.root / "state.db"
        con = sqlite3.connect(db)
        con.executescript("""
            CREATE TABLE sessions (id TEXT PRIMARY KEY, source TEXT, model_config TEXT);
            CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id TEXT, role TEXT, content TEXT, timestamp REAL,
                                   active INTEGER, compacted INTEGER);
            INSERT INTO sessions VALUES ('i1', 'telegram', '{}');
            INSERT INTO messages VALUES (1, 'i1', 'user', 'widget gateway', 1800000000.0, 1, 0);""")
        con.close()
        with self.assertRaises(sessions.InputError):
            list(sessions.hermes_messages(db, include_tool=False, stats=sessions.Stats()))
        q = self.root / "q.jsonl"
        q.write_text(json.dumps({"qid": "q", "query": "widget", "time": T0 + 5, "exclude_sessions": ["i1"]}) + "\n")
        p = subprocess.run([sys.executable, "-I", str(HERE / "sessions.py"), "--queries", str(q), "--hermes-db",
                            str(db), "--arm", "h", "--out", str(self.root / "out")], capture_output=True, text=True)
        self.assertNotEqual(p.returncode, 0)
        self.assertFalse((self.root / "out").exists())


FAKE_STATE = "class SessionDB:\n    def __init__(self, **kw): pass\n    def close(self): pass\n"
FAKE_TOOL = '''import json
def session_search(query="", **kw):
    if query == "err":
        return json.dumps({"success": False, "error": "synthetic"})
    if query == "badcount":
        return json.dumps({"success": True, "count": 2, "results": []})
    if query == "none":
        return json.dumps({"success": True, "count": 0, "results": []})
    return json.dumps({"success": True, "count": 2, "results": [
        {"match_message_id": 1, "session_id": "s", "messages": [
            {"id": 1, "role": "user", "content": "past widget", "timestamp": 50.0},
            {"id": 2, "role": "assistant", "content": "later widget", "timestamp": 150.0}],
         "bookend_end": [{"id": 3, "role": "assistant", "content": "no time"}]},
        {"match_message_id": 4, "session_id": "t", "messages": [
            {"id": 4, "role": "user", "content": "future anchor", "timestamp": 120.0}]}]})
'''


class SessionSearchWrapper(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        hr = self.root / "hermes"
        (hr / "tools").mkdir(parents=True)
        (hr / "hermes_state.py").write_text(FAKE_STATE)
        (hr / "tools" / "__init__.py").write_text("")
        (hr / "tools" / "session_search_tool.py").write_text(FAKE_TOOL)
        self.hr = hr
        (self.root / "copy").mkdir()
        self.db = self.root / "copy" / "state.db"
        self.db.write_text("")

    def tearDown(self):
        self.tmp.cleanup()

    def run_wrapper(self, queries, out):
        q = self.root / f"{out}.jsonl"
        q.write_text("".join(json.dumps({"qid": f"q{i}", "query": t, "time": 100.0, "exclude_sessions": ["self"]}) + "\n"
                             for i, t in enumerate(queries)))
        return subprocess.run([sys.executable, "-I", str(HERE / "hermes_session_search.py"), "--hermes-root",
                               str(self.hr), "--db", str(self.db), "--queries", str(q), "--out", str(self.root / out)],
                              capture_output=True, text=True)

    def rows(self, out, name="comparison.jsonl"):
        return [json.loads(line) for line in (self.root / out / name).read_text().splitlines()]

    def test_postfilter_drops_every_message_at_or_after_the_query(self):
        p = self.run_wrapper(["widget"], "o1")
        self.assertEqual(p.returncode, 0, p.stderr)
        row = self.rows("o1")[0]
        self.assertEqual(row["status"], "ok")
        first, second = row["results"]
        self.assertEqual([m["id"] for m in first["kept"]], [1])
        self.assertEqual((first["dropped_after_query"], first["dropped_no_time"]), (1, 1))
        self.assertTrue(second["anchor_after_query"])
        self.assertEqual(second["kept"], [])
        self.assertEqual(row["visible_chars"], len("past widget"))
        self.assertEqual((row["query_time"], len(row["query_sha"])), (sessions.to_iso(100.0), 16))
        raw = self.rows("o1", "responses.jsonl")[0]
        self.assertIn("later widget", raw["raw"])  # the tool's answer is kept as it came

    def test_errors_are_unknown_and_fail_the_run(self):
        p = self.run_wrapper(["err", "badcount", "none"], "o2")
        self.assertNotEqual(p.returncode, 0)
        self.assertEqual([r["status"] for r in self.rows("o2")], ["error", "error", "ok"])

    def test_manifest_records_module_hashes(self):
        self.run_wrapper(["none"], "o3")
        man = json.loads((self.root / "o3" / "manifest.json").read_text())
        self.assertEqual(len(man["modules"]["tools/session_search_tool.py"]), 64)


def window_row(qid, query, ts, windows, arm="parser"):
    import hashlib
    return {"qid": qid, "arm": arm, "query_time": sessions.to_iso(ts),
            "query_sha": hashlib.sha256(query.encode()).hexdigest()[:16], "future_rejected": 0,
            "windows": [{"rank": i + 1, "text": t, "chars": len(t), "ts": sessions.to_iso(ts - 10 - i), "uid": u,
                         "role": "user", "source": "interactive", "session": "s"} for i, (u, t) in enumerate(windows)]}


class Aggregate(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.q = self.root / "q.jsonl"
        self.q.write_text(json.dumps({"qid": "q1", "query": "widget gateway", "time": T0, "stratum": "interactive",
                                      "exclude_sessions": []}) + "\n")
        self.run_dir = self.root / "run"
        self.run_dir.mkdir()
        self.write_run([window_row("q1", "widget gateway", T0, [("h:1", "widget gateway one"),
                                                                 ("h:2", "widget gateway two")])])

    def tearDown(self):
        self.tmp.cleanup()

    def write_run(self, rows):
        (self.run_dir / "results.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))

    def label(self, uid, text, lab="A", seen=None, qid="q1"):
        import hashlib
        iid = hashlib.sha256(f"{qid}\x00{uid}\x00{text}".encode()).hexdigest()[:12]
        return {"iid": iid, "label": lab, "outdated": "none", "machine": False,
                "seen_sha": hashlib.sha256(("  " + (seen if seen is not None else text)).encode()).hexdigest()[:16]}

    def agg(self, labels, *extra):
        lp = self.root / "l.jsonl"
        lp.write_text("".join(json.dumps(r) + "\n" for r in labels))
        return subprocess.run([sys.executable, "-I", str(HERE / "aggregate.py"), "--queries", str(self.q), "--run",
                               f"parser={self.run_dir}", "--labels", str(lp), *extra], capture_output=True, text=True)

    def test_bound_label_counts_and_changed_text_is_unknown(self):
        p = self.agg([self.label("h:1", "widget gateway one"),
                      self.label("h:2", "widget gateway two", seen="widget gateway older text")])
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("| parser | interactive | 1 | 1 | 1/0/0 | 1 | 1 |", p.stdout)

    def test_duplicate_labels_fail(self):
        lab = self.label("h:1", "widget gateway one")
        self.assertNotEqual(self.agg([lab, lab]).returncode, 0)

    def test_results_bound_to_the_query(self):
        row = window_row("q1", "widget gateway", T0, [("h:1", "widget gateway one")])
        for bad in ({"query_sha": "0" * 16}, {"query_time": sessions.to_iso(T0 + 1)}, {"arm": "other"}):
            self.write_run([{**row, **bad}])
            self.assertNotEqual(self.agg([]).returncode, 0, bad)
        self.write_run([row, row])
        self.assertNotEqual(self.agg([]).returncode, 0)
        broken = json.loads(json.dumps(row))
        broken["windows"][0]["chars"] = 999
        self.write_run([broken])
        self.assertNotEqual(self.agg([]).returncode, 0)
        late = json.loads(json.dumps(row))
        late["windows"][0]["ts"] = sessions.to_iso(T0)
        self.write_run([late])
        self.assertNotEqual(self.agg([]).returncode, 0)

    def comparison(self, **over):
        import hashlib
        kept = [{"id": 1, "role": "user", "timestamp": T0 - 5, "content": "widget", "tool_calls": "",
                 "truncated": False}]
        row = {"qid": "q1", "query_sha": hashlib.sha256(b"widget gateway").hexdigest()[:16],
               "query_time": sessions.to_iso(T0), "status": "ok", "count": 1, "response_chars": 100,
               "results": [{"rank": 1, "anchor": 1, "anchor_after_query": False, "kept": kept,
                            "dropped_after_query": 0, "dropped_no_time": 0, "visible_chars": 6}],
               "visible_chars": 6}
        row.update(over)
        ss = self.root / "comparison.jsonl"
        ss.write_text(json.dumps(row) + "\n")
        return self.agg([], "--session-search", str(ss))

    def test_session_search_errors_are_unknown(self):
        p = self.comparison(status="error", error="synthetic", results=[], visible_chars=0)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("| interactive | 1 | 0 | 1 |", p.stdout)

    def test_comparison_bound_to_the_query(self):
        self.assertEqual(self.comparison().returncode, 0, self.comparison().stderr)
        self.assertNotEqual(self.comparison(query_sha="0" * 16).returncode, 0)
        self.assertNotEqual(self.comparison(query_time=sessions.to_iso(T0 + 60)).returncode, 0)
        late = {"rank": 1, "anchor": 1, "anchor_after_query": False, "dropped_after_query": 0, "dropped_no_time": 0,
                "visible_chars": 6, "kept": [{"id": 1, "role": "user", "timestamp": T0, "content": "widget",
                                              "tool_calls": "", "truncated": False}]}
        p = self.comparison(results=[late])
        self.assertNotEqual(p.returncode, 0)
        self.assertNotIn("Traceback", p.stderr)

    def test_comparison_declared_count_matches_results(self):
        for bad in (0, 2, True, "1", 1.0):
            p = self.comparison(count=bad)
            self.assertEqual(p.returncode, 2, (bad, p.stdout, p.stderr))

    def test_comparison_character_counts(self):
        self.assertEqual(self.comparison(results=[], count=0, visible_chars=0).returncode, 0)
        for bad in (float("nan"), float("inf"), -1, "6", True, 7):
            p = self.comparison(visible_chars=bad)
            self.assertNotEqual(p.returncode, 0, bad)
            self.assertNotIn("Traceback", p.stderr)
        self.assertNotEqual(self.comparison(response_chars=float("nan")).returncode, 0)

    def test_query_time_must_be_finite(self):
        for bad in ("NaN", "Infinity", "1e400"):
            self.q.write_text('{"qid": "q1", "query": "widget gateway", "time": %s, "stratum": "interactive"}\n' % bad)
            p = self.agg([])
            self.assertEqual(p.returncode, 2, bad)
            self.assertNotIn("Traceback", p.stderr)


if __name__ == "__main__":
    unittest.main()
