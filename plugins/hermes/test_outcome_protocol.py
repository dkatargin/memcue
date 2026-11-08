"""Actual caller/native/PostgreSQL completion boundaries; no invented app result."""
import importlib.util,json,os,subprocess,sys,types,unittest
from pathlib import Path
from unittest.mock import patch

class OutcomeCompletion(unittest.TestCase):
 def test_mutation_completion_requires_whole_outcome_receipt(self):
  if not os.environ.get('MEMCUE_RESPONSE_FIXTURE'):self.skipTest('isolated native/PostgreSQL fixture required')
  path=Path(os.environ['MEMCUE_RESPONSE_FIXTURE']);cfg=json.loads(path.read_text())
  env={k:v for k,v in os.environ.items() if not k.startswith(('PG','MEMCUE_','CLAUDE_'))};env.update(cfg['native_env'])
  sys.path.insert(0,cfg['hermes_distribution'])
  def load(name,p):
   spec=importlib.util.spec_from_file_location(name,p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
  hermes=load('protocol_hermes',Path(__file__).parent/'memcue/__init__.py');codex=load('protocol_codex',Path(__file__).parents[1]/'codex/scripts/memcue.py')
  provider=hermes.MemcueMemoryProvider({'binary':cfg['binary'],'dream':False})
  config={'binary':cfg['binary'],'facts':cfg['binary']+'.absent','state_dir':cfg['binary']+'.codex','host':'synthetic'}
  real_run=subprocess.run
  def sql(query):
   r=real_run([cfg['psql'],'-XAt','-v','ON_ERROR_STOP=1','-c',query],env=dict(env,**cfg['psql_env']),capture_output=True,text=True,timeout=10)
   self.assertEqual(r.returncode,0);return r.stdout.strip()
  records=[]
  for caller in ('hermes','codex'):
   for fault in ('missing-error','partial-error','batch-prefix'):
    with self.subTest(caller=caller,fault=fault),patch.dict(os.environ,env,clear=True):
     seed=real_run([cfg['binary'],'add','-source','user','--','Prefer precise completion receipts.'],env=env,capture_output=True,text=True,timeout=7)
     self.assertEqual(seed.returncode,0);fact_id=seed.stdout.strip()
     count,size=map(int,sql('SELECT count(*),coalesce(sum(octet_length(payload::text)),0) FROM memcue.facts').split('|'));self.assertLess(count,100000);self.assertLess(size,64<<20)
     batch=path.parent/(caller+'-batch.json');batch.write_text(json.dumps([{'Content':'Prefer concise complete receipts.','Source':'user'},{'Content':'Prefer explicit safe recovery.','Source':'user'}]))
     args=['add','-batch',str(batch)] if fault=='batch-prefix' else ['correct','-expected-version','1','--',fact_id,'Prefer precise complete outcome receipts.']
     calls=[];native=[]
     def lose(argv,**kw):
      calls.append(argv[1]);is_hermes='capture_output' in kw
      if is_hermes:kw.pop('capture_output')
      out_file=kw.pop('stdout',None);err_file=kw.pop('stderr',None)
      if fault=='batch-prefix':
       kw.update(stdout=subprocess.PIPE,stderr=subprocess.PIPE);r=real_run(argv,**kw)
       out=r.stdout if isinstance(r.stdout,str) else r.stdout.decode();err=r.stderr if isinstance(r.stderr,str) else r.stderr.decode()
       self.assertEqual(r.returncode,0);self.assertEqual(len(out.splitlines()),2)
       delivered=out.splitlines(keepends=True)[0];delivered_err=err
      else:
       rd,wr=os.pipe();os.close(rd)
       try:r=real_run(argv,stdout=wr,stderr=subprocess.PIPE,**kw)
       finally:os.close(wr)
       out='';err=r.stderr if isinstance(r.stderr,str) else r.stderr.decode();self.assertNotEqual(r.returncode,0);self.assertIn('UNKNOWN OUTCOME',err)
       delivered='';delivered_err='' if fault=='missing-error' else err[:12]
      native.append({'exit':r.returncode,'error_bytes':len(err),'delivered_error_bytes':len(delivered_err),'delivered_output_lines':len(delivered.splitlines())})
      if is_hermes:return subprocess.CompletedProcess(argv,r.returncode,delivered,delivered_err)
      out_file.write(delivered.encode());err_file.write(delivered_err.encode());return subprocess.CompletedProcess(argv,r.returncode)
     module=hermes if caller=='hermes' else codex
     with patch.object(module,'subprocess',types.SimpleNamespace(run=lose,TimeoutExpired=subprocess.TimeoutExpired)):
      if caller=='hermes':ok,answer=provider._run(args)
      else:
       try:answer=codex.call(config,args,str(path.parent));ok=True
       except codex.AdapterError as e:answer=str(e);ok=False
     if fault=='batch-prefix':self.assertEqual(int(sql('SELECT count(*) FROM memcue.facts')),count+2)
     else:self.assertEqual(sql("SELECT string_agg(version::text,',' ORDER BY version) FROM memcue.facts WHERE id='"+fact_id+"'"),'1,2')
     self.assertEqual(calls,[args[0]])
     records.append({'caller':caller,'fault':fault,'native':native,'ok':ok})
     (path.parent/'protocol-observation.json').write_text(json.dumps(records,indent=2))
     self.assertFalse(ok,'incomplete mutation receipt must never be success')
     self.assertIn('UNKNOWN OUTCOME',answer,'no complete refusal evidence: mutation outcome must remain UNKNOWN')
     self.assertIn('history',answer.lower());self.assertNotIn(cfg['password'],answer)

if __name__=='__main__':unittest.main()
