"""Real native process, real durable commit, real pipe timeout at the provider boundary."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import types
import unittest
from unittest.mock import patch

class ResponseTimeout(unittest.TestCase):
    def test_committed_timeout_is_unknown_but_read_timeout_is_failure(self):
        if not os.environ.get('MEMCUE_RESPONSE_FIXTURE'):
            self.skipTest('isolated fixture required')
        cfg=json.loads(Path(os.environ['MEMCUE_RESPONSE_FIXTURE']).read_text())
        env={k:v for k,v in os.environ.items() if not k.startswith(('PG','MEMCUE_','CLAUDE_'))}
        env.update(cfg['native_env'])
        sys.path.insert(0,cfg['hermes_distribution'])
        spec=importlib.util.spec_from_file_location('timeout_provider',Path(__file__).parent/'memcue/__init__.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        provider=module.MemcueMemoryProvider({'binary':cfg['binary'],'dream':False})
        calls=[]
        def delayed_delivery(argv,**kw):
            # Keep a second write fd open after the real native process exits. Its
            # receipt cannot reach communicate EOF before the actual finite timeout.
            reader,writer=os.pipe()
            child=subprocess.Popen(argv,stdin=subprocess.PIPE,stdout=writer,stderr=subprocess.PIPE,
                                   text=True,env=kw['env'])
            os.close(writer)
            child.stdin.write(kw.get('input',''));child.stdin.close();child.stdin=None
            code=child.wait(timeout=10)
            calls.append((argv[1],code))
            # A pipe with a writer held by this harness models withheld delivery.
            held_r,held_w=os.pipe()
            os.close(reader)
            child.stdout=os.fdopen(held_r,'r')
            try:
                return child.communicate(timeout=.02)
            finally:
                os.close(held_w);child.stdout.close();child.stderr.close()
        with patch.dict(os.environ,env,clear=True):
            seed=json.loads(provider.handle_tool_call('memcue_add',{'content':'Prefer compact examples in explanations.','kind':'rule'}))
            self.assertNotIn('error',seed)
            fact_id=seed['result'].strip()
            with patch.object(module,'subprocess',types.SimpleNamespace(run=delayed_delivery,TimeoutExpired=subprocess.TimeoutExpired)):
                answer=provider.handle_tool_call('memcue_correct',{'id':fact_id,'expected_version':1,'content':'Prefer compact concrete examples in explanations.'})
            observed=subprocess.run([cfg['psql'],'-XAt','-c',"SELECT string_agg(version::text,',' ORDER BY version) FROM memcue.facts WHERE id='"+fact_id+"'"],env=dict(env,**cfg['psql_env']),capture_output=True,text=True,timeout=10)
            self.assertEqual(observed.returncode,0)
            self.assertEqual(observed.stdout.strip(),'1,2','correction must commit exactly once before timeout oracle')
            self.assertEqual(calls,[('correct',0)])
            self.assertRegex(answer.lower(),r'unknown.{0,20}outcome|ambiguous','caller timeout after a mutation attempt must report UNKNOWN OUTCOME')
            self.assertIn(fact_id,answer)
            self.assertIn('history',answer.lower())
            # An explicit stale retry is refused and cannot append version 3.
            stale=provider.handle_tool_call('memcue_correct',{'id':fact_id,'expected_version':1,'content':'Prefer useful examples.'})
            self.assertIn('changed',stale)
            with patch.object(module,'subprocess',types.SimpleNamespace(run=delayed_delivery,TimeoutExpired=subprocess.TimeoutExpired)):
                read=provider.handle_tool_call('memcue_search',{'query':'compact examples'})
            self.assertNotRegex(read.lower(),r'unknown.{0,20}outcome|ambiguous')
            self.assertIn('error',json.loads(read))
            self.assertNotIn(cfg['password'],answer)

if __name__=='__main__':unittest.main()
