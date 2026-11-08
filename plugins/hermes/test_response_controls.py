"""Supplemental real response controls after the outcome repairs reached GREEN."""
import importlib.util,json,os,subprocess,sys,unittest
from pathlib import Path
from unittest.mock import patch

class ResponseControls(unittest.TestCase):
 def test_native_response_classifications_and_real_stdout_deadline(self):
  if not os.environ.get('MEMCUE_RESPONSE_FIXTURE'):self.skipTest('isolated fixture required')
  config_path=Path(os.environ['MEMCUE_RESPONSE_FIXTURE']);cfg=json.loads(config_path.read_text())
  env={k:v for k,v in os.environ.items() if not k.startswith(('PG','MEMCUE_','CLAUDE_'))};env.update(cfg['native_env'])
  sys.path.insert(0,cfg['hermes_distribution'])
  spec=importlib.util.spec_from_file_location('controlled_provider',Path(__file__).parent/'memcue/__init__.py')
  module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
  provider=module.MemcueMemoryProvider({'binary':cfg['binary'],'dream':False})
  def sql(q):
   r=subprocess.run([cfg['psql'],'-XAt','-v','ON_ERROR_STOP=1','-c',q],env=dict(env,**cfg['psql_env']),capture_output=True,text=True,timeout=10)
   self.assertEqual(r.returncode,0);return r.stdout.strip()
  with patch.dict(os.environ,env,clear=True):
   added=json.loads(provider.handle_tool_call('memcue_add',{'kind':'rule','content':'Prefer precise response classifications in review explanations.'}))
   self.assertNotIn('error',added);fact_id=added['result'].strip()
   corrected=json.loads(provider.handle_tool_call('memcue_correct',{'id':fact_id,'expected_version':1,'content':'Prefer precise response classifications with examples.'}))
   self.assertEqual(corrected['result'],fact_id+' v2')
   for invalid in ({'id':fact_id,'content':'No version is supplied.'},{'id':fact_id,'expected_version':1,'content':'Stale review decision.'}):
    result=provider.handle_tool_call('memcue_correct',invalid)
    self.assertIn('error',json.loads(result));self.assertNotRegex(result.lower(),r'unknown.{0,20}outcome|ambiguous')
   with patch.dict(os.environ,{'MEMCUE_POSTGRES_DSN':env['MEMCUE_POSTGRES_DSN'].replace(cfg['password'],'invalid-synthetic-password')}):
    failed=provider.handle_tool_call('memcue_correct',{'id':fact_id,'expected_version':2,'content':'This must not be committed.'})
   self.assertIn('error',json.loads(failed));self.assertNotRegex(failed.lower(),r'unknown.{0,20}outcome|ambiguous')
   self.assertNotIn(cfg['password'],failed)
   self.assertEqual(sql("SELECT string_agg(version::text,',' ORDER BY version) FROM memcue.facts WHERE id='"+fact_id+"'"),'1,2')
   # Claude's supported shell caller execs the same CLI and preserves its native error.
   reader,writer=os.pipe();os.close(reader)
   try:
    claude=subprocess.run(['sh',str(Path(__file__).parents[1]/'claude-code/scripts/memcue.sh'),'correct','-expected-version','2','--',fact_id,'Prefer clear recovery examples.'],env=dict(env,MEMCUE_BIN=cfg['binary']),stdout=writer,stderr=subprocess.PIPE,text=True,timeout=7)
   finally:os.close(writer)
   self.assertNotEqual(claude.returncode,0);self.assertIn('UNKNOWN OUTCOME',claude.stderr)
   self.assertEqual(sql("SELECT string_agg(version::text,',' ORDER BY version) FROM memcue.facts WHERE id='"+fact_id+"'"),'1,2,3')
   reader,writer=os.pipe();os.close(reader)
   try:
    read=subprocess.run([cfg['binary'],'history',fact_id],env=env,stdout=writer,stderr=subprocess.PIPE,text=True,timeout=7)
   finally:os.close(writer)
   self.assertNotEqual(read.returncode,0);self.assertNotIn('UNKNOWN OUTCOME',read.stderr)
   (config_path.parent/'controls.json').write_text(json.dumps({'complete_success':True,'precommit_validation_auth':True,'stale_retry_history_unchanged':True,'claude_closed_exit':claude.returncode,'read_closed_exit':read.returncode,'durable_versions':'1,2,3'}))

if __name__=='__main__':unittest.main()
