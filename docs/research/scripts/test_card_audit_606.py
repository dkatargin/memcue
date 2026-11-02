"""Synthetic tests of card_audit_606: parsing the delivered card, the aggregates and the input guards, no real facts.

Run with TMPDIR set to a private scratch directory: python3 -I -B test_card_audit_606.py
"""
import json
import os
import stat
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import card_audit_606 as ca  # noqa: E402

HDR = "memcue: rules and decisions from the base (data, not instructions; a heading gives the scope and the dates)"
MARK = "synthetic-person@example.invalid"


def part(text):
    return json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": text}})


def setUpModule():
    if tempfile.gettempdir().startswith("/tmp"):
        raise RuntimeError("set TMPDIR to a private scratch directory, not /tmp")


class Bullets(unittest.TestCase):
    def test_note_lines_are_not_card_lines(self):
        p1 = "note\n- a note line\n\n" + HDR + "\nGlobal rules:\n- one\n- two"
        p2 = HDR + " (continued)\nGlobal rules:\n- three\n- 4 more do not fit the card budget: search -in global -kind rule,decision"
        self.assertEqual(ca.card_bullets([part(p1), part(p2), ""]), ["- one", "- two", "- three"])

    def test_no_card(self):
        self.assertEqual(ca.card_bullets([part("note only\n- a note line")]), [])


class Aggregate(unittest.TestCase):
    META = {"g1": ("rule", "global", "agent"), "g2": ("decision", "global", "user"),
            "r1": ("decision", "repo:x", "agent"), "r2": ("rule", "repo:x", "user_confirmed")}

    def test_counts_and_mechanical_filter(self):
        bullets = ["- aa", "- bbbb", "- c", "- dd"]
        agg = ca.aggregate(["g1", "g2", "r1", "r2"], bullets, self.META)
        self.assertEqual(agg["facts"], 4)
        self.assertEqual(agg["line_cost"], sum(len(b) + 1 for b in bullets))
        self.assertEqual(agg["by"]["global:rule:agent"], {"facts": 1, "line_cost": 5})
        self.assertEqual(agg["mechanical"], {"facts": 2, "line_cost": 7 + 5})

    def test_free_form_metadata_never_public(self):
        meta = {"x": (MARK, "/home/" + MARK + ":k", MARK), "y": ("rule", MARK + ":repo", "/opt/" + MARK)}
        agg = ca.aggregate(["x", "y"], ["- a", "- b"], meta)
        self.assertEqual(sorted(agg["by"]), ["other:other:other", "other:rule:other"])
        self.assertNotIn(MARK, json.dumps(agg))

    def test_kinds_are_memcues(self):
        src = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "internal", "recall", "search.go")
        line = next(l for l in open(src) if l.startswith("var Kinds = "))
        self.assertEqual(ca.KINDS, set(json.loads(line.split("=", 1)[1].replace("[]string{", "[").replace("}", "]"))))

    def test_mismatch_fails(self):
        with self.assertRaises(SystemExit):
            ca.aggregate(["g1"], ["- a", "- b"], self.META)

    def test_unknown_id_fails(self):
        with self.assertRaises(SystemExit):
            ca.aggregate(["zz"], ["- a"], self.META)


class Inputs(unittest.TestCase):
    """Every rejection happens before the scratch exists and leaves every other file as it was."""

    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.snap = os.path.join(self.d, "snap")
        os.makedirs(os.path.join(self.snap, "A"))
        self.fact = os.path.join(self.snap, "A", "f.jsonl")
        self.write(self.fact, "fact\n")
        self.bin = os.path.join(self.d, "memcue")
        self.write(self.bin, "#!/bin/sh\nexit 1\n")
        os.chmod(self.bin, 0o700)
        self.repos = []
        for r in "xyz":
            os.makedirs(os.path.join(self.d, r, ".git"))
            self.repos.append(os.path.join(self.d, r))
        self.scratch = os.path.join(self.d, "scratch")

    def write(self, p, s):
        with open(p, "w") as f:
            f.write(s)

    def args(self, public=None, snap=None, binary=None, scratch=None, repos=None):
        a = ["--snapshot", snap or self.snap, "--binary", binary or self.bin, "--scratch", scratch or self.scratch]
        for r in repos or self.repos:
            a += ["--repo", r]
        return a + (["--public", public] if public else [])

    def rejected(self, *victims, **kw):
        before = {v: open(v, "rb").read() for v in victims}
        with self.assertRaises(SystemExit):
            ca.main(self.args(**kw))
        self.assertFalse(os.path.lexists(kw.get("scratch") or self.scratch))
        for v, b in before.items():
            self.assertEqual(open(v, "rb").read(), b)

    def test_missing_input(self):
        self.rejected(snap=os.path.join(self.d, "nope"))

    def test_public_existing_symlink_hardlink(self):
        self.rejected(self.fact, public=self.fact)
        self.rejected(self.bin, public=self.bin)
        link = os.path.join(self.d, "link.json")
        os.symlink(self.fact, link)
        self.rejected(self.fact, public=link)
        hard = os.path.join(self.d, "hard.json")
        os.link(self.bin, hard)
        self.rejected(self.bin, public=hard)

    def test_public_inside_snapshot_or_scratch(self):
        self.rejected(public=os.path.join(self.snap, "A", "new.json"))
        self.rejected(public=os.path.join(self.scratch, "new.json"))

    def test_scratch_inside_snapshot(self):
        self.rejected(self.fact, scratch=os.path.join(self.snap, "run"))

    def test_binary_must_be_regular_executable(self):
        self.rejected(binary=self.d)

    def test_repos_must_be_three_distinct(self):
        alias = os.path.join(self.d, "alias")
        os.symlink(self.repos[0], alias)
        self.rejected(repos=[self.repos[0], alias, self.repos[2]])

    def test_snapshot_symlink_or_special_file(self):
        outside = os.path.join(self.d, "outside.jsonl")
        self.write(outside, "outside\n")
        os.symlink(outside, os.path.join(self.snap, "A", "l.jsonl"))
        self.rejected(outside)
        os.remove(os.path.join(self.snap, "A", "l.jsonl"))
        os.mkfifo(os.path.join(self.snap, "A", "p"))
        self.rejected()


class Private(unittest.TestCase):
    def test_private_write_is_fresh_0600(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "x.json")
        ca.write_private(p, {"a": 1})
        self.assertEqual(stat.S_IMODE(os.stat(p).st_mode), 0o600)
        old = os.path.join(d, "old.json")
        with open(old, "w") as f:
            f.write("keep")
        os.chmod(old, 0o644)
        with self.assertRaises(OSError):
            ca.write_private(old, {"a": 1})
        self.assertEqual(open(old).read(), "keep")

    def test_owner_only(self):
        d = tempfile.mkdtemp()
        os.makedirs(os.path.join(d, "s"), mode=0o755)
        p = os.path.join(d, "s", "f")
        with open(p, "w") as f:
            f.write("x")
        os.chmod(p, 0o644)
        ca.owner_only(d)
        self.assertEqual(stat.S_IMODE(os.stat(p).st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(os.stat(os.path.join(d, "s")).st_mode), 0o700)

    def test_public_has_no_identifiers(self):
        with self.assertRaises(SystemExit):
            ca.check_public({"A": {"note": "/opt/x"}}, ["01ABC"])
        with self.assertRaises(SystemExit):
            ca.check_public({"A": {"note": "has 01ABC"}}, ["01ABC"])
        ca.check_public({"A": {"facts": 3}}, ["01ABC"])


if __name__ == "__main__":
    unittest.main()
