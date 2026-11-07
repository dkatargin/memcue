"""Isolated real CLI scenarios; synthetic facts, no model or live configuration."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


class Pull(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR', Path(__file__).resolve().parents[1]/'bin'))
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = self.root/'repo'
        (self.repo/'.git').mkdir(parents=True)
        (self.repo/'.git/config').write_text('[remote "origin"]\nurl = https://synthetic.invalid/orchard.git\n')
        self.env = {k:v for k,v in os.environ.items() if not k.startswith(('MEMCUE_', 'CLAUDE_'))}
        self.env.update(MEMCUE_FACTS=str(self.root/'facts'), MEMCUE_STATE_DIR=str(self.root/'state'),
                        MEMCUE_HOST='synthetic', HOME=str(self.root), MEMCUE_DREAM_BACKGROUND='0',
                        GIT_CONFIG_GLOBAL='/dev/null', GIT_CONFIG_NOSYSTEM='1')
        self.bin = os.environ['MEMCUE_BIN']

    def cli(self, *args):
        r = subprocess.run([self.bin,*args], env=self.env, cwd=self.repo, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def add(self, text, kind='pitfall', *args):
        return self.cli('add','-kind',kind,'-source','tool','-scope','repo',*args,'--',text).strip()

    def pull(self, *args):
        raw = self.cli('pre-command','-cwd',str(self.repo),'-session','task-1','-action','build',*args,'orchard build')
        self.assertLessEqual(len(raw.encode()),4096)
        return json.loads(raw)

    def acknowledge(self, packet, *args):
        self.assertTrue(packet['blocked'])
        return self.pull('-ack',packet['receipt'],*args)

    def test_acknowledgment_replay_and_stale_metadata(self):
        fact=self.add('Orchard build requires amber mode only for synthetic fixtures.')
        first=self.pull()
        retry=self.pull()
        self.assertEqual(retry['facts'],first['facts'])
        self.assertEqual(retry['receipt'],first['receipt'])
        self.assertLess(retry['remaining_bytes'],first['remaining_bytes'])
        self.cli('correct',fact,'Orchard build requires violet mode only for synthetic fixtures.')
        changed=self.acknowledge(first)
        self.assertTrue(changed['blocked'])
        self.assertIn('violet mode',changed['facts'][0]['content'])
        self.assertNotEqual(changed['receipt'],first['receipt'])
        ready=self.acknowledge(changed)
        self.assertFalse(ready['blocked'])
        self.assertEqual(ready['facts'],[])
        self.assertFalse(self.acknowledge(changed)['blocked']) # same acknowledgment is idempotent
        self.assertEqual(self.pull()['facts'],[])

    def test_failed_ack_save_cannot_suppress_unacknowledged_facts(self):
        self.add('Orchard build requires amber mode only for synthetic fixtures.')
        first=self.pull()
        guard=self.root/'state/pre-command.json.new'
        guard.mkdir()
        result=subprocess.run([self.bin,'pre-command','-cwd',str(self.repo),'-session','task-1',
                               '-action','build','-ack',first['receipt'],'orchard build'],
                              env=self.env,capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0)
        self.assertEqual(result.stdout,'')
        guard.rmdir()
        replay=self.pull()
        self.assertEqual(replay['facts'],first['facts'])
        self.assertTrue(replay['blocked'])
        self.assertFalse(self.acknowledge(replay)['blocked'])

    def test_lost_acknowledgment_response_is_idempotent(self):
        import sys
        self.add('Orchard build requires amber mode only for synthetic fixtures.')
        first=self.pull()
        wrapper=self.root/'delay-ack.py'
        wrapper.write_text('import subprocess,sys,time\np=subprocess.run(sys.argv[1:])\n'
                           'if p.returncode==0: time.sleep(1)\nsys.exit(p.returncode)\n')
        args=['pre-command','-cwd',str(self.repo),'-session','task-1','-action','build',
              '-ack',first['receipt'],'orchard build']
        with self.assertRaises(subprocess.TimeoutExpired):
            subprocess.run([sys.executable,str(wrapper),self.bin,*args],env=self.env,
                           capture_output=True,text=True,timeout=0.3)
        ready=self.acknowledge(first)
        self.assertFalse(ready['blocked'])
        self.assertEqual(ready['facts'],[])
        compact=self.pull('-epoch','compact-1')
        self.assertTrue(compact['blocked'])
        self.assertTrue(compact['facts'])
        self.assertLess(compact['remaining_bytes'],ready['remaining_bytes']-2048)

    def test_receipt_is_bound_to_request_and_legacy_counters_survive(self):
        self.add('Orchard build requires amber mode only for synthetic fixtures.')
        packet=self.pull()
        result=subprocess.run([self.bin,'pre-command','-cwd',str(self.repo),'-session','task-1',
                               '-action','other','-ack',packet['receipt'],'orchard build'],
                              env=self.env,capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0)
        self.assertEqual(result.stdout,'')
        self.assertFalse(self.acknowledge(packet)['blocked'])
        path=self.root/'state/pre-command.json'
        state=json.loads(path.read_text())
        spent=next(iter(state['tasks'].values()))['spent']
        state.pop('version') # simulate the old CLI-output-based seen format
        path.write_text(json.dumps(state))
        migrated=self.pull()
        self.assertTrue(migrated['facts'])
        current=json.loads(path.read_text())
        self.assertGreater(next(iter(current['tasks'].values()))['spent'],spent)

    def test_explicit_scope_overrides_matching_origin(self):
        with (self.repo/'.git/config').open('a') as config:
            config.write('[remote "upstream"]\nurl = https://synthetic.invalid/upstream.git\n')
        allowed=set()
        foreign=set()
        for scope in ('repo:synthetic.invalid/other','host:other','service:other'):
            foreign.add(self.add('Orchard build scoped qualification.', 'pitfall','-scope',scope))
        for scope in ('repo:synthetic.invalid/other','host:other'):
            foreign.add(self.add('Orchard build scoped qualification.', 'pitfall','-scope',scope,
                                    '-origin','_global 2026-01-01'))
        for scope in ('repo:synthetic.invalid/orchard','repo:synthetic.invalid/upstream','host:synthetic','global'):
            allowed.add(self.add('Orchard build scoped qualification.', 'pitfall','-scope',scope,
                                    '-origin','synthetic.invalid/elsewhere 2026-01-01'))
        ordinary=json.loads(self.cli('search','-json','-n','100','-min-score','0','orchard build'))
        self.assertTrue(foreign.issubset({f['id'] for f in ordinary['facts']}))
        packet=self.pull()
        self.assertEqual({f['id'] for f in packet['facts']},allowed)

    def test_state_save_failure_exposes_no_packet_on_retries(self):
        self.add('Orchard build requires amber mode only on synthetic fixtures.')
        state=self.root/'state'
        state.mkdir(exist_ok=True)
        (state/'pre-command.json.new').mkdir()
        attempts=0
        exposed=0
        for _ in range(44):
            result=subprocess.run([self.bin,'pre-command','-cwd',str(self.repo),'-session','task-1',
                                   '-action','build','orchard build'],env=self.env,capture_output=True,text=True)
            attempts+=1
            exposed+=len(result.stdout.encode())
            self.assertNotEqual(result.returncode,0)
            self.assertEqual(result.stdout,'','packet escaped before accounting reservation')
        print('PERSISTENCE_RETRY_TRACE '+json.dumps({'attempts':attempts,'packet_bytes':exposed}))

    def test_lost_transport_replays_whole_facts_with_a_bound(self):
        import sys
        fact=self.add('Orchard build needs amber mode; only for synthetic fixtures.')
        wrapper=self.root/'delayed.py'
        wrapper.write_text('import subprocess,sys,time\np=subprocess.run(sys.argv[1:])\n'
                           'if p.returncode==0: time.sleep(1)\nsys.exit(p.returncode)\n')
        args=['pre-command','-cwd',str(self.repo),'-session','task-1','-action','build','orchard build']
        with self.assertRaises(subprocess.TimeoutExpired) as lost:
            subprocess.run([sys.executable,str(wrapper),self.bin,*args],env=self.env,
                           capture_output=True,text=True,timeout=0.3)
        raw=self.cli(*args)
        retry=json.loads(raw)
        self.assertIn(fact,[f['id'] for f in retry['facts']], 'successful CLI output was not host delivery')
        self.assertTrue(retry['blocked'],'unacknowledged delivery cannot approve execution')
        self.assertIn('only for synthetic fixtures.',retry['facts'][0]['content'])
        total=len(lost.exception.stdout or b'')+len(raw.encode())
        for _ in range(100):
            result=subprocess.run([self.bin,*args],env=self.env,capture_output=True,text=True)
            total+=len(result.stdout.encode())
            if result.returncode:
                self.assertEqual(result.stdout,'')
                self.assertIn('budget exhausted',result.stderr)
                break
            packet=json.loads(result.stdout)
            self.assertTrue(packet['blocked'])
            if packet['facts']:
                self.assertIn(fact,[f['id'] for f in packet['facts']])
            else:
                self.assertGreater(packet['omitted'],0) # explicit budget overflow, still blocked
        else:
            self.fail('unacknowledged retries escaped the cumulative cap')
        state=json.loads((self.root/'state/pre-command.json').read_text())
        spent=next(iter(state['tasks'].values()))['spent']
        self.assertLessEqual(total,16384-2048)
        self.assertLessEqual(total+2048,spent)
        self.assertLessEqual(spent,16384)
        print('REPLAY_BUDGET_TRACE '+json.dumps({'packet_bytes':total,'reserved_bytes':spent}))

    def test_before_action_and_repeat(self):
        rule=self.add('Orchard review requires an amber label.', 'rule')
        pit=self.add('Orchard build needs ORCHARD_SAFE=1; only in synthetic fixtures.')
        start=json.loads(self.cli('search','-json','-kind','rule,decision','orchard'))
        self.assertEqual([f['id'] for f in start['facts']],[rule])
        first=self.pull()
        self.assertIn(pit,[f['id'] for f in first['facts']])
        ready=self.acknowledge(first)
        self.assertFalse(ready['blocked'])
        # A real local command consumes the delivered qualification before execution.
        env=dict(self.env, ORCHARD_SAFE='1' if 'only in synthetic fixtures' in str(first) else '0')
        r=subprocess.run(['sh','-c','test "$ORCHARD_SAFE" = 1'],env=env)
        print('SYNTHETIC_TRACE '+json.dumps({'task_start':start,'pre_command':first,'acknowledged':ready,
              'action_argv':['sh','-c','test "$ORCHARD_SAFE" = 1'], 'action_exit':r.returncode}))
        self.assertEqual(r.returncode,0)
        self.assertEqual(self.pull()['facts'],[])

    def test_operating_kinds_preserve_full_qualifications(self):
        ids=[]
        for kind in ('rule','decision','pitfall','environment','procedure'):
            ids.append(self.add('Orchard build '+kind+' applies only to synthetic fixtures; require amber mode.',kind))
        packet=self.pull()
        self.assertTrue(packet['blocked'])
        self.assertFalse(self.acknowledge(packet)['blocked'])
        self.assertEqual({f['id'] for f in packet['facts']},set(ids))
        for fact in packet['facts']:
            self.assertIn('only to synthetic fixtures; require amber mode.',fact['content'])

    def test_metadata_correction_is_delivered_again(self):
        content='Orchard build requires amber mode only in synthetic fixtures.'
        fact=self.add(content,'pitfall','-expires','2099-12-31')
        initial=self.pull()
        self.assertEqual(initial['facts'][0]['expires'],'2099-12-31')
        self.acknowledge(initial)
        self.cli('correct','-expires','2098-12-31',fact,content)
        packet=self.pull()
        self.assertEqual([f['expires'] for f in packet['facts']],['2098-12-31'])

    def test_scope_worktree_retirement_and_compaction(self):
        pit=self.add('Orchard build requires a violet label.')
        first=self.pull()
        self.assertIn(pit,str(first))
        self.assertFalse(self.acknowledge(first)['blocked'])
        self.assertEqual(self.pull()['facts'],[])
        again=self.pull('-epoch','compact-1')
        self.assertIn(pit,str(again))
        self.assertLess(again['remaining_bytes'],first['remaining_bytes'])
        # Create a real Git linked worktree, rather than only imitating its metadata.
        def git(*args):
            result=subprocess.run(['git',*args],cwd=self.repo,env=self.env,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
        git('init','-q')
        git('-c','user.name=Synthetic','-c','user.email=synthetic@example.invalid',
            '-c','commit.gpgsign=false','-c','core.hooksPath=/dev/null',
            'commit','--allow-empty','-q','-m','synthetic')
        linked=self.root/'linked'
        git('remote','add','upstream','https://synthetic.invalid/upstream.git')
        alias=self.add('Orchard build alias requires amber mode.', 'pitfall',
                       '-scope','repo:synthetic.invalid/upstream','-origin','synthetic.invalid/elsewhere 2026-01-01')
        git('worktree','add','--detach',str(linked),'HEAD')
        linked_packet=self.pull('-cwd',str(linked))
        self.assertIn(pit,str(linked_packet))
        self.assertIn(alias,str(linked_packet))
        other=self.root/'other'
        (other/'.git').mkdir(parents=True)
        (other/'.git/config').write_text('[remote "origin"]\nurl = https://synthetic.invalid/other.git\n')
        self.assertNotIn(pit,str(self.pull('-cwd',str(other))))
        self.cli('observe-problem','-fact',pit,'-incident','synthetic-retired')
        self.cli('retire',pit)
        self.cli('retire',alias)
        expired=self.add('Orchard build expired workaround.', 'pitfall', '-expires','2000-01-01')
        self.cli('observe-problem','-fact',expired,'-incident','synthetic-expired')
        self.assertEqual(self.pull('-epoch','compact-2')['facts'],[])

    def test_whole_fact_overflow_and_accumulated_budget(self):
        large='Orchard build '+('qualification ' * 450)+'only for synthetic fixtures.'
        self.add(large)
        response=self.pull()
        self.assertTrue(response['blocked'])
        self.assertGreater(response['omitted'],0)
        self.assertEqual(response['facts'],[])
        for i in range(100):
            r=subprocess.run([self.bin,'pre-command','-cwd',str(self.repo),'-session','task-1',
                              '-action','build','orchard build'],env=self.env,capture_output=True,text=True)
            if r.returncode:
                self.assertIn('budget exhausted',r.stderr)
                break
        else:
            self.fail('repeated responses escaped accumulated budget')

    def test_observations_are_explicit_deduplicated_and_scope_cannot_be_bought(self):
        rare=self.add('Orchard build safe synthetic workaround.')
        other=self.add('Unrelated aquarium maintenance.')
        observed=set()
        for incident in ('one','one','two','three','four'):
            if incident not in observed:
                failure=subprocess.run(['sh','-c','exit 23'],env=self.env)
                self.assertEqual(failure.returncode,23)
                observed.add(incident)
            self.cli('observe-problem','-fact',other,'-incident',incident)
        self.assertIn(rare,str(self.pull()))
        self.assertNotIn(other,str(self.pull('-epoch','compact-1')))
        state=json.loads((self.root/'state/pre-command.json').read_text())
        self.assertEqual(len(state['incidents']),4)
        self.pull('-epoch','compact-2')
        self.assertEqual(len(json.loads((self.root/'state/pre-command.json').read_text())['incidents']),4)

    def test_incident_retries_do_not_refresh_age(self):
        import time
        fact=self.add('Orchard build requires amber mode.')
        self.cli('observe-problem','-fact',fact,'-incident','synthetic-one')
        path=self.root/'state/pre-command.json'
        state=json.loads(path.read_text())
        incident=next(iter(state['incidents'].values()))
        incident['at']=int(time.time())-100
        original=incident['at']
        path.write_text(json.dumps(state))
        self.cli('observe-problem','-fact',fact,'-incident','synthetic-one')
        self.assertEqual(next(iter(json.loads(path.read_text())['incidents'].values()))['at'],original)
        incident['at']=int(time.time())-91*86400
        path.write_text(json.dumps(state))
        self.pull()
        self.assertEqual(json.loads(path.read_text())['incidents'],{})


if __name__ == '__main__':
    unittest.main()
