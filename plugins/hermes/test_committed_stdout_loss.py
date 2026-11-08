"""One real PostgreSQL/native/provider regression; fixture supplied by the task runner."""
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import types
import unittest
from unittest.mock import patch


class CommittedStdoutLoss(unittest.TestCase):
    def test_committed_correction_reports_unknown_outcome(self):
        config_path = os.environ.get('MEMCUE_RESPONSE_FIXTURE')
        if not config_path:
            self.skipTest('requires isolated native/PostgreSQL fixture')
        cfg = json.loads(Path(config_path).read_text())
        artifact = Path(config_path).parent
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(('PG', 'MEMCUE_', 'CLAUDE_'))}
        env.update(cfg['native_env'])
        psql_env = dict(env, **cfg['psql_env'])

        def sql(query):
            result = subprocess.run([cfg['psql'], '-XAt', '-v', 'ON_ERROR_STOP=1',
                                     '-c', query], env=psql_env, capture_output=True,
                                    text=True, timeout=20)
            self.assertEqual(result.returncode, 0, 'independent psql observation failed')
            return result.stdout.strip()

        sys.path.insert(0, cfg['hermes_distribution'])
        spec = importlib.util.spec_from_file_location(
            'response_candidate_provider', Path(__file__).parent / 'memcue/__init__.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        provider = module.MemcueMemoryProvider({'binary': cfg['binary'], 'dream': False})
        # Seed through the supported caller; never invent a native application result.
        with patch.dict(os.environ, env, clear=True):
            seeded = json.loads(provider.handle_tool_call('memcue_add', {
                'content': 'Prefer concise explanations when reviewing changes.', 'kind': 'rule'}))
        self.assertNotIn('error', seeded, 'seed mutation failed')
        fact_id = seeded['result'].strip()
        self.assertRegex(fact_id, r'^[a-zA-Z0-9_-]+$')
        count, size = map(int, sql('SELECT count(*), coalesce(sum(octet_length(payload::text)),0) FROM memcue.facts').split('|'))
        self.assertLess(count, 100000)
        self.assertLess(size, 64 * 1024 * 1024)
        self.assertEqual(count, 1)
        self.assertEqual(sql('SELECT version FROM memcue.facts'), '1')
        calls = []

        def lose_stdout(argv, **kwargs):
            self.assertEqual(argv[0], cfg['binary'])
            self.assertEqual(argv[1], 'correct')
            self.assertIn('-expected-version', argv)
            calls.append(argv[1])
            # The child really writes to a pipe with no reader: no substituted executable,
            # transaction, exit code or fabricated stdout. Preserve the OS exit exactly.
            reader, writer = os.pipe()
            os.close(reader)
            try:
                child = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=writer,
                                         stderr=subprocess.PIPE, env=kwargs['env'],
                                         text=True, encoding='utf-8', errors='replace')
            finally:
                os.close(writer)
            try:
                _, stderr = child.communicate(kwargs.get('input', ''), timeout=kwargs['timeout'])
            except BaseException:
                child.kill()
                child.communicate()
                raise
            (artifact / 'native-exit.json').write_text(json.dumps({
                'returncode': child.returncode, 'stderr': stderr, 'stdout_pipe_reader_closed': True}))
            return subprocess.CompletedProcess(argv, child.returncode, '', stderr)

        with patch.dict(os.environ, env, clear=True), patch.object(
                module, 'subprocess', types.SimpleNamespace(run=lose_stdout,
                TimeoutExpired=subprocess.TimeoutExpired)):
            answer = provider.handle_tool_call('memcue_correct', {
                'id': fact_id, 'expected_version': 1,
                'content': 'Prefer concise explanations with concrete examples when reviewing changes.'})
        # A separate psql process, after the caller returns, proves durable commit and no replay.
        versions = sql('SELECT string_agg(version::text,\',\' ORDER BY version) FROM memcue.facts')
        self.assertEqual(versions, '1,2', 'fault did not follow exactly one committed correction')
        self.assertEqual(calls, ['correct'], 'caller replayed the mutation')
        self.assertEqual(sql('SELECT count(DISTINCT id) FROM memcue.facts'), '1')
        (artifact / 'observation.json').write_text(json.dumps({
            'preflight_count': count, 'preflight_bytes': size, 'initial_version': 1,
            'durable_versions': versions, 'native_calls': calls, 'provider_answer': answer,
            'entry': 'MemcueMemoryProvider.handle_tool_call -> _run -> real native binary'}))
        self.assertRegex(answer.lower(), r'ambiguous|unknown.{0,20}outcome|outcome.{0,20}unknown',
                         'committed correction with lost stdout must explicitly report AMBIGUOUS/UNKNOWN OUTCOME')
        self.assertRegex(answer.lower(), r'inspect|history', 'must offer safe durable-history recovery')
        self.assertIn(fact_id, answer, 'recovery must identify the durable fact')
        self.assertNotIn(cfg['password'], answer, 'recovery leaked credentials')


if __name__ == '__main__':
    unittest.main()
