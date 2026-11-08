"""Caller receipts are lost at the real subprocess boundary, never invented by a fake CLI."""
import importlib.util,json,os,subprocess,sys,types,unittest
from pathlib import Path
from unittest.mock import patch

class MissingReceipt(unittest.TestCase):
 def test_supported_python_callers_reject_missing_mutation_receipt(self):
  if not os.environ.get('MEMCUE_RESPONSE_FIXTURE'):self.skipTest('isolated fixture required')
  cfg=json.loads(Path(os.environ['MEMCUE_RESPONSE_FIXTURE']).read_text())
  env={k:v for k,v in os.environ.items() if not k.startswith(('PG','MEMCUE_','CLAUDE_'))};env.update(cfg['native_env'])
  sys.path.insert(0,cfg['hermes_distribution'])
  def load(name,path):
   spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
  hermes=load('missing_hermes',Path(__file__).parent/'memcue/__init__.py')
  codex=load('missing_codex',Path(__file__).parents[1]/'codex/scripts/memcue.py')
  provider=hermes.MemcueMemoryProvider({'binary':cfg['binary'],'dream':False})
  real_run=subprocess.run
  for caller in ('hermes','codex'):
   with self.subTest(caller=caller),patch.dict(os.environ,env,clear=True):
    seeded=json.loads(provider.handle_tool_call('memcue_add',{'content':'Prefer concise explanations of review findings.','kind':'rule'}));self.assertNotIn('error',seeded)
    fact_id=seeded['result'].strip();calls=[]
    def discard(argv,**kw):
     self.assertEqual(argv[0],cfg['binary']);calls.append(argv[1])
     if caller=='hermes':
      kw.pop('capture_output');kw['stdout']=subprocess.DEVNULL;kw['stderr']=subprocess.PIPE
      result=real_run(argv,**kw);result.stdout='';return result
     # Codex supplies an output file. Losing delivery gives it an empty real file.
     kw['stdout']=subprocess.DEVNULL
     return real_run(argv,**kw)
    module=hermes if caller=='hermes' else codex
    with patch.object(module,'subprocess',types.SimpleNamespace(run=discard,DEVNULL=subprocess.DEVNULL,PIPE=subprocess.PIPE,TimeoutExpired=subprocess.TimeoutExpired)):
     if caller=='hermes':answer=provider.handle_tool_call('memcue_correct',{'id':fact_id,'expected_version':1,'content':'Prefer concise explanations with reasons.'})
     else:
      config={'binary':cfg['binary'],'facts':str(Path(cfg['binary']).parent/'absent'),'state_dir':str(Path(cfg['binary']).parent/'codex-state'),'host':'synthetic'}
      try:answer=codex.call(config,['correct','-expected-version','1','--',fact_id,'Prefer concise explanations with reasons.'],str(Path(cfg['binary']).parent))
      except codex.AdapterError as e:answer=str(e)
    observed=real_run([cfg['psql'],'-XAt','-c',"SELECT string_agg(version::text,',' ORDER BY version) FROM memcue.facts WHERE id='"+fact_id+"'"],env=dict(env,**cfg['psql_env']),capture_output=True,text=True)
    self.assertEqual(observed.returncode,0);self.assertEqual(observed.stdout.strip(),'1,2')
    self.assertEqual(calls,['correct'])
    self.assertRegex(answer.lower(),r'unknown.{0,20}outcome|ambiguous','missing receipt after native success must be UNKNOWN OUTCOME, never empty success')
    self.assertIn(fact_id,answer);self.assertIn('history',answer.lower());self.assertNotIn(cfg['password'],answer)

if __name__=='__main__':unittest.main()
