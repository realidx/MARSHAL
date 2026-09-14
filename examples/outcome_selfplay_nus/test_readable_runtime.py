"""CPU integration checks; never contact a model server."""
import copy,importlib.util,json,sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from unpack_runtime import unpack

TMP=tempfile.TemporaryDirectory(prefix='outcome-v3-test-')
HERE=Path(__file__).resolve().parent
ROOT=unpack(HERE/'runtime_v3.tar.gz',HERE/'runtime_v3.sha256',TMP.name)
sys.path[:0]=[str(ROOT/'runs/outcome_selfplay_screen'),str(ROOT/'third_party/negotiation_benchmark/src'),str(ROOT)]
import rollout as r
import selfplay_prompt as p
from bp_display import Names,action_call

class PromptTests(unittest.TestCase):
    def env(self):
        reset=r.select_resets('smoke')[0]
        return r.OutcomeEnv(reset['raw'],reset['realized_world'])

    def test_full_bank_named_tools_roundtrip_native_rewards_and_replay(self):
        seen=set()
        class Policy:
            def __call__(self,messages,obs,seed):
                for legal in obs['legal_actions']:
                    named=Names(obs).action(legal,obs['player'],obs['public_state']['commitments'])
                    tool_name,arguments=action_call(named)
                    assert p.decode_call(obs,tool_name,arguments)==legal
                native=r.ScriptedPolicy()(messages,obs,seed)['action']
                shown=Names(obs).action(native,obs['player'],obs['public_state']['commitments'])
                name,args=action_call(shown);seen.add(name)
                fake=SimpleNamespace(seed=None,complete_with_tools=Mock(return_value=SimpleNamespace(
                    tool_calls=[SimpleNamespace(name=name,arguments=args)],content='CPU test',raw_message={},usage={},finish_reason='tool_calls')))
                result=r.HTTPPolicy(base_url='unused',model='unused',client=fake)(messages,obs,seed)
                assert result['action']==native
                assert fake.complete_with_tools.call_args.kwargs['tools']==p.tools_for(obs)
                return result
        summary,results=r.run_batch(r.select_resets('all'),Policy,rollouts=1,concurrency=1)
        self.assertEqual(summary['statuses'],{'terminal':24})
        self.assertTrue(summary['all_replays_verified'])
        self.assertEqual(seen,{'OFFER','ACCEPT','REJECT','INVESTIGATE','PASS'})
        for result in results:
            for player in result['players']:
                self.assertEqual(player['terminal_reward'],player['combined_reward'])
            for call in result['calls']:
                text=json.dumps(call['messages'])
                for marker in ('submit_action','proposer_action','partner_action','type_catalogues','supplied_belief','partner_policy'):
                    self.assertNotIn(marker,text)

    def test_binding_pending_and_linear_completion(self):
        e=self.env();obs=e.observe();actor=obs['player']
        offer=next(a for a in obs['legal_actions'] if a.get('action')=='OFFER' and sum(a['proposer_action'])==1 and sum(a['partner_action'])==1)
        e.step(offer);pending=p.render(e.observe())
        self.assertIn('These additions are not yet binding.',pending)
        self.assertIn('Currently 0 of 2 requirements are binding; completion=0.',pending)
        self.assertEqual({t['function']['name'] for t in p.tools_for(e.observe())},{'ACCEPT','REJECT'})
        e.step({'response':'ACCEPT'});text=p.render(e.observe())
        self.assertIn('New binding commitments:',text)
        self.assertIn('completion=0.5',text)
        self.assertIn('completion=1.',text)
        self.assertNotIn('These additions are not yet binding.',text)

    def test_private_answer_provenance_and_indistinguishable_worlds(self):
        e=self.env();obs=e.observe();actor=obs['player']
        alternative=next(w for w in e.rules.worlds if tuple(w[actor])==e.world[actor] and w!=e.world)
        twin=r.OutcomeEnv(e.raw,alternative)
        self.assertEqual(p.render(obs),p.render(twin.observe()))
        self.assertEqual(p.tools_for(obs),p.tools_for(twin.observe()))
        query=next(a for a in obs['legal_actions'] if a.get('action')=='INVESTIGATE');e.step(query)
        own=p.render(e.observe(actor));other=p.render(e.observe(query['player']))
        self.assertIn('Your investigation revealed that',own)
        self.assertNotIn('Your investigation revealed that',other)
        self.assertIn('The answer was shown only to you.',own)
        self.assertIn(f'{Names(obs).players[actor]}=0',own)
        self.assertNotIn('answer was shown only to you',other)
        self.assertIn('equal chances of want and neutral',own)
        self.assertNotIn('equal chances of want, neutral and avoid',own)

    def test_tool_validation_and_retry_penalty(self):
        e=self.env();obs=e.observe()
        self.assertIsNone(p.decode_call(obs,'submit_action',{'action':{'action':'PASS'}}))
        self.assertIsNone(p.decode_call(obs,'PASS',{'unexpected':1}))
        offer=next(a for a in p.visible(obs)['legal_actions'] if a.get('action')=='OFFER' and a['self_commitments'])
        name,args=action_call(offer);bad=copy.deepcopy(args);bad['self_commitments']*=2
        self.assertIsNone(p.decode_call(obs,name,bad))
        class RetryPolicy:
            count=0
            def __call__(self,messages,obs,seed):
                self.count+=1
                if self.count==1:return dict(action=None,finish_reason='length')
                if self.count==2:assert messages[-1]['content']==p.RETRY
                return r.ScriptedPolicy()(messages,obs,seed)
        result=r.run_episode(r.select_resets('smoke')[0],RetryPolicy())
        self.assertEqual(result['status'],'terminal')
        self.assertEqual(sum(x['format_penalty'] for x in result['players']),-.1)
        self.assertTrue(result['replay_verified'])

if __name__=='__main__':
    try:unittest.main()
    finally:TMP.cleanup()
