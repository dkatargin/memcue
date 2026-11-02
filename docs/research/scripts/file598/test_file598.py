#!/usr/bin/env python3
"""Synthetic tests of file598.py (#598). Every fact, path, repository and session here is invented; nothing opens a
live base, a real transcript or a real state.db.

    python3 -I docs/research/scripts/file598/test_file598.py
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import file598 as m  # noqa: E402

APP = "example.com/team/app"
OTHER = "example.com/team/other"


def at(day: str, hour: int = 12) -> datetime:
    return datetime.fromisoformat(f"{day}T{hour:02d}:00:00+00:00")


def version(fid: str, n: int, created: str, content: str, status: str = "active", scope: str = "",
            origin: str = "", expires: str = "") -> dict:
    v = {"id": fid, "version": n, "created": created, "status": status, "content": content}
    for k, val in (("scope", scope), ("origin", origin), ("expires", expires)):
        if val:
            v[k] = val
    return v


class FakeResolver:
    """Maps directories to (root, keys, status) the way GitResolver does, without a filesystem."""

    def __init__(self, roots: dict[str, list[str]], unknown: tuple[str, ...] = ()):
        self.roots = roots
        self.unknown = unknown

    def locate(self, path: str):
        for u in self.unknown:
            if path == u or path.startswith(u + "/"):
                return None, [], "unknown"
        for root, keys in sorted(self.roots.items(), key=lambda kv: -len(kv[0])):
            if path == root or path.startswith(root + "/"):
                return root, keys, "repo"
        return None, ["dir:" + path], "outside"


class ExtractPaths(unittest.TestCase):
    def kinds(self, text: str) -> list[tuple[str, str]]:
        return m.extract_paths(text)

    def test_urls_and_scp_remotes_are_not_paths(self):
        self.assertEqual(self.kinds("see https://docs.example.org/guide/setup.md for it"), [])
        self.assertEqual(self.kinds("clone git@example.com:team/app.git first"), [])
        self.assertEqual(self.kinds("file:///etc/app/config.toml"), [])

    def test_absolute_file_with_line_number_and_punctuation(self):
        self.assertEqual(self.kinds("edit /etc/app/config.toml."), [("abs", "/etc/app/config.toml")])
        self.assertEqual(self.kinds("panic at /opt/app/cmd/main.go:42:7"), [("abs", "/opt/app/cmd/main.go")])
        self.assertEqual(self.kinds("CONFIG=/etc/app/a.conf"), [("abs", "/etc/app/a.conf")])

    def test_absolute_path_inside_other_language_text(self):
        self.assertEqual(self.kinds("файл /etc/app/a.conf, затем перезапуск"), [("abs", "/etc/app/a.conf")])

    def test_endpoints_and_slash_commands_are_not_paths(self):
        self.assertEqual(self.kinds("GET /api/v1/users returns 200"), [])
        self.assertEqual(self.kinds("run /review before merge"), [])

    def test_absolute_directory_is_its_own_kind(self):
        self.assertEqual(self.kinds("state lives in /var/lib/tool/"), [("absdir", "/var/lib/tool")])
        self.assertEqual(self.kinds("state lives in /var/lib/tool"), [("absdir", "/var/lib/tool")])

    def test_home_paths(self):
        self.assertEqual(self.kinds("the key is in ~/.config/tool/settings.json"),
                         [("home", "~/.config/tool/settings.json")])
        self.assertEqual(self.kinds("cache in ~/.cache/tool"), [("homedir", "~/.cache/tool")])

    def test_variable_prefixed_paths_are_ambiguous(self):
        self.assertEqual(self.kinds("$HOME/x/y.txt and ${ROOT}/a/b.go"), [])

    def test_repository_relative_files(self):
        self.assertEqual(self.kinds("`internal/store/text.go` reads it"), [("rel", "internal/store/text.go")])
        self.assertEqual(self.kinds("run ./scripts/run.sh"), [("rel", "scripts/run.sh")])
        self.assertEqual(self.kinds("CI is .github/workflows/ci.yml"), [("rel", ".github/workflows/ci.yml")])
        self.assertEqual(self.kinds("../x/y.go is outside"), [])

    def test_module_paths_branches_and_globs_are_not_files(self):
        self.assertEqual(self.kinds("module example.com/team/app"), [])
        self.assertEqual(self.kinds("example.com/team/app/main.go"), [])
        self.assertEqual(self.kinds("fork team/app on branch feat/login"), [])
        self.assertEqual(self.kinds("every docs/*.md and src/{a,b}.go"), [])
        self.assertEqual(self.kinds("internal/store/ holds it"), [])

    def test_basenames_only_when_file_shaped(self):
        self.assertEqual(self.kinds("README.md and Makefile changed"), [("base", "README.md"), ("base", "Makefile")])
        self.assertEqual(self.kinds("needs node.js and v0.24.0 from example.com"), [])
        self.assertEqual(self.kinds("set it in .env"), [("base", ".env")])

    def test_each_path_once_in_text_order(self):
        self.assertEqual(self.kinds("/etc/a/b.conf then /etc/a/b.conf and README.md"),
                         [("abs", "/etc/a/b.conf"), ("base", "README.md")])


class Remotes(unittest.TestCase):
    def test_normalize_remote_like_tier_normalize(self):
        self.assertEqual(m.normalize_remote("git@Example.com:Team/App.git"), APP)
        self.assertEqual(m.normalize_remote("https://user@example.com:8443/team/app.git/"), APP)
        self.assertEqual(m.normalize_remote("ssh://git@example.com/team/app"), APP)
        self.assertEqual(m.normalize_remote("/srv/git/app.git"), "")
        self.assertEqual(m.normalize_remote("file:///srv/git/app.git"), "")


class FactState(unittest.TestCase):
    def test_state_at_takes_the_version_in_force(self):
        vs = [version("F1", 1, "2026-10-01T00:00:00Z", "a"),
              version("F1", 2, "2026-10-05T00:00:00Z", "a", status="retired")]
        self.assertIsNone(m.state_at(vs, at("2026-09-30")))
        self.assertEqual(m.state_at(vs, at("2026-10-02"))["version"], 1)
        self.assertEqual(m.state_at(vs, at("2026-10-06"))["version"], 2)

    def test_eligible_is_active_unexpired_and_off_the_shelf(self):
        t = at("2026-10-10")
        self.assertTrue(m.eligible(version("F", 1, "x", "a", expires="2026-10-10"), t))
        self.assertFalse(m.eligible(version("F", 1, "x", "a", expires="2026-10-09"), t))
        self.assertFalse(m.eligible(version("F", 1, "x", "a", status="retired"), t))
        self.assertFalse(m.eligible(version("F", 1, "x", "a", scope="shelf:research"), t))
        self.assertFalse(m.eligible(None, t))

    def test_expiry_is_judged_on_the_local_calendar(self):
        late = datetime.fromisoformat("2026-10-09T22:30:00+00:00")
        f = version("F", 1, "x", "a", expires="2026-10-09")
        self.assertTrue(m.eligible(f, late, tz_minutes=0))
        self.assertFalse(m.eligible(f, late, tz_minutes=180))

    def test_project_of_follows_scope_then_origin(self):
        self.assertEqual(m.project_of(version("F", 1, "x", "a", scope="repo:Example.com/Team/App")), "repo:" + APP)
        self.assertEqual(m.project_of(version("F", 1, "x", "a", scope="dir:/srv/Tool")), "dir:/srv/Tool")
        self.assertEqual(m.project_of(version("F", 1, "x", "a", origin=APP + " 2026-10-01")), "repo:" + APP)
        self.assertEqual(m.project_of(version("F", 1, "x", "a", scope="global", origin=APP + " 2026-10-01")), "")
        self.assertEqual(m.project_of(version("F", 1, "x", "a", origin="_global 2026-10-01")), "")

    def test_placed_mirrors_the_default_places(self):
        keys = [APP]
        self.assertTrue(m.placed(version("F", 1, "x", "a", scope="repo:" + APP), keys, "box"))
        self.assertTrue(m.placed(version("F", 1, "x", "a", scope="host:box", origin=OTHER + " 2026-10-01"), keys,
                                 "box"))
        self.assertTrue(m.placed(version("F", 1, "x", "a", scope="global"), keys, "box"))
        self.assertTrue(m.placed(version("F", 1, "x", "a", origin=APP + " 2026-10-01", scope="service:db"), keys,
                                 "box"))
        self.assertFalse(m.placed(version("F", 1, "x", "a", scope="repo:" + OTHER), keys, "box"))
        self.assertFalse(m.placed(version("F", 1, "x", "a", scope="service:db"), keys, "box"))
        self.assertFalse(m.placed(version("F", 1, "x", "a", scope="host:elsewhere"), keys, "box"))
        # Outside a repository the default is the whole base off the shelves.
        self.assertTrue(m.placed(version("F", 1, "x", "a", scope="repo:" + OTHER), ["dir:/srv/x"], "box"))


class Matching(unittest.TestCase):
    def setUp(self):
        self.facts = {
            "ABS": [version("ABS", 1, "2026-10-01T00:00:00Z", "the port is in /etc/app/config.toml", scope="global")],
            "HOME": [version("HOME", 1, "2026-10-01T00:00:00Z", "token in ~/.config/tool/auth.json",
                             scope="host:box")],
            "REL": [version("REL", 1, "2026-10-01T00:00:00Z", "internal/store/text.go parses lines",
                            scope="repo:" + APP)],
            "LATE": [version("LATE", 1, "2026-10-20T00:00:00Z", "see /etc/app/late.toml", scope="global")],
            "GONE": [version("GONE", 1, "2026-10-01T00:00:00Z", "see /etc/app/gone.toml", scope="global"),
                     version("GONE", 2, "2026-10-03T00:00:00Z", "see /etc/app/gone.toml", scope="global",
                             status="retired")],
            "DIR": [version("DIR", 1, "2026-10-01T00:00:00Z", "logs go to /var/log/app/", scope="global")],
            "BASE": [version("BASE", 1, "2026-10-01T00:00:00Z", "Makefile has the targets", scope="global")],
            "SHELF": [version("SHELF", 1, "2026-10-01T00:00:00Z", "upstream /etc/app/config.toml default",
                              scope="shelf:research")],
            "EDIT": [version("EDIT", 1, "2026-10-01T00:00:00Z", "nothing here", scope="global"),
                     version("EDIT", 2, "2026-10-15T00:00:00Z", "now about /etc/app/config.toml", scope="global")],
        }
        self.index = m.Index(self.facts)
        self.resolver = FakeResolver({"/w/app": [APP], "/w/app-feature": [APP], "/w/other": [OTHER]},
                                     unknown=("/w/gone",))

    def match(self, path, day="2026-10-10"):
        return self.index.match(path, at(day), self.resolver, "/home/u")

    def test_exact_absolute_and_home_paths(self):
        self.assertEqual(self.match("/etc/app/config.toml")["asof"], {"ABS": "abs"})
        self.assertEqual(self.match("/home/u/.config/tool/auth.json")["asof"], {"HOME": "home"})

    def test_shelf_never_matches_and_a_later_version_matches_only_after_it(self):
        self.assertNotIn("SHELF", self.match("/etc/app/config.toml", "2026-10-20")["asof"])
        self.assertIn("EDIT", self.match("/etc/app/config.toml", "2026-10-20")["asof"])
        self.assertNotIn("EDIT", self.match("/etc/app/config.toml", "2026-10-10")["asof"])

    def test_time_respected_and_today_is_an_upper_bound(self):
        r = self.match("/etc/app/late.toml")
        self.assertEqual(r["asof"], {})
        self.assertEqual(r["today"], {"LATE": "abs"})
        g = self.match("/etc/app/gone.toml", "2026-10-02")
        self.assertEqual(g["asof"], {"GONE": "abs"})
        self.assertEqual(g["today"], {})

    def test_relative_path_needs_the_same_repository_in_any_worktree(self):
        self.assertEqual(self.match("/w/app/internal/store/text.go")["asof"], {"REL": "rel"})
        self.assertEqual(self.match("/w/app-feature/internal/store/text.go")["asof"], {"REL": "rel"})
        other = self.match("/w/other/internal/store/text.go")
        self.assertEqual(other["asof"], {})
        self.assertEqual(other["loose"], {"REL": "rel_other_project"})
        gone = self.match("/w/gone/internal/store/text.go")
        self.assertEqual(gone["asof"], {})
        self.assertEqual(gone["loose"], {"REL": "rel_unresolved"})

    def test_relative_path_must_sit_at_the_repository_root(self):
        r = self.match("/w/app/vendor/x/internal/store/text.go")
        self.assertEqual(r["asof"], {})
        self.assertEqual(r["loose"], {"REL": "rel_other_project"})

    def test_directory_and_basename_matches_are_loose_only(self):
        self.assertEqual(self.match("/var/log/app/today.log")["loose"], {"DIR": "dir"})
        self.assertEqual(self.match("/var/log/app/today.log")["asof"], {})
        self.assertEqual(self.match("/w/other/Makefile")["loose"], {"BASE": "base"})

    def test_absolute_path_of_one_checkout_matches_another_worktree_of_its_repository(self):
        resolver = FakeResolver({"/srv/app": [APP], "/srv/app-feature": [APP], "/srv/other": [OTHER]})
        facts = {"WT": [version("WT", 1, "2026-10-01T00:00:00Z", "see /srv/app/internal/a.go", scope="global")]}
        index = m.Index(facts, resolver=resolver)
        t = at("2026-10-10")
        self.assertEqual(index.match("/srv/app/internal/a.go", t, resolver, "/home/u")["asof"], {"WT": "abs"})
        self.assertEqual(index.match("/srv/app-feature/internal/a.go", t, resolver, "/home/u")["asof"],
                         {"WT": "abs_worktree"})
        self.assertEqual(index.match("/srv/other/internal/a.go", t, resolver, "/home/u")["asof"], {})

    def test_a_path_without_extension_matches_only_when_read_exactly(self):
        facts = {"BIN": [version("BIN", 1, "2026-10-01T00:00:00Z", "the wrapper is /usr/local/bin/tool",
                                 scope="global")]}
        index = m.Index(facts)
        t = at("2026-10-10")
        self.assertEqual(index.match("/usr/local/bin/tool", t, self.resolver, "/home/u")["asof"], {"BIN": "abs"})
        r = index.match("/usr/local/bin/tool/x.conf", t, self.resolver, "/home/u")
        self.assertEqual((r["asof"], r["loose"]), ({}, {"BIN": "dir"}))

    def test_no_workspace_wide_match(self):
        r = self.match("/w/app/cmd/main.go")
        self.assertEqual((r["asof"], r["loose"], r["today"]), ({}, {}, {}))


class NormalizeRead(unittest.TestCase):
    def test_relative_and_home_reads(self):
        self.assertEqual(m.normalize_read("a/b.go", "/w/app", "/home/u"), "/w/app/a/b.go")
        self.assertEqual(m.normalize_read("~/x/y.md", "/w/app", "/home/u"), "/home/u/x/y.md")
        self.assertEqual(m.normalize_read("/w/app/./a/../b.go", "", "/home/u"), "/w/app/b.go")
        self.assertIsNone(m.normalize_read("a/b.go", "", "/home/u"))
        self.assertIsNone(m.normalize_read("", "/w", "/home/u"))


class Transcripts(unittest.TestCase):
    def test_claude_reads_dedupe_and_skip_non_calls(self):
        with tempfile.TemporaryDirectory() as d:
            proj = Path(d, "projects", "-w-app")
            (proj / "S2" / "subagents").mkdir(parents=True)
            call = {"type": "tool_use", "id": "toolu_1", "name": "Read", "input": {"file_path": "/w/app/a.go"}}
            rec = {"type": "assistant", "sessionId": "S1", "cwd": "/w/app", "timestamp": "2026-10-10T10:00:00Z",
                   "isSidechain": False, "message": {"id": "msg_1", "content": [call]}}
            bash = {"type": "tool_use", "id": "toolu_2", "name": "Bash", "input": {"command": "cat /etc/app/x.toml"}}
            rec2 = dict(rec, message={"id": "msg_2", "content": [bash]})
            result = {"type": "user", "sessionId": "S1", "cwd": "/w/app", "timestamp": "2026-10-10T10:00:01Z",
                      "message": {"content": [{"type": "tool_result", "tool_use_id": "toolu_1",
                                               "content": "{\"file_path\": \"/w/app/z.go\"}"}]}}
            request = {"type": "api-request", "sessionId": "S1", "params": {"messages": [{"content": [call]}]}}
            lines = [rec, rec, result, request, rec2]
            (proj / "S1.jsonl").write_text("\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8")
            sub = dict(rec, sessionId="S2", isSidechain=True,
                       message={"id": "msg_3", "content": [dict(call, id="toolu_3")]})
            (proj / "S2" / "subagents" / "agent-1.jsonl").write_text(json.dumps(sub) + "\n", encoding="utf-8")
            own = dict(rec, sessionId="ME", message={"id": "msg_4", "content": [dict(call, id="toolu_4")]})
            stand = dict(rec, sessionId="ST", cwd="/w/app/docs/research/scripts/x/results/runs/r1",
                         message={"id": "msg_5", "content": [dict(call, id="toolu_5")]})
            (proj / "ME.jsonl").write_text(json.dumps(own) + "\n", encoding="utf-8")
            (proj / "ST.jsonl").write_text(json.dumps(stand) + "\n", encoding="utf-8")
            reads, bashes, stats = m.read_claude(Path(d, "projects"), {"ME"}, ["/results/runs"])
        self.assertEqual(sorted((r["id"], r["cls"]) for r in reads),
                         [("toolu_1", "main"), ("toolu_3", "subagent"), ("toolu_4", "own"), ("toolu_5", "stand")])
        self.assertEqual([b["id"] for b in bashes], ["toolu_2"])
        self.assertEqual(stats["duplicate_calls"], 1)

    def test_line_separators_inside_json_strings_do_not_split_records(self):
        with tempfile.TemporaryDirectory() as d:
            proj = Path(d, "projects", "-w")
            proj.mkdir(parents=True)
            call = {"type": "tool_use", "id": "toolu_9", "name": "Read", "input": {"file_path": "/w/a.go"}}
            rec = {"type": "assistant", "sessionId": "S", "cwd": "/w", "timestamp": "2026-10-10T10:00:00Z",
                   "message": {"id": "m", "content": [{"type": "text", "text": "one two\x0cthree"}, call]}}
            (proj / "S.jsonl").write_text(json.dumps(rec, ensure_ascii=False) + "\n", encoding="utf-8")
            reads, _, stats = m.read_claude(Path(d, "projects"), set(), [])
            facts_dir = Path(d, "facts", "A")
            facts_dir.mkdir(parents=True)
            v = version("FA", 1, "2026-10-01T00:00:00Z", "first second /etc/app/a.conf")
            (facts_dir / "FA.jsonl").write_text(json.dumps(v, ensure_ascii=False) + "\n", encoding="utf-8")
            facts, fstats = m.load_facts(Path(d, "facts"))
        self.assertEqual([r["id"] for r in reads], ["toolu_9"])
        self.assertNotIn("bad_lines", stats)
        self.assertEqual(facts["FA"][0]["content"], "first second /etc/app/a.conf")

    def test_hermes_reads_dedupe_by_call_id(self):
        with tempfile.TemporaryDirectory() as d:
            db = Path(d, "state.db")
            c = sqlite3.connect(db)
            c.execute("create table sessions (id text, source text, parent_session_id text, cwd text, "
                      "git_repo_root text, started_at real)")
            c.execute("create table messages (id integer primary key, session_id text, role text, tool_calls text, "
                      "timestamp real, active integer, compacted integer)")
            c.execute("insert into sessions values ('H1', 'cli', null, '/w/app', '/w/app', 1)")
            c.execute("insert into sessions values ('H2', 'subagent', 'H1', null, null, 1)")
            tc = [{"id": "call_1", "type": "function",
                   "function": {"name": "read_file", "arguments": json.dumps({"path": "a.go"})}},
                  {"id": "call_2", "type": "function",
                   "function": {"name": "terminal",
                                "arguments": json.dumps({"command": "cat x.toml", "workdir": "/w/tool"})}}]
            for active in (1, 0):
                c.execute("insert into messages (session_id, role, tool_calls, timestamp, active, compacted) "
                          "values ('H1', 'assistant', ?, 1791000000, ?, 0)", (json.dumps(tc), active))
            tc2 = [{"id": "call_3", "type": "function",
                    "function": {"name": "read_file", "arguments": {"path": "/etc/app/x.toml"}}}]
            c.execute("insert into messages (session_id, role, tool_calls, timestamp, active, compacted) "
                      "values ('H2', 'assistant', ?, 1791000001, 1, 0)", (json.dumps(tc2),))
            c.commit()
            c.close()
            reads, terms, stats = m.read_hermes(db)
        self.assertEqual(sorted((r["id"], r["path"], r["cwd"], r["cls"]) for r in reads),
                         [("call_1", "a.go", "/w/app", "cli"), ("call_3", "/etc/app/x.toml", "", "subagent")])
        self.assertEqual([(t["id"], t["cwd"]) for t in terms], [("call_2", "/w/tool")])
        self.assertEqual(stats["duplicate_calls"], 2)

    def test_command_paths_are_absolute_home_or_cwd_relative(self):
        self.assertEqual(m.command_paths("sed -n 1,20p internal/a.go && cat ~/.config/t.json /etc/x/y.conf",
                                         "/w/app", "/home/u"),
                         ["/w/app/internal/a.go", "/home/u/.config/t.json", "/etc/x/y.conf"])


class EndToEnd(unittest.TestCase):
    def build(self, d: str) -> tuple[Path, Path, Path]:
        facts = Path(d, "facts")
        (facts / "A").mkdir(parents=True)
        (facts / "B").mkdir(parents=True)
        (facts / "A" / "FA.jsonl").write_text(json.dumps(version(
            "FA", 1, "2026-10-01T00:00:00Z", "port in /etc/app/config.toml", scope="global")) + "\n", "utf-8")
        (facts / "B" / "FB.jsonl").write_text(json.dumps(version(
            "FB", 1, "2026-10-01T00:00:00Z", "no path here", scope="global")) + "\n", "utf-8")
        proj = Path(d, "projects", "-w")
        proj.mkdir(parents=True)
        recs = []
        for i, p in enumerate(["/etc/app/config.toml", "/etc/app/other.toml", "/etc/app/config.toml"]):
            recs.append({"type": "assistant", "sessionId": "S1", "cwd": "/", "timestamp": "2026-10-10T10:00:00Z",
                         "message": {"id": f"m{i}", "content": [{"type": "tool_use", "id": f"t{i}", "name": "Read",
                                                                 "input": {"file_path": p}}]}})
        (proj / "S1.jsonl").write_text("\n".join(json.dumps(r) for r in recs) + "\n", "utf-8")
        return facts, Path(d, "projects"), Path(d, "out")

    def run_main(self, argv: list[str]) -> int:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return m.main(argv)

    def test_measure_then_summarize_reproduces_the_summary(self):
        with tempfile.TemporaryDirectory() as d:
            facts, projects, out = self.build(d)
            self.assertEqual(self.run_main(["measure", "--facts", str(facts), "--claude-projects", str(projects),
                                            "--home", "/home/u", "--host", "box", "--today", "2026-11-01",
                                            "--out", str(out)]), 0)
            summary = json.loads((out / "summary.json").read_text("utf-8"))
            claude = summary["claude_read"]["all"]
            self.assertEqual(claude["calls"], 3)
            self.assertEqual(claude["asof"]["calls"], 2)
            self.assertEqual(claude["asof"]["unique_facts"], 1)
            self.assertEqual(claude["asof"]["chars_per_call_sum"], 2 * len("port in /etc/app/config.toml"))
            self.assertEqual(claude["asof"]["chars_per_session_unique"], len("port in /etc/app/config.toml"))
            self.assertEqual(summary["facts"]["active"], 2)
            self.assertEqual(summary["facts"]["with_kind"]["abs"], 1)
            again = Path(d, "again")
            self.assertEqual(self.run_main(["summarize", "--in", str(out), "--out", str(again)]), 0)
            self.assertEqual(json.loads((again / "summary.json").read_text("utf-8")), summary)

    def test_out_must_be_new_and_outside_the_inputs(self):
        with tempfile.TemporaryDirectory() as d:
            facts, projects, out = self.build(d)
            out.mkdir()
            (out / "keep.txt").write_text("x", "utf-8")
            base = ["measure", "--facts", str(facts), "--claude-projects", str(projects), "--home", "/home/u",
                    "--host", "box", "--today", "2026-11-01", "--out"]
            self.assertNotEqual(self.run_main(base + [str(out)]), 0)
            self.assertEqual((out / "keep.txt").read_text("utf-8"), "x")
            self.assertNotEqual(self.run_main(base + [str(facts / "inside")]), 0)
            self.assertFalse((facts / "inside").exists())
            self.assertEqual(sorted(os.listdir(facts)), ["A", "B"])


def measure_argv(facts: Path, out: Path, *extra: str, host: str = "box") -> list[str]:
    return ["measure", "--facts", str(facts), "--home", "/home/u", "--host", host, "--today", "2026-11-01",
            "--out", str(out), *extra]


def run_quiet(argv: list[str]) -> int:
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return m.main(argv)


def write_fact(facts: Path, versions: list[dict]) -> None:
    d = facts / versions[0]["id"][-1]
    d.mkdir(parents=True, exist_ok=True)
    (d / (versions[0]["id"] + ".jsonl")).write_text("".join(json.dumps(v) + "\n" for v in versions), "utf-8")


class PublicAggregates(unittest.TestCase):
    def test_meta_and_summary_do_not_carry_the_host(self):
        with tempfile.TemporaryDirectory() as d:
            facts, projects, out = EndToEnd.build(self, d)
            host = "zz-private-host-name"
            self.assertEqual(run_quiet(measure_argv(facts, out, "--claude-projects", str(projects), host=host)), 0)
            for name in ("meta.json", "summary.json"):
                self.assertNotIn(host, (out / name).read_text("utf-8"), name)


class PrivateModes(unittest.TestCase):
    def test_outputs_are_owner_only_whatever_the_umask(self):
        with tempfile.TemporaryDirectory() as d:
            facts, projects, out = EndToEnd.build(self, d)
            again = Path(d, "again")
            old = os.umask(0)
            try:
                self.assertEqual(run_quiet(measure_argv(facts, out, "--claude-projects", str(projects))), 0)
                self.assertEqual(run_quiet(["summarize", "--in", str(out), "--out", str(again)]), 0)
            finally:
                os.umask(old)
            for directory in (out, again):
                self.assertEqual(directory.stat().st_mode & 0o777, 0o700, directory)
                for f in directory.iterdir():
                    self.assertEqual(f.stat().st_mode & 0o777, 0o600, f)


class MetadataTime(unittest.TestCase):
    """Relabel, Retag and SetQueries copy the creation time of the version before (internal/store/store.go), so the
    time of a version that changes only metadata is unknown."""

    def setUp(self):
        self.resolver = FakeResolver({})

    def test_a_relabel_with_the_same_created_is_ambiguous_not_current(self):
        vs = [version("F", 1, "2026-10-01T00:00:00Z", "see /etc/app/x.toml", expires="2026-10-05"),
              version("F", 2, "2026-10-01T00:00:00Z", "see /etc/app/x.toml")]
        r = m.Index({"F": vs}).match("/etc/app/x.toml", at("2026-10-10"), self.resolver, "/home/u")
        self.assertEqual(r["asof"], {})
        self.assertEqual(r["ambiguous"], {"F": "abs"})

    def test_a_scope_change_onto_the_shelf_is_ambiguous(self):
        vs = [version("F", 1, "2026-10-01T00:00:00Z", "see /etc/app/x.toml", scope="global"),
              version("F", 2, "2026-10-01T00:00:00Z", "see /etc/app/x.toml", scope="shelf:research")]
        r = m.Index({"F": vs}).match("/etc/app/x.toml", at("2026-10-10"), self.resolver, "/home/u")
        self.assertEqual((r["asof"], r["ambiguous"]), ({}, {"F": "abs"}))

    def test_a_relabel_after_a_correction_copies_a_distinct_time(self):
        vs = [version("F", 1, "2026-10-01T00:00:00Z", "old text"),
              version("F", 2, "2026-10-03T00:00:00Z", "see /etc/app/x.toml"),
              version("F", 3, "2026-10-03T00:00:00Z", "see /etc/app/x.toml", scope="shelf:research"),
              version("F", 4, "2026-10-08T00:00:00Z", "see /etc/app/x.toml", scope="shelf:research",
                      status="retired")]
        self.assertEqual([v["version"] for v in m.plausible_versions(vs, at("2026-09-30"))], [])
        self.assertEqual([v["version"] for v in m.plausible_versions(vs, at("2026-10-05"))], [2, 3])
        self.assertEqual([v["version"] for v in m.plausible_versions(vs, at("2026-10-09"))], [4])
        idx = m.Index({"F": vs})
        r = idx.match("/etc/app/x.toml", at("2026-10-05"), self.resolver, "/home/u")
        self.assertEqual((r["asof"], r["ambiguous"]), ({}, {"F": "abs"}))
        r = idx.match("/etc/app/x.toml", at("2026-10-09"), self.resolver, "/home/u")
        self.assertEqual((r["asof"], r["ambiguous"]), ({}, {}))

    def test_a_snapshot_before_the_call_settles_every_version(self):
        vs = [version("F", 1, "2026-10-03T00:00:00Z", "see /etc/app/x.toml"),
              version("F", 2, "2026-10-03T00:00:00Z", "see /etc/app/x.toml", scope="shelf:research")]
        idx = m.Index({"F": vs}, snapshot=at("2026-10-04"))
        r = idx.match("/etc/app/x.toml", at("2026-10-05"), self.resolver, "/home/u")
        self.assertEqual((r["asof"], r["ambiguous"]), ({}, {}))

    def test_a_relabel_that_changes_nothing_relevant_stays_certain(self):
        vs = [version("F", 1, "2026-10-01T00:00:00Z", "see /etc/app/x.toml"),
              dict(version("F", 2, "2026-10-01T00:00:00Z", "see /etc/app/x.toml"), kind="rule")]
        r = m.Index({"F": vs}).match("/etc/app/x.toml", at("2026-10-10"), self.resolver, "/home/u")
        self.assertEqual((r["asof"], r["ambiguous"]), ({"F": "abs"}, {}))

    def test_placement_that_depends_on_a_relabel_is_unsure(self):
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d, "repo")
            (repo / ".git").mkdir(parents=True)
            (repo / ".git" / "config").write_text('[remote "origin"]\n\turl = git@example.com:team/app.git\n',
                                                  "utf-8")
            facts = Path(d, "facts")
            write_fact(facts, [version("F", 1, "2026-10-01T00:00:00Z", "see /etc/app/x.toml", scope="repo:" + OTHER),
                               version("F", 2, "2026-10-01T00:00:00Z", "see /etc/app/x.toml", scope="global")])
            proj = Path(d, "projects", "-r")
            proj.mkdir(parents=True)
            rec = {"type": "assistant", "sessionId": "S", "cwd": str(repo), "timestamp": "2026-10-10T10:00:00Z",
                   "message": {"id": "m", "content": [{"type": "tool_use", "id": "t1", "name": "Read",
                                                       "input": {"file_path": "/etc/app/x.toml"}}]}}
            (proj / "S.jsonl").write_text(json.dumps(rec) + "\n", "utf-8")
            out = Path(d, "out")
            self.assertEqual(run_quiet(measure_argv(facts, out, "--claude-projects", str(Path(d, "projects")))), 0)
            row = json.loads((out / "calls.jsonl").read_text("utf-8").splitlines()[0])
        self.assertEqual(row["asof"], {"F": "abs"})
        self.assertEqual(row["placed_session"], [])
        self.assertEqual(row["placed_session_unsure"], ["F"])


class FilePlaces(unittest.TestCase):
    def test_the_files_repository_only_adds_places(self):
        other = version("F", 1, "x", "a", scope="repo:" + OTHER)
        third = version("F", 1, "x", "a", scope="repo:example.com/team/third")
        self.assertTrue(m.placed(other, ["dir:/srv/x"], "box"))
        self.assertTrue(m.placed_union(other, ["dir:/srv/x"], [APP], "box"))
        self.assertTrue(m.placed_union(other, [APP], [OTHER], "box"))
        self.assertFalse(m.placed_union(third, [APP], [OTHER], "box"))
        self.assertTrue(m.placed_union(other, None, [OTHER], "box"))
        self.assertFalse(m.placed_union(third, None, [OTHER], "box"))
        self.assertIsNone(m.placed_union(other, None, [], "box"))


class Cutoff(unittest.TestCase):
    def setUp(self):
        self.facts = {
            "FUT": [version("FUT", 1, "2026-12-01T00:00:00Z", "see /etc/app/x.toml", scope="global")],
            "IN": [version("IN", 1, "2026-11-02T20:59:59Z", "see /etc/app/x.toml", scope="global")],
            "OUT": [version("OUT", 1, "2026-11-02T21:00:00Z", "see /etc/app/x.toml", scope="global")],
            "LATER": [version("LATER", 1, "2026-10-01T00:00:00Z", "see /etc/app/x.toml", scope="global"),
                      version("LATER", 2, "2026-12-01T00:00:00Z", "see /etc/app/x.toml", scope="global",
                              status="retired")],
        }

    def test_today_matches_end_at_the_local_day(self):
        idx = m.Index(self.facts, today="2026-11-02", tz_minutes=180)
        r = idx.match("/etc/app/x.toml", at("2026-11-01"), FakeResolver({}), "/home/u")
        self.assertEqual(r["today"], {"IN": "abs", "LATER": "abs"})

    def test_inventory_ends_at_the_local_day(self):
        recs = {f["id"]: f for f in m.fact_records(self.facts, "2026-11-02", "/home/u", tz_minutes=180)}
        self.assertEqual({k: v["status"] for k, v in recs.items()},
                         {"FUT": "future", "IN": "active", "OUT": "future", "LATER": "active"})


class Inputs(unittest.TestCase):
    def test_a_named_input_must_exist_and_be_of_its_type(self):
        with tempfile.TemporaryDirectory() as d:
            facts, projects, _ = EndToEnd.build(self, d)
            a_file = Path(d, "plain.txt")
            a_file.write_text("x", "utf-8")
            cases = [
                measure_argv(Path(d, "missing"), Path(d, "o1")),
                measure_argv(a_file, Path(d, "o2")),
                measure_argv(facts, Path(d, "o3"), "--claude-projects", str(Path(d, "missing"))),
                measure_argv(facts, Path(d, "o4"), "--claude-projects", str(a_file)),
                measure_argv(facts, Path(d, "o5"), "--hermes-state", str(Path(d, "missing.db"))),
                measure_argv(facts, Path(d, "o6"), "--hermes-state", str(projects)),
            ]
            for argv in cases:
                self.assertNotEqual(run_quiet(argv), 0, argv)
                self.assertFalse(Path(argv[argv.index("--out") + 1]).exists(), argv)
            self.assertEqual(run_quiet(measure_argv(facts, Path(d, "ok"))), 0)


class Boundaries(unittest.TestCase):
    def test_a_quoted_spaced_name_or_a_bracket_glob_leaves_no_directory(self):
        self.assertEqual(m.extract_paths('the file "/etc/acme/foo bar.conf" holds it'), [("base", "bar.conf")])
        self.assertEqual(m.extract_paths("each /etc/acme/a[12].conf"), [])
        self.assertEqual(m.extract_paths("open /etc/acme/my\\ file.conf"), [("base", "file.conf")])
        self.assertEqual(m.extract_paths("one `/var/lib/tool` dir"), [("absdir", "/var/lib/tool")])

    def test_such_fragments_never_match_strongly(self):
        idx = m.Index({"Q": [version("Q", 1, "2026-10-01T00:00:00Z", 'edit "/etc/acme/foo bar.conf"')],
                       "B": [version("B", 1, "2026-10-01T00:00:00Z", "edit /etc/acme/a[12].conf")]})
        for p in ("/etc/acme/foo", "/etc/acme/a"):
            r = idx.match(p, at("2026-10-10"), FakeResolver({}), "/home/u")
            self.assertEqual((r["asof"], r.get("ambiguous", {})), ({}, {}), p)

    def test_a_file_shaped_head_of_a_quoted_spaced_name_is_dropped_too(self):
        self.assertEqual(m.extract_paths('edit "/etc/acme/foo.conf backup"'), [])
        self.assertEqual(m.extract_paths('edit "~/.config/acme/a.json old" now'), [])
        self.assertEqual(m.extract_paths('edit "docs/acme/a.md copy" now'), [])
        self.assertEqual(m.extract_paths('edit "/etc/acme/foo.conf" now'), [("abs", "/etc/acme/foo.conf")])
        idx = m.Index({"Q": [version("Q", 1, "2026-10-01T00:00:00Z", 'edit "/etc/acme/foo.conf backup"')]})
        r = idx.match("/etc/acme/foo.conf", at("2026-10-10"), FakeResolver({}), "/home/u")
        self.assertEqual((r["asof"], r["ambiguous"], r["loose"]), ({}, {}, {}))


class SummarizeInputs(unittest.TestCase):
    def test_summarize_reads_its_inputs_before_making_the_output(self):
        with tempfile.TemporaryDirectory() as d:
            facts, projects, out = EndToEnd.build(self, d)
            self.assertEqual(run_quiet(measure_argv(facts, out, "--claude-projects", str(projects))), 0)
            partial = Path(d, "partial")
            partial.mkdir()
            (partial / "meta.json").write_text((out / "meta.json").read_text("utf-8"), "utf-8")
            (partial / "facts.jsonl").write_text((out / "facts.jsonl").read_text("utf-8"), "utf-8")
            broken = Path(d, "broken")
            broken.mkdir()
            for name in ("meta.json", "facts.jsonl"):
                (broken / name).write_text((out / name).read_text("utf-8"), "utf-8")
            (broken / "calls.jsonl").write_text("{not json\n", "utf-8")
            for src in (Path(d, "missing"), Path(d, "plain.txt"), partial, broken):
                if src.name == "plain.txt":
                    src.write_text("x", "utf-8")
                dest = Path(d, "out-" + src.name)
                self.assertNotEqual(run_quiet(["summarize", "--in", str(src), "--out", str(dest)]), 0, src)
                self.assertFalse(dest.exists(), src)


class History(unittest.TestCase):
    def test_a_malformed_history_fails_closed(self):
        bad = {
            "mixed": [version("F1", 1, "2026-10-01T00:00:00Z", "a"), version("F2", 2, "2026-10-01T00:00:00Z", "b")],
            "conflict": [version("F1", 1, "2026-10-01T00:00:00Z", "a"), version("F1", 1, "2026-10-01T00:00:00Z", "b")],
        }
        for name, versions in bad.items():
            with tempfile.TemporaryDirectory() as d:
                facts = Path(d, "facts")
                write_fact(facts, versions)
                with self.assertRaises(ValueError, msg=name):
                    m.load_facts(facts)
                out = Path(d, "out")
                self.assertNotEqual(run_quiet(measure_argv(facts, out)), 0, name)
                self.assertFalse(out.exists(), name)


if __name__ == "__main__":
    unittest.main()
