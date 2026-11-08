import importlib.util,json,os,subprocess,unittest
from pathlib import Path
from unittest.mock import patch

class NativeTimeout(unittest.TestCase):
 def test_timeout_after_commit_is_unknown(self):
  if not os.environ.get('MEMCUE_RESPONSE_FIXTURE'):self.skipTest('isolated fixture required')
  cfg=json.loads(Path(os.environ['MEMCUE_RESPONSE_FIXTURE']).read_text())
  spec=importlib.util.spec_from_file_location('response_codex',Path(__file__).parents[1]/'scripts/memcue.py')
  adapter=importlib.util.module_from_spec(spec);spec.loader.exec_module(adapter)
  env={k:v for k,v in os.environ.items() if not k.startswith(('PG','MEMCUE_','CLAUDE_'))};env.update(cfg['native_env'])
  real_run=subprocess.run
  config={'binary':cfg['binary'],'facts':cfg['binary']+'.absent','state_dir':cfg['binary']+'.state','host':'synthetic'}
  with patch.dict(os.environ,env,clear=True):
   fact_id=adapter.call(config,['add','-source','user','--','Prefer compact review examples.'],str(Path(cfg['binary']).parent)).strip()
   reader,writer=os.pipe();os.set_blocking(writer,False)
   try:
    while True:os.write(writer,b'x'*4096)
   except BlockingIOError:pass
   os.set_blocking(writer,True)
   def blocked(argv,**kw):
    kw['stdout']=writer
    return real_run(argv,**kw)
   try:
    with patch.object(adapter.subprocess,'run',blocked):
     try:answer=adapter.call(config,['correct','-expected-version','1','--',fact_id,'Prefer compact concrete review examples.'],str(Path(cfg['binary']).parent),timeout=.25)
     except adapter.AdapterError as e:answer=str(e)
   finally:os.close(reader);os.close(writer)
   check=real_run([cfg['psql'],'-XAt','-c',"SELECT string_agg(version::text,',' ORDER BY version) FROM memcue.facts WHERE id='"+fact_id+"'"],env=dict(env,**cfg['psql_env']),capture_output=True,text=True)
   self.assertEqual(check.returncode,0);self.assertEqual(check.stdout.strip(),'1,2')
   self.assertRegex(answer.lower(),r'unknown.{0,20}outcome|ambiguous','timed-out native correction committed; caller must report UNKNOWN OUTCOME')
   self.assertIn(fact_id,answer);self.assertIn('history',answer.lower());self.assertNotIn(cfg['password'],answer)

if __name__=='__main__':unittest.main()
