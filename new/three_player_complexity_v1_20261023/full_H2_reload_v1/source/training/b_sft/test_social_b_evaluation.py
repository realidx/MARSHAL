from copy import deepcopy
import json
import unittest

from training.b_sft.social_b_curriculum import family, variants, split_families
from training.b_sft.social_b_evaluation import request, score_attempt, score_transition, summarize, SPEC
from training.b_sft.social_b_oracle import forward_fixture, VERSION, FAVORED_RULE


def task(tid,history,values):
    return dict(id=tid,family='same',input=dict(player=0,history=history,queries=[dict(player=1,goal=0)],game=dict(n_players=2),
        own_preferences=[1],public_type_catalogues={'0':[[1]],'1':[[1],[0],[-1]]},
        public_setup={'intervention_prefix':[]}, pending_offer=None,
        public_state=dict(current_proposer=0,round_robin=[0]*30,turn_index=len(history),commitments=[[0],[0]]),
        partner_model={'window_proposal_turns':2,'version':VERSION},favored_rule=FAVORED_RULE),
        gold=dict(judgments=[dict(player=1,goal=0,possible_preferences=values,favored=values[0] if len(values)==1 else 'undetermined')]),
        hidden_audit='SECRET_GOLD')


def completion(values):
    args=dict(judgments=[dict(player=1,goal=0,possible_preferences=values,favored=values[0] if len(values)==1 else 'undetermined')])
    return dict(finish_reason='stop',message=dict(role='assistant',content='My earlier judgment.',
        tool_calls=[dict(id='call_1',type='function',function=dict(name='SUBMIT_BELIEFS',arguments=json.dumps(args)))]))


class EvaluationTests(unittest.TestCase):
    def test_native_only_and_failure_accounting(self):
        t=task('a',[],['neutral'])
        good=score_attempt(t,completion(['neutral']))
        self.assertTrue(score_attempt(t,dict(raw_message=completion(['neutral'])['message'],finish_reason='stop'))['exact'])
        bad=score_attempt(t,dict(message=dict(content=json.dumps(completion(['neutral'])))))
        truncated=score_attempt(t,dict(completion(['neutral']),finish_reason='length'))
        infra=score_attempt(t,dict(status='infrastructure_failure'))
        self.assertEqual([x['status'] for x in (good,bad,truncated,infra)],['ok','format_failure','truncated','infrastructure_failure'])
        stats=summarize([bad,good,infra])
        self.assertEqual(stats['checkpoint_exact_rate'],.5)
        self.assertEqual(stats['statuses']['format_failure'],1)
        self.assertEqual(SPEC['baselines'],[])

    def test_wrong_previous_answer_can_recover_without_gold_feedback(self):
        a=task('a',[],['want','neutral']);b=task('b',[{'action':'PASS'}],['neutral'])
        wrong=completion(['want']);right=completion(['neutral'])
        saved=deepcopy(b)
        req=request(b,mode='sequential',prior_turns=[dict(task=a,message=wrong['message'])])
        self.assertIn(wrong['message'],req['messages'])
        self.assertNotIn('SECRET_GOLD',json.dumps(req))
        self.assertEqual(req['messages'][-2]['content'],'Recorded.')
        relation=score_transition(a,b,score_attempt(a,wrong),score_attempt(b,right),dict(player=1,goal=0))
        self.assertTrue(relation['error_recovered'])
        self.assertFalse(relation['error_persisted'])
        self.assertEqual(b,saved)
        with self.assertRaises(ValueError):request(b,prior_turns=[dict(task=a,message=wrong['message'])])
        changed=deepcopy(a);changed['input']['game']={'different_turn_order':True}
        with self.assertRaises(ValueError):request(b,mode='sequential',prior_turns=[dict(task=changed,message=wrong['message'])])

    def test_maintain_and_update_errors_are_separate(self):
        a=task('a',[],['want','neutral']);b=task('b',[{'action':'PASS'}],['want','neutral'])
        x=score_transition(a,b,score_attempt(a,completion(['want','neutral'])),score_attempt(b,completion(['neutral'])),dict(player=1,goal=0))
        self.assertTrue(x['unnecessary_update']);self.assertFalse(x['missed_update'])
        b['gold']['judgments'][0].update(possible_preferences=['neutral'],favored='neutral')
        x=score_transition(a,b,score_attempt(a,completion(['want','neutral'])),score_attempt(b,completion(['want','neutral'])),dict(player=1,goal=0))
        self.assertTrue(x['missed_update'])

    def test_readable_delta_preserves_history_and_evidence_rules(self):
        a=task('a',[],['want','neutral']);b=task('b',[{'action':'PASS'}],['neutral'])
        from training.b_sft.social_b_evaluation import SYSTEM, payload
        first=payload(a['input'])
        self.assertEqual(first['public_state']['committed_action_ids']['0'],[])
        self.assertEqual(first['own_preferences'],dict(player=0,preferences_by_goal={'goal_0':'want'}))
        r=request(b,mode='sequential',prior_turns=[dict(task=a,message=completion(['want'])['message'])])
        users=[json.loads(m['content']) for m in r['messages'] if m['role']=='user']
        self.assertNotIn('game',users[1])
        self.assertEqual(users[0]['history']+users[1]['new_history'],payload(b['input'])['history'])
        self.assertEqual(users[1]['new_history'][0]['kind'],'autonomous')
        self.assertIn('including the observer actions',SYSTEM)
        self.assertNotIn('Only subsequent partner events can exclude types',SYSTEM)
        self.assertIn('A goal is satisfied only when every action',SYSTEM)

    def test_family_ignores_turn_variants_and_renaming(self):
        raw,prefix=forward_fixture(rounds=2)
        s=dict(raw=raw,prefix=prefix,target=1,goal=2)
        base=family(raw)
        for v in variants(s):self.assertEqual(family(v['raw']),base)
        renamed=deepcopy(raw);g=renamed['game'];mapping={0:2,1:0,2:1}
        counts=g['n_actions_per_player'];new=[0]*3
        for p,k in enumerate(counts):new[mapping[p]]=k
        g['n_actions_per_player']=new
        for goal in g['goals']:
            for action in goal['required_actions']:
                p=action['player_id'];action['action_id']=counts[p]-1-action['action_id'];action['player_id']=mapping[p]
        g['goals'].reverse()
        self.assertEqual(family(renamed),base)
        split=split_families({'a':{'family':base},'b':{'family':base}}, {'a'})
        self.assertEqual(len(split),1)


if __name__=='__main__':unittest.main()
