"""Truthful controls for the post-attempt close-error boundary."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

class CloseControls(unittest.TestCase):
    def setUp(self):
        fixture = os.environ.get('MEMCUE_RESPONSE_FIXTURE')
        if not fixture: self.skipTest('isolated native PostgreSQL fixture required')
        self.path = Path(fixture)
        self.cfg = json.loads(self.path.read_text())
        spec = importlib.util.spec_from_file_location('close_controls_adapter', Path(__file__).parents[1]/'scripts/memcue.py')
        self.adapter = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.adapter)
        self.env = {k:v for k,v in os.environ.items() if not k.startswith(('PG','MEMCUE_','CLAUDE_'))}
        self.env.update(self.cfg['native_env'])
        self.config = {'binary':self.cfg['binary'],'facts':str(self.path.parent/'absent'),
                       'state_dir':str(self.path.parent/'codex-state'),'host':'synthetic'}
        p = patch.dict(os.environ,self.env,clear=True)
        p.start(); self.addCleanup(p.stop)
    def call(self, args, config=None):
        return self.adapter.call(config or self.config,args,str(self.path.parent))
    def test_known_spawn_failure_is_not_unknown(self):
        with self.assertRaises(FileNotFoundError) as exc:
            self.call(['add','--','Synthetic nonattempt.'],dict(self.config,binary=str(self.path.parent/'missing-native')))
        self.assertNotIn('UNKNOWN OUTCOME',str(exc.exception))
    def test_known_validation_and_auth_refusals_remain_refusals(self):
        with self.assertRaises(self.adapter.AdapterError) as exc:
            self.call(['correct','-expected-version','0','--','absent','Synthetic refused correction.'])
        self.assertNotIn('UNKNOWN OUTCOME',str(exc.exception))
        with patch.dict(os.environ,{'MEMCUE_POSTGRES_DSN':self.env['MEMCUE_POSTGRES_DSN'].replace(self.cfg['password'],'invalid-synthetic-password')}):
            with self.assertRaises(self.adapter.AdapterError) as auth:
                self.call(['add','-source','user','--','Synthetic authentication refusal.'])
        self.assertNotIn('UNKNOWN OUTCOME',str(auth.exception))
        self.assertNotIn(self.cfg['password'],str(auth.exception))
    def test_read_close_failure_is_an_ordinary_transport_error(self):
        original_file, original_popen = tempfile.TemporaryFile, subprocess.Popen
        files, native = [], []
        case = self
        class CloseFault:
            def __init__(self,file):self.file=file
            def __getattr__(self,name):return getattr(self.file,name)
            def __enter__(self):return self
            def __exit__(self,*exc):
                self.file.close()
                case.assertEqual(len(native),1)
                case.assertEqual(native[0].returncode,0)
                raise OSError('synthetic read-command input-file close failure')
        def temporary(*a,**kw):
            f=original_file(*a,**kw);files.append(f)
            return CloseFault(f) if len(files)==3 else f
        def popen(argv,**kw):
            p=original_popen(argv,**kw)
            if argv[0]==self.cfg['binary']:native.append(p)
            return p
        with patch.object(self.adapter.tempfile,'TemporaryFile',temporary),patch.object(self.adapter._subprocess,'Popen',popen):
            with self.assertRaises(self.adapter.AdapterError) as exc:self.call(['facts'])
        self.assertNotIn('UNKNOWN OUTCOME',str(exc.exception))
        self.assertIn('response transport unavailable',str(exc.exception))
        self.assertTrue(all(f.closed for f in files))
    def test_complete_success_and_validated_noop_stay_successful(self):
        self.assertIn('version',json.loads(self.call(['version','-json'])))
        batch=self.path.parent/'empty-control.json';batch.write_text('[]')
        self.assertEqual(self.call(['add','--batch='+str(batch)]),'')

if __name__=='__main__':unittest.main()
