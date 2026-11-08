"""Real native/PostgreSQL correction followed by input-file close failure."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

class ClosePhase(unittest.TestCase):
    def test_committed_correction_close_failure_is_explicit_unknown(self):
        fixture = os.environ.get('MEMCUE_RESPONSE_FIXTURE')
        if not fixture:
            self.skipTest('isolated native PostgreSQL fixture required')
        path = Path(fixture)
        cfg = json.loads(path.read_text())
        spec = importlib.util.spec_from_file_location('close_adapter', Path(__file__).parents[1] / 'scripts/memcue.py')
        adapter = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(adapter)
        env = {k:v for k,v in os.environ.items() if not k.startswith(('PG','MEMCUE_','CLAUDE_'))}
        env.update(cfg['native_env'])
        def sql(query):
            r = subprocess.run([cfg['psql'], '-XAt', '-v', 'ON_ERROR_STOP=1', '-c', query],
                               env=dict(env, **cfg['psql_env']), capture_output=True, text=True, timeout=7)
            self.assertEqual(r.returncode, 0)
            return r.stdout.strip()
        seed = subprocess.run([cfg['binary'], 'add', '-source', 'user', '--',
                               'Prefer explicit correction outcome guidance.'], env=env,
                              capture_output=True, text=True, timeout=7)
        self.assertEqual(seed.returncode, 0)
        fact_id = seed.stdout.strip()
        count, size = map(int, sql('SELECT count(*),coalesce(sum(octet_length(payload::text)),0) FROM memcue.facts').split('|'))
        self.assertEqual(count, 1)
        self.assertLess(size, 64 << 20)
        self.assertEqual(sql('SELECT version FROM memcue.facts'), '1')
        original_file, original_popen = tempfile.TemporaryFile, subprocess.Popen
        files, native = [], []
        class CloseFault:
            def __init__(self, file): self.file = file
            def __getattr__(self, name): return getattr(self.file, name)
            def __enter__(self): return self
            def __exit__(self, *exc):
                self.file.close()
                self_test.assertEqual(len(native), 1)
                self_test.assertEqual(native[0].returncode, 0, 'native must actually finish successfully before fault')
                versions = sql("SELECT string_agg(version::text,',' ORDER BY version) FROM memcue.facts WHERE id='" + fact_id + "'")
                self_test.assertEqual(versions, '1,2', 'independent durable observation must precede injected close failure')
                (path.parent / 'close-phase-marker.json').write_text(json.dumps({'native_exit':0,'versions':versions,'temporary_file_ordinal':3}))
                raise OSError('synthetic input-file close failure')
        self_test = self
        def temporary(*args, **kwargs):
            file = original_file(*args, **kwargs)
            files.append(file)
            return CloseFault(file) if len(files) == 3 else file
        def popen(argv, **kwargs):
            child = original_popen(argv, **kwargs)
            if argv[0] == cfg['binary'] and argv[1] == 'correct': native.append(child)
            return child
        config = {'binary':cfg['binary'],'facts':str(path.parent/'absent'),'state_dir':str(path.parent/'codex-state'),'host':'synthetic'}
        failure = None
        with patch.dict(os.environ, env, clear=True), patch.object(adapter.tempfile,'TemporaryFile',temporary), patch.object(adapter._subprocess,'Popen',popen):
            try:
                adapter.call(config, ['correct','-expected-version','1','--',fact_id,
                                      'Prefer explicit safe correction recovery guidance.'], str(path.parent))
            except Exception as exc:
                failure = exc
        self.assertEqual(len(native), 1, 'no automatic replay')
        self.assertTrue(all(f.closed for f in files))
        self.assertEqual(sql("SELECT string_agg(version::text,',' ORDER BY version) FROM memcue.facts WHERE id='"+fact_id+"'"), '1,2')
        self.assertIsInstance(failure, adapter.AdapterError, 'post-attempt runner error must reach the supported caller outcome boundary')
        self.assertIn('UNKNOWN OUTCOME', str(failure))
        self.assertIn(fact_id, str(failure))
        self.assertIn('history', str(failure))
        self.assertNotIn(cfg['password'], str(failure))

if __name__ == '__main__': unittest.main()
