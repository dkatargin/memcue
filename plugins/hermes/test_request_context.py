"""Real released normal-plugin discovery and request dispatch; synthetic storage only."""
import os,sys,json,tempfile,subprocess,shutil,unittest,copy
from pathlib import Path
if os.environ.get('MEMCUE_HERMES_DISTRIBUTION'):
 sys.path.insert(0,os.environ['MEMCUE_HERMES_DISTRIBUTION'])
ROOT=Path(__file__).resolve().parent
class RequestContext(unittest.TestCase):
 def test_actual_normal_activation_and_same_turn_cwd(self):
  binary=os.environ['MEMCUE_BIN']
  with tempfile.TemporaryDirectory(prefix='memcue-request-') as tmp:
   home=Path(tmp)
   env=dict(os.environ)
   for k in list(env):
    if k.startswith(('MEMCUE_','CLAUDE_','ANTHROPIC_')):env.pop(k)
   env.update(HOME=tmp,HERMES_HOME=tmp,XDG_STATE_HOME=str(home/'state'),XDG_CONFIG_HOME=str(home/'config'),MEMCUE_FACTS=str(home/'facts'),MEMCUE_STATE_DIR=str(home/'native-state'),MEMCUE_DREAM_BACKGROUND='0',MEMCUE_AUTO_INSTALL='0',GIT_CONFIG_GLOBAL='/dev/null',GIT_CONFIG_SYSTEM='/dev/null',GIT_CONFIG_NOSYSTEM='1')
   from unittest.mock import patch
   with patch.dict(os.environ,env,clear=True):
    for name in ('memcue','memcue-context'):shutil.copytree(ROOT/name,home/'plugins'/name)
    (home/'config.yaml').write_text('memory:\n  provider: memcue\n  memcue:\n    binary: '+json.dumps(binary)+'\n    dream: false\nplugins:\n  enabled: [memcue-context]\n')
    from hermes_cli.plugins import get_plugin_manager
    from hermes_cli.middleware import apply_llm_request_middleware
    from plugins.memory import load_memory_provider
    from agent.runtime_cwd import set_session_cwd,clear_session_cwd
    manager=get_plugin_manager();manager.discover_and_load(force=True)
    provider=load_memory_provider('memcue')
    self.assertIsNotNone(provider)
    provider.initialize('owned-session',hermes_home=tmp,cwd=tmp,agent_context='primary')
    repos=[]
    for i in range(2):
     repo=home/str(i);subprocess.run(['git','init','-q',str(repo)],check=True)
     subprocess.run(['git','-C',str(repo),'remote','add','origin',f'https://example.invalid/{i}.git'],check=True)
     subprocess.run([binary,'add','-cwd',str(repo),'-kind','pitfall','-scope','repo','--',f'Failure-{i} cause; full workaround.'],check=True,stdout=subprocess.DEVNULL)
     repos.append(repo)
    provider.initialize('owned-session',hermes_home=tmp,cwd=str(repos[0]),agent_context='primary')
    token=set_session_cwd(str(repos[0]))
    try:
     self.assertNotIn('Failure-0 cause;',provider.system_prompt_block(),'middleware mode duplicated facts in cached system prompt')
     self.assertEqual(provider.prefetch('ok',session_id='owned-session'),'','middleware mode duplicated turn-entry delivery')
    finally:clear_session_cwd()
    for key in ('messages','input'):

     request={key:[{'role':'user','content':'ok'}]}
     original=copy.deepcopy(request)
     for i,repo in enumerate(repos):
      token=set_session_cwd(str(repo))
      try:result=apply_llm_request_middleware(request,session_id='owned-session',turn_id='same-turn',api_mode='chat' if key=='messages' else 'codex_responses')
      finally:clear_session_cwd()
      text=json.dumps(result.payload,ensure_ascii=False)
      self.assertIn(f'Failure-{i} cause; full workaround.',text,'per-request middleware omitted actual cwd pitfalls in the same turn')
      self.assertNotIn(f'Failure-{1-i} cause;',text)
      self.assertEqual(request,original)
     token=set_session_cwd(str(repos[1]))
     try:
      retry=apply_llm_request_middleware(result.payload,session_id='owned-session',turn_id='same-turn',api_mode='chat')
      self.assertEqual(retry.payload,result.payload,'retry duplicated transient repository context')
     finally:clear_session_cwd()
     # Accepted transformed-request extension: native retries normally use fresh kwargs.
     # Provenance must survive the released dispatcher's deep copies, outside model JSON.
     token=set_session_cwd(str(repos[0]))
     try:
      reused=copy.deepcopy(result.payload)
      before=copy.deepcopy(reused)
      changed=apply_llm_request_middleware(reused,session_id='owned-session',api_mode='chat' if key=='messages' else 'codex_responses').payload
      self.assertNotIn('Failure-1 cause;',json.dumps(changed),'transformed retry retained stale owned repo-B snapshot')
      self.assertIn('Failure-0 cause;',json.dumps(changed))
      self.assertEqual(changed[key][:-1],request[key])
      self.assertEqual(reused,before,'transformed input was mutated')
      self.assertEqual(set(changed),set(request),'private request metadata escaped')
      with patch.object(provider,'_run',return_value=(False,'synthetic snapshot read failure')):
       failed=apply_llm_request_middleware(reused,session_id='owned-session',api_mode='chat' if key=='messages' else 'codex_responses').payload
      self.assertNotIn('Failure-1 cause;',json.dumps(failed),'failed transformed retry retained prior owned facts')
      self.assertIn('unavailable',json.dumps(failed))
      self.assertEqual(failed[key][:-1],request[key])
      recovered=apply_llm_request_middleware(failed,session_id='owned-session',api_mode='chat' if key=='messages' else 'codex_responses').payload
      self.assertEqual(recovered,changed,'successful retry did not recover one fresh snapshot')
      self.assertEqual(reused,before)

      # Identical ordinary framing/text is not provenance, including the last item.
      ordinary=copy.deepcopy(dict(changed[key][-1]))
      if key=='messages':
       history=[{'role':'user','content':ordinary['content']},ordinary,{'role':'assistant','content':None,'tool_calls':[{'id':'same','type':'function','function':{'name':'terminal','arguments':'{}'}}]},{'role':'tool','tool_call_id':'same','content':ordinary['content']},copy.deepcopy(ordinary)]
      else:
       history=[{'type':'message','role':'user','content':copy.deepcopy(ordinary['content'])},ordinary,{'type':'function_call','call_id':'same','name':'terminal','arguments':'{}'},{'type':'function_call_output','call_id':'same','output':json.dumps(ordinary['content'])},copy.deepcopy(ordinary)]
      ordinary_request={key:history};ordinary_before=copy.deepcopy(ordinary_request)
      ordinary_sent=apply_llm_request_middleware(ordinary_request,session_id='owned-session',api_mode='chat' if key=='messages' else 'codex_responses').payload
      self.assertEqual(ordinary_sent[key][:-1],history,'ordinary identical text was mistaken for owned transient context')
      self.assertEqual(ordinary_request,ordinary_before)
      self.assertEqual(json.loads(json.dumps(ordinary_sent)),{key:[*history,dict(changed[key][-1])]},'private marker serialized to provider')
     finally:clear_session_cwd()
     unrelated=apply_llm_request_middleware(request,session_id='unrelated',api_mode='chat')
     self.assertEqual(unrelated.payload,request)
    # Protocol and failure controls run through the real released dispatcher.
    from unittest.mock import patch
    token=set_session_cwd(str(repos[0]))
    try:
     protocol={'messages':[{'role':'system','content':'original system'},{'role':'user','content':'ok'},{'role':'assistant','content':None,'tool_calls':[{'id':'call-1','type':'function','function':{'name':'terminal','arguments':'{}'}}]},{'role':'tool','tool_call_id':'call-1','content':'original tool output'}]}
     sent=apply_llm_request_middleware(protocol,session_id='owned-session',api_mode='chat').payload
     self.assertEqual(sent['messages'][:-1],protocol['messages'])
     self.assertEqual(sent['messages'][-1]['role'],'developer')
     response={'input':[{'type':'function_call','call_id':'call-1','name':'terminal','arguments':'{}'},{'type':'function_call_output','call_id':'call-1','output':'original function output'}]}
     sent=apply_llm_request_middleware(response,session_id='owned-session',api_mode='codex_responses').payload
     self.assertEqual(sent['input'][:-1],response['input'])
     with patch.object(provider,'_run',return_value=(False,'synthetic transport failure')):
      failed=apply_llm_request_middleware({'messages':[]},session_id='owned-session',api_mode='chat').payload
      self.assertIn('unavailable',json.dumps(failed));self.assertNotIn('Failure-0 cause;',json.dumps(failed))
     provider.on_pre_compress([])
     recovered=apply_llm_request_middleware({'messages':[]},session_id='owned-session',api_mode='chat').payload
     self.assertIn('Failure-0 cause;',json.dumps(recovered))
     sub=load_memory_provider('memcue');sub.initialize('sub-session',hermes_home=tmp,agent_context='subagent')
     self.assertEqual(apply_llm_request_middleware({'messages':[]},session_id='sub-session',api_mode='chat').payload,{'messages':[]})
     config=(home/'config.yaml').read_text()
     (home/'config.yaml').write_text(config.replace('provider: memcue','provider: builtin'))
     self.assertEqual(apply_llm_request_middleware({'messages':[]},session_id='owned-session',api_mode='chat').payload,{'messages':[]})
     (home/'config.yaml').write_text(config.replace('enabled: [memcue-context]','enabled: []'))
     manager.discover_and_load(force=True)
     self.assertEqual(apply_llm_request_middleware({'messages':[]},session_id='owned-session',api_mode='chat').payload,{'messages':[]})
     (home/'config.yaml').write_text(config);manager.discover_and_load(force=True)
    finally:clear_session_cwd()
    token=set_session_cwd(str(repos[0]))
    def revoke_during_read(*args,**kwargs):
     provider.on_session_switch('during-read')
     return True,json.dumps({'context':'Revoked snapshot','facts':['Revoked failure; full workaround.']})
    try:
     with patch.object(provider,'_run',side_effect=revoke_during_read):
      revoked=apply_llm_request_middleware({'messages':[]},session_id='owned-session',api_mode='chat')
      self.assertEqual(revoked.payload,{'messages':[]},'ownership revoked during native I/O still injected facts')
    finally:provider.on_session_switch('owned-session');clear_session_cwd()
    # Another active profile with the same session/repository identity must retain its own base.
    from hermes_constants import set_hermes_home_override,reset_hermes_home_override
    other=home/'profile-b';other.mkdir()
    for name in ('memcue','memcue-context'):shutil.copytree(ROOT/name,other/'plugins'/name)
    (other/'config.yaml').write_text('memory:\n  provider: memcue\n  memcue:\n    binary: '+json.dumps(binary)+'\n    facts: '+json.dumps(str(other/'facts'))+'\n    dream: false\nplugins:\n  enabled: [memcue-context]\n')
    subprocess.run([binary,'add','-cwd',str(repos[0]),'-kind','pitfall','-scope','repo','--','Profile-B-only cause; private synthetic workaround.'],env=dict(env,MEMCUE_FACTS=str(other/'facts'),MEMCUE_STATE_DIR=str(other/'native-state')),check=True,stdout=subprocess.DEVNULL)
    profile_token=set_hermes_home_override(other)
    cwd_token=set_session_cwd(str(repos[0]))
    try:
     other_provider=load_memory_provider('memcue');other_provider.initialize('owned-session',hermes_home=str(other),agent_context='primary')
     b=apply_llm_request_middleware({'messages':[]},session_id='owned-session',api_mode='chat')
     self.assertIn('Profile-B-only cause;',json.dumps(b.payload))
     self.assertNotIn('Failure-0 cause;',json.dumps(b.payload),'profile A facts leaked through shared native state')
    finally:reset_hermes_home_override(profile_token);clear_session_cwd()
    token=set_session_cwd(str(repos[0]))
    try:
     a=apply_llm_request_middleware({'messages':[]},session_id='owned-session',api_mode='chat')
     self.assertNotIn('Profile-B-only cause;',json.dumps(a.payload),'profile B facts leaked into profile A')
    finally:clear_session_cwd()
    provider.on_session_switch('rotated-session')
    token=set_session_cwd(str(repos[0]))
    try:
     rotated=apply_llm_request_middleware({'messages':[]},session_id='rotated-session',api_mode='chat')
     self.assertIn('Failure-0 cause;',json.dumps(rotated.payload),'rotated provider ownership lost automatic context')
     self.assertEqual(apply_llm_request_middleware({'messages':[]},session_id='owned-session',api_mode='chat').payload,{'messages':[]})
     provider.shutdown()
     self.assertEqual(apply_llm_request_middleware({'messages':[]},session_id='rotated-session',api_mode='chat').payload,{'messages':[]})
    finally:clear_session_cwd()
if __name__=='__main__':unittest.main()
