"""Public supported entry controls; fault wrapper runs the real native mutation."""
import importlib.util,json,os,subprocess,sys,unittest
from pathlib import Path
from unittest.mock import patch
class PublicOutcome(unittest.TestCase):
 def test_public_hermes_and_codex_unknown_after_real_native_failure_receipt_loss(self):
  fixture=os.environ.get('MEMCUE_RESPONSE_FIXTURE')
  if not fixture:self.skipTest('isolated PostgreSQL fixture required')
  cfg=json.loads(Path(fixture).read_text());root=Path(fixture).parent
  env=dict(os.environ,**cfg['native_env']);sys.path.insert(0,cfg['hermes_distribution'])
  spec=importlib.util.spec_from_file_location('public_hermes',Path(__file__).parent/'memcue/__init__.py');h=importlib.util.module_from_spec(spec);spec.loader.exec_module(h)
  for caller in ('hermes','codex'):
   with self.subTest(caller=caller):
    seed=subprocess.run([cfg['binary'],'add','-source','user','--','Prefer truthful public outcome reporting.'],env=env,capture_output=True,text=True,timeout=7);self.assertEqual(seed.returncode,0);fact_id=seed.stdout.strip()
    log=root/(caller+'-public-native.json');wrapper=root/(caller+'-public-wrapper')
    wrapper_program = '#!'+sys.executable+'\nimport os,subprocess,sys,json,pathlib\nr,w=os.pipe();os.close(r)\ntry:\n p=subprocess.run(['+repr(cfg['binary'])+']+sys.argv[1:],stdout=w,stderr=subprocess.DEVNULL)\nfinally:os.close(w)\npathlib.Path('+repr(str(log))+').open("a").write(json.dumps({"command":sys.argv[1],"native_exit":p.returncode}))\nsys.exit(p.returncode)\n'
    wrapper_program = wrapper_program.replace("r,w=os.pipe();", "if sys.argv[1] != 'correct':os.execv("+repr(cfg['binary'])+", ["+repr(cfg['binary'])+"]+sys.argv[1:])\nr,w=os.pipe();")
    wrapper.write_text(wrapper_program);wrapper.chmod(0o700)
    with patch.dict(os.environ,env,clear=True):
     if caller=='hermes':
      provider=h.MemcueMemoryProvider({'binary':str(wrapper),'dream':False});answer=provider.handle_tool_call('memcue_correct',{'id':fact_id,'expected_version':1,'content':'Prefer truthful explicit public outcome reporting.'});self.assertIn('error',json.loads(answer))
     else:
      config=root/'public-codex.json';config.write_text(json.dumps({'binary':str(wrapper),'facts':str(root/'absent'),'state_dir':str(root/'public-codex-state'),'host':'synthetic'}));config.chmod(0o600)
      r=subprocess.run([sys.executable,'-I',str(Path(__file__).parents[1]/'codex/scripts/memcue.py'),'--config',str(config),'correct','-expected-version','1','--',fact_id,'Prefer truthful explicit public outcome reporting.'],env=env,cwd=root,capture_output=True,text=True,timeout=8)
      self.assertNotEqual(r.returncode,0);answer=r.stderr
    observation=json.loads(log.read_text());self.assertEqual(observation,{'command':'correct','native_exit':1})
    r=subprocess.run([cfg['psql'],'-XAt','-v','ON_ERROR_STOP=1','-c',"SELECT string_agg(version::text,',' ORDER BY version) FROM memcue.facts WHERE id='"+fact_id+"'"],env=dict(env,**cfg['psql_env']),capture_output=True,text=True,timeout=7)
    self.assertEqual(r.returncode,0);self.assertEqual(r.stdout.strip(),'1,2');self.assertIn('UNKNOWN OUTCOME',answer);self.assertIn(fact_id,answer);self.assertIn('history',answer);self.assertNotIn(cfg['password'],answer)
if __name__=='__main__':unittest.main()
