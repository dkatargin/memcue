"""Frozen controls for complete batches and conservative protocol mismatches."""
import importlib.util,json,os,subprocess,sys,unittest
from pathlib import Path
from unittest.mock import patch
class CompletionControls(unittest.TestCase):
 def test_real_batch_aliases_empty_noop_and_native_refusals(self):
  fixture=os.environ.get('MEMCUE_RESPONSE_FIXTURE')
  if not fixture:self.skipTest('isolated PostgreSQL fixture required')
  p=Path(fixture);cfg=json.loads(p.read_text());sys.path.insert(0,cfg['hermes_distribution'])
  def load(n,path):
   s=importlib.util.spec_from_file_location(n,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
  h=load('complete_hermes',Path(__file__).parent/'memcue/__init__.py');c=load('complete_codex',Path(__file__).parents[1]/'codex/scripts/memcue.py')
  config={'binary':cfg['binary'],'facts':str(p.parent/'absent'),'state_dir':str(p.parent/'codex-state'),'host':'synthetic'}
  env=dict(os.environ,**cfg['native_env']);provider=h.MemcueMemoryProvider({'binary':cfg['binary'],'dream':False})
  def count():
   r=subprocess.run([cfg['psql'],'-XAt','-v','ON_ERROR_STOP=1','-c','SELECT count(*) FROM memcue.facts'],env=dict(env,**cfg['psql_env']),capture_output=True,text=True,timeout=7);self.assertEqual(r.returncode,0);return int(r.stdout.strip())
  with patch.dict(os.environ,env,clear=True):
   for caller in ('hermes','codex'):
    def call(args):
     if caller=='hermes':return provider._run(args)
     try:return True,c.call(config,args,str(p.parent))
     except c.AdapterError as e:return False,str(e)
    for spelling in ('-batch','-batch=','--batch','--batch='):
     for size in (2,0):
      batch=p.parent/'control-batch.json';batch.write_text(json.dumps([{'Content':'Prefer explicit complete batch outcomes.','Source':'user'}]*size))
      args=['add',spelling+str(batch)] if spelling.endswith('=') else ['add',spelling,str(batch)]
      # Ensure schema through a real native empty read before counting.
      subprocess.run([cfg['binary'],'facts'],env=env,check=True,capture_output=True,timeout=7)
      before=count();ok,out=call(args);self.assertTrue(ok,(caller,spelling,size,out));self.assertEqual(len(out.splitlines()),size);self.assertEqual(count(),before+size)
    ok,out=call(['correct','-expected-version','1','--','absent','Never commit this.'])
    self.assertFalse(ok);self.assertNotIn('UNKNOWN OUTCOME',out)
    with patch.dict(os.environ,{'MEMCUE_POSTGRES_DSN':env['MEMCUE_POSTGRES_DSN'].replace(cfg['password'],'invalid-synthetic-password')}):
     ok,out=call(['add','-source','user','--','Never authenticate this.'])
    self.assertFalse(ok);self.assertNotIn('UNKNOWN OUTCOME',out);self.assertNotIn(cfg['password'],out)
 def test_recovery_never_uses_a_fact_body_as_the_target_id(self):
  if os.environ.get('MEMCUE_HERMES_DISTRIBUTION'):
   sys.path.insert(0,os.environ['MEMCUE_HERMES_DISTRIBUTION'])
  payload='01J00000000000000000000000'
  path=Path(__file__).parents[1]/'codex/scripts/memcue.py'
  spec=importlib.util.spec_from_file_location('target_codex',path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
  self.assertNotIn(payload,m.unknown_mutation(['correct','-expected-version','1','--','legacy-target',payload]))
 def test_complete_frame_nonce_and_version_are_required(self):
  if os.environ.get('MEMCUE_HERMES_DISTRIBUTION'):
   sys.path.insert(0,os.environ['MEMCUE_HERMES_DISTRIBUTION'])
  for name,path in [('h',Path(__file__).parent/'memcue/__init__.py'),('c',Path(__file__).parents[1]/'codex/scripts/memcue.py')]:
   s=importlib.util.spec_from_file_location('frame_'+name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
   for diagnostic in ('\nMEMCUE_OUTCOME_V1 []\n','\nMEMCUE_OUTCOME_V1 null\n','', 'UNKNOWN OUTCOME','\nMEMCUE_OUTCOME_V1 {}\n','\nMEMCUE_OUTCOME_V1 {"version":2}\n'):
    with self.subTest(caller=name,diagnostic=diagnostic):
     self.assertEqual(m.classify_outcome('one-id\n',diagnostic,0,'f'*32)[0],'unknown')
if __name__=='__main__':unittest.main()
