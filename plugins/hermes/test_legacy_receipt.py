"""Complete native receipts for existing IDs retain their successful classification."""
import importlib.util,json,os,subprocess,sys,unittest
from pathlib import Path
from unittest.mock import patch

class ExistingIDReceipt(unittest.TestCase):
 def test_complete_existing_id_receipts_are_successful(self):
  if not os.environ.get('MEMCUE_RESPONSE_FIXTURE'):self.skipTest('isolated fixture required')
  cfg=json.loads(Path(os.environ['MEMCUE_RESPONSE_FIXTURE']).read_text())
  env={k:v for k,v in os.environ.items() if not k.startswith(('PG','MEMCUE_','CLAUDE_'))};env.update(cfg['native_env'])
  sys.path.insert(0,cfg['hermes_distribution'])
  def load(name,path):
   spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
  hermes=load('existing_hermes',Path(__file__).parent/'memcue/__init__.py')
  codex=load('existing_codex',Path(__file__).parents[1]/'codex/scripts/memcue.py')
  def sql(q):
   r=subprocess.run([cfg['psql'],'-XAt','-v','ON_ERROR_STOP=1','-c',q],env=dict(env,**cfg['psql_env']),capture_output=True,text=True,timeout=10)
   self.assertEqual(r.returncode,0);return r.stdout.strip()
  for caller in ('hermes','codex'):
   with self.subTest(caller=caller),patch.dict(os.environ,env,clear=True):
    seed=subprocess.run([cfg['binary'],'add','-source','user','--','Prefer truthful complete response classifications.'],env=env,capture_output=True,text=True,timeout=7)
    self.assertEqual(seed.returncode,0);new_id=seed.stdout.strip();legacy='legacy-'+caller
    # Fixture-only preexisting history, using the unchanged schema's supported
    # string ID domain. The mutation and response under test are entirely real.
    sql("UPDATE memcue.facts SET id='"+legacy+"',payload=jsonb_set(payload,'{ID}',to_jsonb('"+legacy+"'::text)) WHERE id='"+new_id+"'")
    self.assertEqual(sql("SELECT version FROM memcue.facts WHERE id='"+legacy+"'"),'1')
    if caller=='hermes':
     p=hermes.MemcueMemoryProvider({'binary':cfg['binary'],'dream':False})
     answer=p.handle_tool_call('memcue_correct',{'id':legacy,'expected_version':1,'content':'Prefer truthful classifications with recovery guidance.'})
    else:
     config={'binary':cfg['binary'],'facts':cfg['binary']+'.absent','state_dir':cfg['binary']+'.state','host':'synthetic'}
     try:answer=codex.call(config,['correct','-expected-version','1','--',legacy,'Prefer truthful classifications with recovery guidance.'],str(Path(cfg['binary']).parent))
     except codex.AdapterError as e:answer=str(e)
    self.assertEqual(sql("SELECT string_agg(version::text,',' ORDER BY version) FROM memcue.facts WHERE id='"+legacy+"'"),'1,2')
    if caller=='hermes':self.assertNotIn('error',json.loads(answer),'complete native receipt for existing ID must be success')
    else:self.assertEqual(answer,legacy+' v2\n','complete native receipt for existing ID must be success')

if __name__=='__main__':unittest.main()
