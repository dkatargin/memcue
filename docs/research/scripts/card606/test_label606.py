#!/usr/bin/env python3
"""Synthetic tests of label606.py (#606). Every fact, label and client here is invented; nothing calls a model.

    python3 -I docs/research/scripts/card606/test_label606.py
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import label606 as m  # noqa: E402

CAL = {r["id"]: r["expect"] for r in m.CALIBRATION}


def row(i: int, text: str = "", **kw) -> dict:
    r = {"id": f"f{i}", "text": text or f"Invented fact number {i}.", "created": "2026-01-02T03:04:05+00:00",
         "kind": "fact", "scope": "global", "source": "user", "cards": ["c1"]}
    r.update(kw)
    return r


class FakeClient:
    """Answers each batch with fixture labels: calibration rows get their expected channel, the rest `knowledge`."""

    def __init__(self, base_url="https://chatgpt.com/backend-api/codex", reply=None, finish="stop"):
        self.base_url = base_url
        self._real_client = NS(base_url=base_url, max_retries=2,
                               _client=NS(follow_redirects=True, event_hooks={"request": [], "response": []}))
        self.chat = NS(completions=NS(create=self.create))
        self.calls, self.closed, self.reply, self.finish = [], False, reply, finish

    def create(self, **kw):
        self.calls.append(kw)
        facts = json.loads(kw["messages"][1]["content"])["facts"]
        labels = [{"id": f["id"], "channel": CAL.get(f["id"], "knowledge"), "confidence": "high",
                   "reason": "fixture", "programs": []} for f in facts]
        content = self.reply(facts) if self.reply else json.dumps({"labels": labels})
        msg = NS(content=content, tool_calls=None)
        return NS(choices=[NS(message=msg, finish_reason=self.finish)], model=kw["model"],
                  usage=NS(prompt_tokens=10, completion_tokens=5, total_tokens=15))

    def close(self):
        self.closed = True


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.out = self.dir / "out"

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, rows) -> Path:
        p = self.dir / "in.json"
        p.write_text(rows if isinstance(rows, str) else json.dumps(rows))
        return p

    def run_main(self, rows, client=None) -> tuple[int, str, FakeClient]:
        c = client or FakeClient()
        factory = lambda: (m.harden(c, m.MODEL, FakeClient), m.MODEL)  # noqa: E731
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = m.main(["--in", str(self.write(rows)), "--out", str(self.out)], factory)
        return code, buf.getvalue(), c


class Validation(Base):
    def refused(self, rows, needle: str):
        with self.assertRaises(m.InputError) as e:
            m.load_rows(self.write(rows))
        self.assertIn(needle, str(e.exception))

    def test_schema(self):
        self.refused({"id": "x"}, "list")
        self.refused([{k: v for k, v in row(1).items() if k != "cards"}], "fields")
        self.refused([row(1, extra=1)], "fields")
        self.refused([row(1, cards="c1")], "cards")
        self.refused([row(1, scope=3)], "scope")
        self.refused([row(1, created="yesterday")], "created")
        self.refused([row(1, text=" ")], "text")
        self.refused('[{"id": "a", "id": "b"}]', "duplicate key")

    def test_duplicates_and_reserved_ids(self):
        self.refused([row(1), row(1)], "duplicate id")
        self.refused([row(1, id=m.CALIBRATION[0]["id"])], "reserved")

    def test_secret_fails_closed_without_echo(self):
        token = "sk-" + "Zq9x" * 8  # invented, credential-shaped
        for text in (f"key is {token}", "ghp_" + "a1B2" * 9, "-----BEGIN OPENSSH PRIVATE KEY-----"):
            with self.assertRaises(m.InputError) as e:
                m.load_rows(self.write([row(1, text=text)]))
            self.assertNotIn(text, str(e.exception))
            self.assertNotIn(token, str(e.exception))

    def test_refusals_happen_before_output_and_client(self):
        code, out, c = self.run_main([row(1), row(1)])
        self.assertEqual(code, 2)
        self.assertFalse(self.out.exists())
        self.assertEqual(c.calls, [])

    def test_input_symlink_and_output_aliases(self):
        real = self.write([row(1)])
        link = self.dir / "link.json"
        link.symlink_to(real)
        with self.assertRaises(m.InputError):
            m.load_rows(link)
        self.out.mkdir()
        for out in (self.out, real, self.dir / "nope" / "x"):
            with self.assertRaises(m.InputError):
                m.check_out(real, out)
        self.assertEqual(real.read_text(), json.dumps([row(1)]))


class Transport(unittest.TestCase):
    def test_harden_sets_guards(self):
        c = FakeClient()
        m.harden(c, m.MODEL, FakeClient)
        self.assertEqual(c._real_client.max_retries, 0)
        self.assertFalse(c._real_client._client.follow_redirects)
        guard = c._real_client._client.event_hooks["request"][-1]
        guard(NS(url="https://api.openai.com/v1/x"))
        for url in ("https://example.com/v1", "http://chatgpt.com/x", "https://chatgpt.com.evil.test/x"):
            with self.assertRaises(m.TransportError):
                guard(NS(url=url))

    def test_unsafe_route_refused(self):
        for url in ("https://example.com/v1", "http://api.openai.com/v1", "https://chatgpt.com:8443/x"):
            with self.assertRaises(m.TransportError):
                m.harden(FakeClient(base_url=url), m.MODEL, FakeClient)
        with self.assertRaises(m.TransportError):
            m.harden(FakeClient(), "gpt-other", FakeClient)
        with self.assertRaises(m.TransportError):
            m.harden(NS(base_url="https://chatgpt.com"), m.MODEL, FakeClient)


class Run(Base):
    def records(self, name):
        return [json.loads(x) for x in (self.out / name).read_text().splitlines()]

    def test_batches_binding_and_modes(self):
        rows = [row(i) for i in range(10)]
        code, out, c = self.run_main(rows)
        self.assertEqual(code, 0)
        self.assertTrue(c.closed)
        self.assertEqual([len(json.loads(k["messages"][1]["content"])["facts"]) for k in c.calls], [4, 8, 2])
        sent = json.loads(c.calls[1]["messages"][1]["content"])["facts"][0]
        self.assertEqual(set(sent), {"id", "text", "created", "kind", "scope", "source"})
        self.assertEqual(c.calls[1]["extra_body"], {"reasoning": {"enabled": True, "effort": "low"}})
        self.assertEqual(c.calls[1]["timeout"], 120)
        self.assertEqual(json.loads(out), {"rows": 10, "batches": 2, "failed_batches": 0, "labelled": 10,
                                           "unknown": 0, "error_rows": 0, "unprocessed": 0,
                                           "calibration": "passed"})
        labels = {r["id"]: r for r in self.records("labels.jsonl")}
        reqs = {r["batch"]: r for r in self.records("requests.jsonl")}
        resps = {r["batch"]: r for r in self.records("responses.jsonl")}
        lab = labels["f9"]
        self.assertEqual(lab["source_sha256"], m.sha(m.canon(rows[9])))
        self.assertEqual(lab["request_sha256"], m.sha(m.canon(reqs[lab["batch"]]["request"])))
        self.assertEqual(lab["response_sha256"], m.sha(resps[lab["batch"]]["content"]))
        self.assertEqual(oct(self.out.stat().st_mode & 0o777), "0o700")
        for f in self.out.iterdir():
            self.assertEqual(oct(f.stat().st_mode & 0o777), "0o600")

    def test_existing_output_refused(self):
        self.out.mkdir()
        code, _, c = self.run_main([row(1)])
        self.assertEqual((code, c.calls, list(self.out.iterdir())), (2, [], []))

    def test_invalid_reply_is_unknown_and_fails(self):
        bad = [lambda f: "not json", lambda f: json.dumps({"labels": []}),
               lambda f: json.dumps({"labels": [{"id": x["id"], "channel": "vibes", "confidence": "high",
                                                 "reason": "", "programs": []} for x in f]})]
        for reply in bad:
            with self.subTest(reply=reply):
                self.tearDown(); self.setUp()  # noqa: E702
                c = FakeClient()  # calibration is answered right, the real batch with the bad reply
                c.reply = lambda f, r=reply: (json.dumps({"labels": [{"id": x["id"], "channel": CAL[x["id"]],
                                              "confidence": "high", "reason": "fixture", "programs": []}
                                              for x in f]}) if f[0]["id"] in CAL else r(f))
                code, out, c = self.run_main([row(i) for i in range(9)], c)
                self.assertEqual((code, json.loads(out)["failed_batches"], len(c.calls)), (1, 1, 2))
                summary = json.loads(out)
                self.assertEqual(summary.get("error_rows"), 8)
                self.assertEqual(summary.get("unprocessed"), 1)
                labs = self.records("labels.jsonl")
                self.assertEqual((len(labs), {r["channel"] for r in labs}), (8, {"UNKNOWN"}))
                self.assertTrue(c.closed)

    def test_calibration_failure_halts_before_real_rows(self):
        for c in (FakeClient(reply=lambda f: json.dumps({"labels": [
                {"id": x["id"], "channel": "unknown", "confidence": "low", "reason": "", "programs": []}
                for x in f]})), FakeClient(finish="length")):
            with self.subTest():
                self.tearDown(); self.setUp()  # noqa: E702
                code, out, c = self.run_main([row(1)], c)
                self.assertEqual((code, len(c.calls), json.loads(out)["calibration"]), (3, 1, "failed"))
                self.assertTrue(c.closed)


if __name__ == "__main__":
    unittest.main()
