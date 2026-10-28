from copy import deepcopy
import json
import unittest
from unittest.mock import patch
from tempfile import TemporaryDirectory
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from training.b_sft.social_bp_curriculum import (
    acceptable, result_use_fixture, p_task, p_examples, result_pairs,
    prepare_b, digest, b_pairs_and_sequences,
)
from training.b_sft.social_bp_curriculum_eval import request, score, group_diagnostics, select_batch, run_probe
from training.b_sft.social_terminal_teacher import TerminalEpisode
from training.b_sft.social_b_oracle import forward_fixture, canonical
from training.b_sft.debug.audit_social_design_iteration import belief_examples, independent_values


def decorate(t, tid='sample'):
    return dict(t,id=tid,split='train',mechanism='test',topology='test')


def completion(name, args):
    return dict(finish_reason='stop',raw_message=dict(role='assistant',content='Reasoning.',
        tool_calls=[dict(id='call_test',type='function',function=dict(name=name,arguments=json.dumps(args)))]))


class ShortCurriculumTests(unittest.TestCase):
    def test_native_result_bridge_has_disjoint_answers_and_clear_own_gain(self):
        tasks=[]
        for value in ('want','avoid'):
            raw,prefix=result_use_fixture(value)
            e=TerminalEpisode(raw,prefix)
            independent_values(e.tree)
            self.assertEqual(len(e.tree.worlds),1)
            self.assertEqual(e.tree.entries[0].node.state.turn_index,5)
            self.assertEqual(e.tree.entries[0].node.state.public_state()['investigation_remaining'],0)
            t=decorate(p_task(e,raw['own_preferences']),value)
            t['contrast_family']='result-bridge'
            best=t['teacher']['acceptable_actions']
            self.assertEqual(best,[dict(action='OFFER',partner_id=1,
                proposer_action=[1,0] if value=='want' else [0,1],partner_action=[1])])
            # Native goal arithmetic: favorable risky deal yields two goals;
            # safe deal yields one. Wrong risky deal is rejected and yields zero.
            q={canonical(a):v[0] for a,v in zip(t['input']['legal_actions'],t['teacher']['action_values'])}
            risky=canonical(dict(action='OFFER',partner_id=1,proposer_action=[1,0],partner_action=[1]))
            safe=canonical(dict(action='OFFER',partner_id=1,proposer_action=[0,1],partner_action=[1]))
            self.assertEqual(q[risky],2 if value=='want' else 0)
            self.assertEqual(q[safe],1)
            tasks.append(t)
        pairs=result_pairs(tasks)
        self.assertEqual(len(pairs),1)
        self.assertTrue(pairs[0]['investigator_is_decision_maker'])
        self.assertTrue(all(r['disjoint'] for r in pairs[0]['tolerance_survival']))

    def test_short_assisted_update_retains_correct_prior_and_one_event(self):
        raw,prefix=forward_fixture()
        e=TerminalEpisode(raw,prefix)
        tasks=[prepare_b(t) for t in belief_examples(e,1,2,max_per_kind=8)]
        short=[t for t in tasks if t['skill']=='update' and not t['input']['old_history']]
        self.assertTrue(short)
        for t in short:
            self.assertEqual(len(t['input']['new_history']),1)
            self.assertEqual(t['input']['previous_belief']['possible_preferences'],['want','neutral','avoid'])
            self.assertNotEqual(t['teacher']['gold'],t['input']['previous_belief'])

    def test_tolerances_do_not_allow_social_compensation_of_own_loss(self):
        self.assertEqual(acceptable([[1,0,0],[.8,100,100]],0),[0])
        self.assertEqual(acceptable([[1,1,0],[1,.95,0]],0),[0,1])
        self.assertEqual(acceptable([[1,1,0],[1,.7,0]],0),[0])
        for bad in (-1,float('nan'),float('inf')):
            with self.assertRaises(ValueError):acceptable([[1,0,0]],0,bad)

    def test_request_separates_teacher_answers_and_native_reward_roundtrip(self):
        raw,prefix=result_use_fixture('avoid')
        t=decorate(p_task(TerminalEpisode(raw,prefix),raw['own_preferences']))
        t['teacher']['secret_sentinel']='MUST_NOT_APPEAR'
        payload=request(t)
        self.assertNotIn('MUST_NOT_APPEAR',json.dumps(payload))
        self.assertNotIn('action_values',json.dumps(payload))
        self.assertNotIn('own_tolerance',json.dumps(payload))
        self.assertEqual(score(t,completion('SUBMIT_ACTION',t['teacher']['acceptable_actions'][0]))['reward'],1)
        self.assertEqual(score(t,completion('SUBMIT_ACTION',dict(action='PASS')))['reward'],0)
        illegal=deepcopy(t['teacher']['acceptable_actions'][0]);illegal['proposer_action']=[True,0]
        self.assertEqual(score(t,completion('SUBMIT_ACTION',illegal))['reward'],-1)
        self.assertEqual(score(t,dict(raw_message=dict(content=json.dumps(t['teacher']['acceptable_actions'][0]))))['reward'],-1)

    def test_nonuniform_posterior_is_not_described_as_equal_support(self):
        raw,prefix=forward_fixture()
        e=TerminalEpisode(raw,prefix)
        e.weights=np.array([.6,.3,.1])
        self.assertIsNone(p_task(e,raw['type_catalogues']['1'][0]))

    def test_sampling_keeps_all_wrong_core_and_never_mixes_splits_or_bp(self):
        raw,prefix=forward_fixture()
        bs=[decorate(prepare_b(t),str(i)) for i,t in enumerate(belief_examples(TerminalEpisode(raw,prefix),1,2))]
        extra=deepcopy(bs[0]);extra.update(id='heldout',split='validation_structure')
        diagnostics=dict(groups=[dict(task_id=t['id'],status='all_wrong') for t in bs])
        ids=select_batch(bs+[extra],task='B',stage=1,size=32,seed=0,diagnostics=diagnostics)
        self.assertEqual(len(ids),32)
        self.assertNotIn('heldout',ids)
        self.assertTrue({t.get('category',t['skill']) for t in bs} <=
                        {t.get('category',t['skill']) for t in bs if t['id'] in ids})

    def test_groups_distinguish_all_wrong_mixed_incomplete_and_duplicate(self):
        raw,prefix=result_use_fixture('avoid')
        task=decorate(p_task(TerminalEpisode(raw,prefix),raw['own_preferences']))
        bad=completion('SUBMIT_ACTION',dict(action='PASS'))
        good=completion('SUBMIT_ACTION',task['teacher']['acceptable_actions'][0])
        samples=[dict(task_id=task['id'],sample_index=i,**bad) for i in range(2)]
        report=group_diagnostics([task],samples,group_size=2)
        self.assertEqual(report['groups'][0]['status'],'all_wrong')
        self.assertEqual(report['strata'][0]['recommendation'],'add_shorter_bridge_and_keep_core_probes')
        samples[1]=dict(task_id=task['id'],sample_index=1,**good)
        self.assertEqual(group_diagnostics([task],samples,group_size=2)['groups'][0]['status'],'mixed')
        self.assertEqual(group_diagnostics([task],samples[:1],group_size=2)['groups'][0]['status'],'incomplete')
        with self.assertRaisesRegex(ValueError,'Duplicate'):
            group_diagnostics([task],samples+[samples[0]],group_size=2)

    def test_continuous_request_keeps_wrong_model_answer_not_gold(self):
        raw,prefix=forward_fixture()
        tasks=[decorate(prepare_b(t),digest(t['input'])) for t in belief_examples(TerminalEpisode(raw,prefix),1,2,max_per_kind=12)]
        _,sequences=b_pairs_and_sequences(tasks)
        self.assertTrue(sequences)
        by_id={t['id']:t for t in tasks}
        first,last=[by_id[i] for i in (sequences[0]['checkpoints'][0],sequences[0]['checkpoints'][-1])]
        wrong=completion('SUBMIT_BELIEFS',dict(judgments=[dict(**first['input']['queries'][0],possible_preferences=['avoid'],favored='avoid')]))
        wrong['raw_message']['content']='MY_PRIOR_WRONG_REASONING'
        payload=request(last,prior_turns=[dict(task=first,raw_message=wrong['raw_message'])])
        self.assertIn('MY_PRIOR_WRONG_REASONING',json.dumps(payload))
        self.assertNotIn('previous_belief',payload['messages'][-1]['content'])
        self.assertEqual(payload['messages'][-2]['content'],'Recorded.')

    def test_parallel_probe_records_each_sample_once_and_keeps_failures(self):
        raw,prefix=result_use_fixture('avoid')
        base=p_task(TerminalEpisode(raw,prefix),raw['own_preferences'])
        tasks=[decorate(deepcopy(base),str(i)) for i in range(4)]
        class Client:
            def __init__(self,*args,**kwargs):pass
            def complete_with_tools(self,**payload):
                answer=completion('SUBMIT_ACTION',dict(action='PASS'))
                return SimpleNamespace(**answer,usage={'completion_tokens':12})
        with TemporaryDirectory() as temp, patch('training.b_sft.social_bp_curriculum_eval.probe_tasks',return_value=(tasks,tasks)), \
                patch('methods.vllm_client.OpenAICompatibleNegotiationClient',Client):
            out=Path(temp)/'out'
            result=run_probe(temp,out,model='mock',base_urls=['http://one','http://two'],group_size=2)
            rows=[json.loads(x) for x in (out/'samples.jsonl').read_text().splitlines()]
            self.assertEqual(result['requests_sent'],8)
            self.assertEqual(len({(r['task_id'],r['sample_index']) for r in rows}),8)
            report=json.loads((out/'sampling_diagnostics.json').read_text())
            self.assertTrue(all(r['status']=='all_wrong' for r in report['groups']))
            self.assertFalse(result['parameters_updated'])


if __name__=='__main__':unittest.main()
