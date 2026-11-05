import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from contextlib import redirect_stdout
import io

from training.b_sft.social_coupled_credit import NativeEpisode
from training.b_sft.social_three_arm import cases, payload, parse, Policy, Scripted, VLLM, run, rollout, ARMS, partner, messages, BELIEF_STOP, preflight


def native_call(action):
    return [dict(type="function",function=dict(name="SUBMIT_ACTION",arguments=json.dumps(action)))]


class ThreeArmTests(unittest.TestCase):
    def test_evidence_changes_optimal_partner_at_same_physical_state(self):
        pack=cases(); states=[]; optima=[]
        for case in pack[:2]:
            env=NativeEpisode(case['raw'],case['prefix'])
            physical=env.node.state.public_state()
            physical.pop('transcript')
            states.append(physical)
            self.assertEqual(len(case['worlds']),1)
            values=[]
            for action in payload(env,case,'bp')['legal_actions']:
                outcome=rollout(case,case['worlds'][0],action,None,'bp',7)
                self.assertTrue(outcome['terminal'])
                values.append((action,outcome['reward']))
            best=max(v for _,v in values)
            optima.append({json.dumps(a,sort_keys=True) for a,v in values if v==best})
        self.assertEqual(states[0],states[1])
        self.assertFalse(optima[0]&optima[1])
        self.assertEqual(len(pack[2]['worlds']),4)

    def test_no_hidden_world_or_solver_label_in_prompt(self):
        for case in cases():
            p=payload(NativeEpisode(case['raw'],case['prefix']),case,'bp')
            self.assertNotIn('worlds',p)
            self.assertNotIn('model_beliefs',p)
            self.assertNotIn('queries',p)
            self.assertEqual(p['own_preferences']['player'],case['raw']['ego'])
            self.assertNotIn('proposer_action',json.dumps(p['legal_actions']))
            self.assertTrue(json.dumps(p).isascii())

    def test_action_parser_strict_and_bp_required(self):
        legal=[{'action':'PASS'}]
        self.assertEqual(parse('Their preferences are uncertain.\n\nI choose to wait.',legal,'bp',tool_calls=native_call(legal[0])),legal[0])
        for text in ('<ACTION>{"action":"PASS"}</ACTION>',
                     'Reason <ACTION>{"action_index":0}</ACTION>',
                     'Reason <ACTION>{"action":"PASS","action":"PASS"}</ACTION>'):
            with self.assertRaises(ValueError):parse(text,legal,'free')
        with self.assertRaises(ValueError):parse('Reason <ACTION>{"action":"PASS"}</ACTION>',legal,'bp')

    def test_numeric_action_reports_exact_failure_without_index_repair(self):
        class Numeric(Scripted):
            def generate(self,*args,**kwargs):
                text='I choose the willing partner.\n\n<ACTION>6</ACTION>'
                return dict(text=text,content='I choose the willing partner.',tool_calls=native_call(6),token_ids=list(text.encode()),logprobs=[0]*len(text),
                            finish_reason='stop',usage={'completion_tokens':len(text)})
        case=cases()[0];env=NativeEpisode(case['raw'],case['prefix'])
        policy=Policy(Numeric(),lambda *args:None)
        with redirect_stdout(io.StringIO()):result=policy.draw(env,case,'free',7)
        self.assertEqual(result['status'],'format_failure')
        self.assertEqual(result['validation_error'],'action_must_be_object')
        self.assertIsNone(result['answer'])
        self.assertEqual(len(policy.calls),2)

    def test_retry_separate_and_shared_prefix_budget(self):
        case=cases()[0];env=NativeEpisode(case['raw'],case['prefix'])
        class OnceTruncated(Scripted):
            def __init__(self):self.n=0;self.observed=[]
            def generate(self,prompt,prefix,limit,seed,stop,**kwargs):
                self.observed.append((list(prefix),limit));self.n+=1
                r=super().generate(prompt,prefix,limit,seed,stop,**kwargs)
                if self.n==1:r['finish_reason']='length'
                return r
        backend=OnceTruncated();policy=Policy(backend,lambda *x:None)
        b=policy.draw(env,case,'bp',7,belief_only=True)
        self.assertEqual([c['status'] for c in policy.calls],['truncation','ok'])
        self.assertEqual([c['failure_reward'] for c in policy.calls],[-1,0])
        p=policy.draw(env,case,'bp',7,belief=b)
        self.assertEqual(p['status'],'ok')
        self.assertEqual(backend.observed[-1],(b['token_ids'],1024-len(b['token_ids'])))

    def test_b_retry_consumes_the_path_retry_allowance(self):
        case=cases()[0];env=NativeEpisode(case['raw'],case['prefix'])
        class FailingP(Scripted):
            def __init__(self):self.n=0
            def generate(self,*args,**kwargs):
                self.n+=1;r=super().generate(*args,**kwargs)
                if self.n!=2:r['finish_reason']='length'
                return r
        policy=Policy(FailingP(),lambda *x:None)
        b=policy.draw(env,case,'bp',7,belief_only=True)
        p=policy.draw(env,case,'bp',7,belief=b)
        self.assertEqual(p['status'],'truncation')
        self.assertEqual(len(policy.calls),3)  # B attempt, B retry, P; no second retry.

    def test_native_chat_request_preserves_prefix_and_reads_tools(self):
        backend=VLLM.__new__(VLLM);backend.model='test';backend.endpoint='http://unused/chat/completions'
        class Tokenizer:
            def decode(self,ids,**kwargs):return 'B text.\n\n' if ids==[3] else 'exact rendered prefix'
            def encode(self,text,**kwargs):return [1,2,3]
        backend.tokenizer=Tokenizer()
        result=dict(choices=[dict(message=dict(content='P reasoning.',tool_calls=native_call({'action':'PASS'})),
            finish_reason='tool_calls',logprobs=dict(content=[dict(token='token_id:7',logprob=-.1),dict(token='token_id:8',logprob=-.2)]))],
            usage=dict(completion_tokens=2,prompt_tokens=3),prompt_logprobs=[None,{'2':{}},{'3':{}}])
        tools=[{'type':'function','function':{'name':'SUBMIT_ACTION'}}]
        with patch('training.b_sft.social_three_arm.urlopen') as http:
            http.return_value.__enter__.side_effect=[io.StringIO(json.dumps({'tokens':[1,2,3]})),io.StringIO(json.dumps(result))]
            generated=backend.generate([1,2],[3],10,7,None,msgs=[dict(role='user',content='State')],tools=tools)
            request=http.call_args.args[0];sent=json.loads(request.data)
        self.assertTrue(request.full_url.endswith('/chat/completions'))
        self.assertEqual(sent['tools'],tools)
        self.assertEqual(sent['tool_choice'],'auto')
        self.assertFalse(sent['parallel_tool_calls'])
        self.assertEqual(sent['messages'][-1],dict(role='assistant',content='B text.\n\n'))
        self.assertNotIn('prompt',sent)
        self.assertEqual(generated['token_ids'],[7,8])
        self.assertEqual(generated['tool_calls'],native_call({'action':'PASS'}))
        self.assertTrue(generated['prompt_verified'])

    def test_plaintext_actions_never_replace_native_tools(self):
        legal=[{'action':'PASS'}]
        for text in ('Reason. {"action":"PASS"}',
                     'Reason. <ACTION>{"action":"PASS"}</ACTION>',
                     'Reason. <tool_call>{"name":"SUBMIT_ACTION","arguments":{"action":"PASS"}}</tool_call>'):
            with self.assertRaisesRegex(ValueError,'expected_one_native_tool_call'):
                parse(text,legal,'free',tool_calls=[])
        self.assertEqual(parse('I choose to wait.',legal,'free',tool_calls=native_call(legal[0])),legal[0])

    def test_all_arms_spend_same_rollout_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'pilot'
            with redirect_stdout(io.StringIO()):summary=run(out,Scripted())
            self.assertEqual({v['rollout_slots'] for v in summary.values()},{24})
            self.assertEqual({v['terminal_episodes'] for v in summary.values()},{24})
            self.assertEqual(summary['bp_outcome']['requests'],12)
            self.assertEqual(summary['bp_branch']['requests'],18)
            cfg=json.loads((out/'run_config.json').read_text())
            self.assertFalse(cfg['actual_LM']);self.assertEqual(cfg['optimizer_updates'],0)
            with self.assertRaises(FileExistsError):run(out,Scripted())

    def test_twice_failed_generation_spends_slots_without_fake_payoffs(self):
        class Broken(Scripted):
            def generate(self,*args,**kwargs):
                return dict(text='bad',token_ids=[1],logprobs=[0],finish_reason='stop',usage={'completion_tokens':1})
        with tempfile.TemporaryDirectory() as tmp:
            with redirect_stdout(io.StringIO()):summary=run(Path(tmp)/'broken',Broken())
            for arm in ARMS:
                self.assertEqual(summary[arm]['rollout_slots'],24)
                self.assertEqual(summary[arm]['terminal_episodes'],0)
                self.assertIsNone(summary[arm]['all_slots_mean_return'])
            self.assertEqual(summary['free_outcome']['requests'],24)
            self.assertEqual(summary['bp_branch']['requests'],12)

    def test_separate_arms_preserve_serial_rollouts_and_budget(self):
        with tempfile.TemporaryDirectory() as tmp, redirect_stdout(io.StringIO()):
            root=Path(tmp)
            together=run(root/'all',Scripted())
            for arm in ARMS:
                separate=run(root/arm,Scripted(),arms=(arm,))
                self.assertEqual(set(separate),{arm})
                self.assertEqual(separate[arm]['rollout_slots'],together[arm]['rollout_slots'])
                self.assertEqual((root/arm/f'{arm}_rollouts.jsonl').read_text(),
                                 (root/'all'/f'{arm}_rollouts.jsonl').read_text())
                self.assertEqual((root/arm/f'{arm}_signals.jsonl').read_text(),
                                 (root/'all'/f'{arm}_signals.jsonl').read_text())
                config=json.loads((root/arm/'run_config.json').read_text())
                self.assertEqual(config['selected_arms'],[arm])

    def test_natural_b_boundary_and_old_template_rejected(self):
        self.assertIsNone(parse('The partner may agree.\n\n',[], 'bp',belief_only=True))
        for text in ('<B>Judgment about partner preferences</B>',
                     'The partner may agree.', 'The partner may agree.\n\nI choose PASS.'):
            with self.assertRaises(ValueError):parse(text,[], 'bp',belief_only=True)
        with self.assertRaises(ValueError):
            parse('<B>Unknown</B><P>Wait</P><ACTION>{"action":"PASS"}</ACTION>',[{'action':'PASS'}],'bp')

    def test_qualitative_partner_rule_matches_native_behavior_for_pilot(self):
        from random import Random
        for case in cases():
            base=NativeEpisode(case['raw'],case['prefix'])
            for world in case['worlds']:
                for move in base.visible()['legal_actions']:
                    env=NativeEpisode(case['raw'],case['prefix']);env.step(move)
                    if env.node.state.is_terminal:continue
                    actor=env.rules.actor(env.node)
                    before=env.node.state.goal_satisfaction()
                    accept=next(a for a in env.rules.actions(env.node) if a.to_dict()=={'response':'ACCEPT'})
                    after=env.rules._apply(env.node,accept).state.goal_satisfaction()
                    changes=[pref for pref,was,now in zip(world[actor],before,after) if now and not was]
                    expected={'response':'ACCEPT' if 1 in changes and -1 not in changes else 'REJECT'}
                    self.assertEqual(partner(env,world,Random(0)),expected)
        for mode in ('free','bp'):
            c=cases()[0];msgs=messages(NativeEpisode(c['raw'],c['prefix']),c,mode)
            text=json.dumps(msgs)
            self.assertNotIn('expected terminal utility',text)
            self.assertNotIn('+1',text)
            self.assertNotIn('<B>',text)
            self.assertNotIn('<P>',text)

    def test_preflight_stops_on_first_unusable_path(self):
        class Broken(Scripted):
            def generate(self,*args,**kwargs):
                return dict(text='bad',token_ids=[1],logprobs=[0],finish_reason='stop',usage={'completion_tokens':1})
        with tempfile.TemporaryDirectory() as tmp, redirect_stdout(io.StringIO()):
            out=Path(tmp)/'preflight'
            with self.assertRaises(RuntimeError):preflight(out,Broken())
            report=json.loads((out/'preflight.json').read_text())
            self.assertFalse(report['format_passed'])
            self.assertEqual(report['requests'],2)
            good=Path(tmp)/'good';preflight(good,Scripted())
            report=json.loads((good/'preflight.json').read_text())
            self.assertTrue(report['format_passed'])
            self.assertEqual(report['requests'],4)
            self.assertTrue(report['semantic_review_required'])

if __name__=='__main__':unittest.main()
