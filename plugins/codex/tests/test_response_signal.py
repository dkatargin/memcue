import importlib.util,json,os,subprocess,time,types,unittest
from pathlib import Path
from unittest.mock import patch

class NativeSignal(unittest.TestCase):
 def test_signal_after_commit_is_unknown(self):
  if not os.environ.get('MEMCUE_RESPONSE_FIXTURE'):self.skipTest('isolated fixture required')
  cfg=json.loads(Path(os.environ['MEMCUE_RESPONSE_FIXTURE']).read_text())
  spec=importlib.util.spec_from_file_location('signal_codex',Path(__file__).parents[1]/'scripts/memcue.py');adapter=importlib.util.module_from_spec(spec);spec.loader.exec_module(adapter)
  env={k:v for k,v in os.environ.items() if not k.startswith(('PG','MEMCUE_','CLAUDE_'))};env.update(cfg['native_env'])
  config={'binary':cfg['binary'],'facts':cfg['binary']+'.absent','state_dir':cfg['binary']+'.state','host':'synthetic'}
  with patch.dict(os.environ,env,clear=True):
   fact_id=adapter.call(config,['add','-source','user','--','Prefer clear recovery guidance after review updates.'],str(Path(cfg['binary']).parent)).strip()
   reader,writer=os.pipe();os.set_blocking(writer,False)
   try:
    while True:os.write(writer,b'x'*4096)
   except BlockingIOError:pass
   os.set_blocking(writer,True)
   observations=[]
   def killed(argv,**kw):
    child=subprocess.Popen(argv,stdin=subprocess.PIPE,stdout=writer,stderr=kw['stderr'],env=kw['env'],cwd=kw['cwd'])
    try:
     child.stdin.write(kw.get('input',b''));child.stdin.close();child.stdin=None
     for _ in range(40):
      r=subprocess.run([cfg['psql'],'-XAt','-c',"SELECT count(*) FROM memcue.facts WHERE id='"+fact_id+"'"],env=dict(env,**cfg['psql_env']),capture_output=True,text=True,timeout=5)
      self.assertEqual(r.returncode,0)
      if r.stdout.strip()=='2':observations.append('1,2');break
      time.sleep(.01)
     self.assertEqual(observations,['1,2'],'must observe committed correction before signal')
    finally:child.kill();child.wait(timeout=5)
    observations.append(child.returncode)
    return subprocess.CompletedProcess(argv,child.returncode)
   try:
    with patch.object(adapter,'subprocess',types.SimpleNamespace(run=killed,TimeoutExpired=subprocess.TimeoutExpired)):
     try:answer=adapter.call(config,['correct','-expected-version','1','--',fact_id,'Prefer clear explicit recovery guidance.'],str(Path(cfg['binary']).parent))
     except adapter.AdapterError as e:answer=str(e)
   finally:os.close(reader);os.close(writer)
   self.assertEqual(observations,['1,2',-9])
   self.assertRegex(answer.lower(),r'unknown.{0,20}outcome|ambiguous','native signal after committed mutation must be UNKNOWN OUTCOME')
   self.assertIn(fact_id,answer);self.assertIn('history',answer.lower())

if __name__=='__main__':unittest.main()
