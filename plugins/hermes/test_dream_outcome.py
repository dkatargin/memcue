"""Model-free local prepare/apply, genuine durable history and lost receipts."""
import importlib.util,json,os,subprocess,sys,tempfile,types,unittest
from pathlib import Path
from unittest.mock import patch

class DreamOutcome(unittest.TestCase):
 def test_local_apply_reports_uncertainty_after_fact_change(self):
  binary=os.environ.get('MEMCUE_BIN')
  if not binary:self.skipTest('built native binary required')
  if os.environ.get('MEMCUE_HERMES_DISTRIBUTION'):
   sys.path.insert(0,os.environ['MEMCUE_HERMES_DISTRIBUTION'])
  def load(name,path):
   s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
  hermes=load('dream_hermes',Path(__file__).parent/'memcue/__init__.py');codex=load('dream_codex',Path(__file__).parents[1]/'codex/scripts/memcue.py')
  real_run=subprocess.run
  for caller,mode in [('native','closed'),('codex','empty'),('hermes','complete')]:
   with self.subTest(caller=caller,mode=mode),tempfile.TemporaryDirectory(prefix='dream-outcome-') as tmp:
    root=Path(tmp);facts=root/'facts.db';state=root/'state'
    env={k:v for k,v in os.environ.items() if not k.startswith(('MEMCUE_','PG','CLAUDE_'))};env.update(HOME=tmp,HERMES_HOME=tmp,MEMCUE_FACTS=str(facts),MEMCUE_STATE_DIR=str(state),MEMCUE_DREAM_BACKGROUND='0',MEMCUE_AUTO_INSTALL='0')
    def native(args):
     r=real_run([binary,*args],env=env,capture_output=True,text=True,timeout=8);self.assertEqual(r.returncode,0,r.stderr[:160]);return r.stdout
    ids=[native(['add','-source','user','--',text]).strip() for text in ['Synthetic review workflow subscribes the review bot to every repository except forks and archives.','Synthetic review workflow subscribes the review bot to all repositories except forks and archives.','Synthetic review workflow subscribes the review bot to repositories except all forks and archives.']]
    native(['dream','-prepare','-all']);packet=json.loads((state/'dream.packet.json').read_text())
    self.assertTrue(any(all(i in g for i in ids) for g in packet['groups']))
    answer={'packet':packet['id'],'actions':[{'op':'retire','id':ids[1],'by':ids[0],'kind':'duplicate','reason':'synthetic duplicate control'},{'op':'retire','id':ids[2],'by':ids[0],'kind':'duplicate','reason':'synthetic second duplicate control'}]}
    answer_file=root/'answer.json';answer_file.write_text(json.dumps(answer))
    args=['dream','-apply',str(answer_file)];calls=[]
    def lost(argv,**kw):
     calls.append(argv[1]);out=kw.pop('stdout',None);err=kw.pop('stderr',None);kw.pop('capture_output',None)
     r=real_run(argv,stdout=subprocess.PIPE,stderr=subprocess.PIPE,**kw)
     self.assertEqual(r.returncode,0)
     if out is not None:err.write(r.stderr);return subprocess.CompletedProcess(argv,r.returncode)
     return subprocess.CompletedProcess(argv,r.returncode,'',r.stderr)
    with patch.dict(os.environ,env,clear=True):
     if caller=='native':
      rd,wr=os.pipe();os.close(rd)
      try:r=real_run([binary,*args],env=env,stdout=wr,stderr=subprocess.PIPE,text=True,timeout=8)
      finally:os.close(wr)
      ok=False;result=r.stderr;self.assertNotEqual(r.returncode,0)
     elif caller=='codex':
      config={'binary':binary,'facts':str(facts),'state_dir':str(state),'host':'synthetic'}
      with patch.object(codex,'subprocess',types.SimpleNamespace(run=lost,TimeoutExpired=subprocess.TimeoutExpired)):
       try:result=codex.call(config,args,tmp);ok=True
       except codex.AdapterError as e:result=str(e);ok=False
     else:
      provider=hermes.MemcueMemoryProvider({'binary':binary,'facts':str(facts),'dream':False})
      result=provider.handle_tool_call('memcue_dream_apply',{'answer':json.dumps(answer)});ok='error' not in json.loads(result)
    history=json.loads(native(['history','-json',ids[1]]));self.assertEqual([r['Version'] for r in history],[1,2]);self.assertEqual(history[-1]['Status'],'retired')
    remaining=json.loads(native(['history','-json',ids[2]]));self.assertEqual(len(remaining),1 if mode=='closed' else 2,'closed output must demonstrate partial multi-operation apply')
    if mode=='complete':self.assertTrue(ok,'complete local apply must remain successful')
    else:
     self.assertFalse(ok,'lost apply receipt must not be success');self.assertIn('UNKNOWN OUTCOME',result,'local fact apply committed before lost response')

if __name__=='__main__':unittest.main()
