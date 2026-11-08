"""A real inherited stdout pipe must obey the CLI's unchanged invocation budget."""
import json,os,subprocess,unittest
from pathlib import Path

class NativeStdoutDeadline(unittest.TestCase):
 def test_committed_native_stdout_wait_is_bounded_and_unknown(self):
  if not os.environ.get('MEMCUE_RESPONSE_FIXTURE'):self.skipTest('isolated fixture required')
  config_path=Path(os.environ['MEMCUE_RESPONSE_FIXTURE']);cfg=json.loads(config_path.read_text())
  env={k:v for k,v in os.environ.items() if not k.startswith(('PG','MEMCUE_','CLAUDE_'))};env.update(cfg['native_env'])
  seed=subprocess.run([cfg['binary'],'add','-source','user','--','Prefer bounded response delivery for review explanations.'],env=env,capture_output=True,text=True,timeout=7)
  self.assertEqual(seed.returncode,0);fact_id=seed.stdout.strip()
  reader,writer=os.pipe();os.set_blocking(writer,False)
  try:
   while True:os.write(writer,b'x'*4096)
  except BlockingIOError:pass
  os.set_blocking(writer,True)
  completed=True
  child=subprocess.Popen([cfg['binary'],'correct','-expected-version','1','--',fact_id,'Prefer bounded response delivery with clear recovery instructions.'],env=env,stdout=writer,stderr=subprocess.PIPE,text=True)
  try:
   try:_,stderr=child.communicate(timeout=6)
   except subprocess.TimeoutExpired:
    completed=False;child.kill();_,stderr=child.communicate()
  finally:os.close(reader);os.close(writer)
  observed=subprocess.run([cfg['psql'],'-XAt','-c',"SELECT string_agg(version::text,',' ORDER BY version) FROM memcue.facts WHERE id='"+fact_id+"'"],env=dict(env,**cfg['psql_env']),capture_output=True,text=True,timeout=7)
  self.assertEqual(observed.returncode,0);self.assertEqual(observed.stdout.strip(),'1,2','must be a committed correction before the deadline oracle')
  (config_path.parent/'stdout-deadline.json').write_text(json.dumps({'completed_within_six_seconds':completed,'native_exit':child.returncode,'stderr':stderr,'durable_versions':'1,2'}))
  self.assertTrue(completed,'committed CLI must stop waiting on inherited stdout when its four-second invocation deadline expires')
  self.assertNotEqual(child.returncode,0);self.assertIn('UNKNOWN OUTCOME',stderr);self.assertIn(fact_id,stderr)

if __name__=='__main__':unittest.main()
