from copy import deepcopy
import json
import unittest
from unittest.mock import patch
from training.social_mixed.reasoning_bank import load, panel, PATH
from training.social_mixed.reasoning_scoring import score
from training.social_mixed.reasoning_training import group_advantages, ReasoningCollector
from training.social_mixed.reasoning_validation import metrics_and_state, ReasoningValidator
from training.b_sft import social_named_probe as named


def completion(task,index):
    action=named.present(task,task.get('name_variant',0))['legal_actions'][index]
    name,args=named.action_call(action)
    return dict(finish_reason='stop',raw_message=dict(content='',tool_calls=[dict(function=dict(name=name,arguments=json.dumps(args)))]))


class TriStateTests(unittest.TestCase):
    def test_native_tool_scoring_and_O_independence(self):
        rows=load();p=next(t for t in rows if t['paired_view']=='Pplus' and set(t['p_supervision']['action_states'])=={'positive','negative','masked'})
        o=next(t for t in rows if t['canonical_id']==p['canonical_id'] and t['paired_view']=='O')
        for state in ('positive','negative','masked'):
            j=p['p_supervision']['action_states'].index(state);response=completion(p,j)
            result=score(p,response)
            self.assertEqual(result['semantic_outcome'],state)
            self.assertEqual(result['semantic_eligible'],state!='masked')
            self.assertEqual(result['correct'],None if state=='masked' else state=='positive')
            self.assertIsInstance(score(o,response)['correct'],bool)
        cut=completion(p,0);cut['finish_reason']='length'
        self.assertFalse(score(p,cut)['semantic_eligible'])

    def test_mask_does_not_change_centering_or_protocol_validity(self):
        scores=[dict(status='ok',reward=1),dict(status='ok',reward=0)]
        masked=dict(status='ok',reward=0,semantic_eligible=False)
        for norm in ('centered_fixed','standard_sequence'):
            base,_=group_advantages(scores,[dict(completion=dict(finish_reason='stop'))]*2,norm)
            values,valid=group_advantages(scores+[masked]*6,[dict(completion=dict(finish_reason='stop'))]*8,norm)
            self.assertEqual(values[:2],base);self.assertEqual(values[2:],[0.]*6);self.assertTrue(all(valid))
            values,_=group_advantages([scores[0]]+[masked]*7,[dict(completion=dict(finish_reason='stop'))]*8,norm)
            self.assertEqual(values,[0.]*8)

    def test_pool_full_parents_and_sampler_excludes_ineligible_P(self):
        rows=load();c=ReasoningCollector({'bp_train':rows},lambda reqs:[],concurrency=8)
        self.assertEqual(len(c.schedule),373)
        eligible={t['canonical_id'] for t in rows if t['paired_view']=='Pplus' and t['p_train_eligible']}
        self.assertEqual(len(eligible),314)
        self.assertEqual(set(c.informative+c.controls),eligible)
        self.assertIn(('P3','linear'),{(t['source_kernel'],t['completion_mode']) for t in rows if t['paired_view']=='O'})
        self.assertEqual(len({t['package_id'] for s in ('train','validation') for t in load(s)}),175)
        # Exercise real sampling path with synthetic rollouts, preserving all task metadata.
        def generate(reqs):return [dict(response_ids=[1]*1024,completion=dict(finish_reason='stop')) for _ in reqs]
        c.generate=generate
        with patch('training.social_mixed.paired_requests.request',return_value={}),patch('training.social_mixed.reasoning_scoring.score',return_value=dict(reward=1.,correct=True,status='ok')),patch('training.social_mixed.reasoning_scoring.decision_metrics',return_value={}):
            collected,_,_,_=c.collect(0,'decomposed')
        self.assertTrue(all(r['canonical_id'] in eligible for r in collected if r['kind']=='Pplus'))
        # Current global coverage uses four distinct B groups, not the retired paired-5 slot.
        self.assertEqual(len({r['canonical_id'] for r in collected if r['kind']=='B'}),4)

    def test_masked_validation_is_not_forgetting_or_incorrect(self):
        task=dict(id='p',paired_view='Pplus',canonical_id='c',package_id='pkg')
        old=dict(last={'p':True},ever_correct={'p':True})
        calls=[dict(task=task,score=dict(correct=None,reward=0,status='ok',semantic_outcome='masked'))]
        m,state=metrics_and_state(calls,old)
        self.assertEqual(m['reasoning/Pplus/scored_coverage'],0)
        self.assertEqual(m['reasoning/Pplus/forgotten_from_previous'],0)
        self.assertEqual(m['reasoning/Pplus/previously_correct_now_masked'],1)
        self.assertTrue(state['ever_correct']['p']);self.assertIsNone(state['last']['p'])
        self.assertNotIn('reasoning/Pplus/conditional_accuracy',m)

    def test_validation_panel_contains_real_B_action_contrasts(self):
        ts=panel();by={(t['canonical_id'],t['paired_view']):t for t in ts}
        pairs=[r for r in load('validation','relations.jsonl') if r.get('isolated_B_action_pair')]
        self.assertEqual(len(pairs),2)
        for r in pairs:
            a,b=(by[r[k],'B'] for k in ('left','right'))
            self.assertEqual(a['input']['queries'],b['input']['queries'])
            self.assertNotEqual(a['teacher']['gold'],b['teacher']['gold'])
            pa,pb=(by[r[k],'Pplus']['p_supervision']['action_states'] for k in ('left','right'))
            self.assertFalse({j for j,x in enumerate(pa) if x=='positive'} & {j for j,x in enumerate(pb) if x=='positive'})

class ValidatorIntegrationTests(unittest.TestCase):
    def test_validator_replaces_native_binary_P_metrics(self):
        tasks=[t for t in panel() if t['paired_view']!='Pplus' or t['p_pool_status']!='quarantined']
        calls=[];masked=0
        from training.b_sft.social_bp_training import native_completion, reward
        for task in tasks:
            response=native_completion(task)
            if task['paired_view']=='Pplus' and 'masked' in task['p_supervision']['action_states']:
                response=completion(task,task['p_supervision']['action_states'].index('masked'));masked+=1
            calls.append(dict(task=task,completion=response,score=reward(task,response),replica=0))
        self.assertGreater(masked,0)
        obj=ReasoningValidator.__new__(ReasoningValidator);obj.tasks=tasks
        baseline=dict(bp_calls=calls,metrics={'bp/obsolete_binary_P':1.},protocol={})
        with patch('training.social_mixed.validation.Validator.run',return_value=baseline):
            result=obj.run()
        self.assertNotIn('bp/obsolete_binary_P',result['metrics'])
        self.assertEqual(result['metrics']['reasoning/Pplus/semantic_masked'],masked)
        self.assertLess(result['metrics']['reasoning/Pplus/scored_coverage'],1)
        self.assertEqual(result['metrics']['reasoning/B/isolated_B_action_pairs'],2)
        self.assertEqual(result['metrics']['reasoning/B/isolated_B_both_correct'],1)


if __name__=='__main__':unittest.main()
