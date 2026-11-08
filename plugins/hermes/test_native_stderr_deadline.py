"""A real inherited stdout pipe must obey the CLI's unchanged invocation budget."""
import json,os,subprocess,unittest
from pathlib import Path

class NativeStderrDeadline(unittest.TestCase):
 def test_committed_error_delivery_is_bounded_when_both_channels_fail(self):
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
  stdout_reader,stdout_writer=os.pipe();os.close(stdout_reader)
  completed=True
  child=subprocess.Popen([cfg['binary'],'correct','-expected-version','1','--',fact_id,'Prefer bounded error delivery after committed changes.'],env=env,stdout=stdout_writer,stderr=writer,text=True)
  try:
   try:child.wait(timeout=5.3)
   except subprocess.TimeoutExpired:
    completed=False;child.kill();child.wait(timeout=2)
  finally:os.close(reader);os.close(writer);os.close(stdout_writer)
  stderr=''
  observed=subprocess.run([cfg['psql'],'-XAt','-c',"SELECT string_agg(version::text,',' ORDER BY version) FROM memcue.facts WHERE id='"+fact_id+"'"],env=dict(env,**cfg['psql_env']),capture_output=True,text=True,timeout=7)
  self.assertEqual(observed.returncode,0);self.assertEqual(observed.stdout.strip(),'1,2','must be a committed correction before the deadline oracle')
  (config_path.parent/'stderr-deadline.json').write_text(json.dumps({'completed_within_six_seconds':completed,'native_exit':child.returncode,'stderr':stderr,'durable_versions':'1,2'}))
  self.assertTrue(completed,'committed CLI must bound error delivery on full inherited stderr within the aggregate budget')
  self.assertNotEqual(child.returncode,0)

if __name__=='__main__':unittest.main()
