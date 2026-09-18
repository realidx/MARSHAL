"""Candidate acceptance checks: labels, leakage, pairing and actual sampling."""
from collections import defaultdict
import json
import unittest
from training.social_mixed.prepare_reasoning_v4 import OUT,read
from training.social_mixed.reasoning_requests import request
from training.social_mixed.distribution_sampling import select
from training.social_mixed.structure_coverage import audit
from training.b_sft.social_bp_training import native_completion,reward
from training.b_sft.preference_contract import belief

class ReasoningDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.train=read(OUT/'bp_train.jsonl');cls.dev=read(OUT/'bp_validation.jsonl')
    def test_split_independence_and_labels(self):
        self.assertFalse(audit(OUT)['cross_split_families'])
        for rows in (self.train,self.dev):
            self.assertEqual(len(rows),len({t['id'] for t in rows}))
            for t in rows:
                self.assertTrue(reward(t,native_completion(t))['correct'])
                if t['task']=='B':self.assertEqual(t['teacher']['gold'],belief(t['teacher']['preference_weights']))
            self.assertTrue(any(t['kernel']=='B3' and t['skill']=='update' for t in rows))
            self.assertTrue(any(t['kernel']=='B3' and t['skill']=='maintain' for t in rows))
            self.assertTrue(any(t['kernel']=='P4' and t['input']['private_results'] for t in rows))
    def test_history_oracle_pairs_have_identical_information_and_labels(self):
        for rows in (self.train,self.dev):
            by={t['id']:t for t in rows};pairs=[t for t in rows if t.get('oracle_pair_of')]
            self.assertTrue(pairs)
            for oracle in pairs:
                raw=by[oracle['oracle_pair_of']]
                self.assertEqual(raw['teacher'],oracle['teacher'])
                for key in ('current_state','voluntary_history','private_results','public_preferences','own_preferences'):
                    self.assertEqual(raw['input'][key],oracle['input'][key])
                text=request(raw)['messages'][1]['content']
                self.assertNotIn('YOUR CURRENT BELIEF',text)
                self.assertNotIn('supplied belief',text)
                self.assertIn('YOUR CURRENT BELIEF',request(oracle)['messages'][1]['content'])
                joint=oracle['input']['supplied_belief']['joint_distribution']
                self.assertAlmostEqual(sum(float(r['probability']) for r in joint),1)
    def test_all_train_tasks_scheduled(self):
        seen=set()
        for step in range(512):seen.update(t['id'] for t in select(self.train,step,42))
        self.assertEqual(seen,{t['id'] for t in self.train})
    def test_candidate_periodic_validation_end_to_end(self):
        from training.social_mixed.validation import Validator,VERSION,cells
        from training.social_mixed.core import seed_for
        from training.social_mixed.test_core import generated
        data={name:read(OUT/(name+'.jsonl')) for name in ('bp_train','bp_validation','selfplay_train','selfplay_validation')}
        tasks=[t for t in data['bp_validation'] if t.get('periodic_validation')]
        answers={seed_for(42,VERSION,'bp',t['id'],0):native_completion(t) for t in tasks}
        def generate(reqs):
            return [dict(completion=answers[r['seed']]) if r['seed'] in answers else generated('PASS',{}) for r in reqs]
        report=Validator(data,generate).run()
        self.assertEqual(len(report['bp_calls']),45)
        self.assertEqual(report['metrics']['games/current_team/all/completed'],8)
        self.assertGreater(report['metrics']['bp/history_pairs/count'],0)
        self.assertEqual(report['metrics']['bp/history_pairs/raw_accuracy'],1)
        self.assertEqual(report['metrics']['bp/history_pairs/oracle_accuracy'],1)
        coverage={k for t in tasks for k in cells(t)}
        for k in ('B3/update','B3/maintain','P4/binary/result_use','P4/linear/result_use','P/history_sensitive'):
            self.assertIn(k,coverage)

    def test_actual_collector_uses_history_adapter(self):
        from training.social_mixed.core import Collector,seed_for
        data={name:read(OUT/(name+'.jsonl')) for name in ('bp_train','bp_validation','selfplay_train','selfplay_validation')}
        step=1;tasks=select(data['bp_train'],step,42)
        lookup={seed_for(42,t['id'],r,step):t for t in tasks for r in range(8)}
        history_calls=[]
        def generate(requests):
            outputs=[]
            for req in requests:
                t=lookup[req['seed']]
                if t['input'].get('belief_source')=='history':
                    self.assertNotIn('YOUR CURRENT BELIEF',req['messages'][1]['content']);history_calls.append(t['id'])
                outputs.append(dict(prompt_ids=[1],response_ids=[2],behavior_log_probs=[-.1],completion=native_completion(t)))
            return outputs
        rows,units,games,metrics=Collector(data,generate,seed=42,concurrency=16).collect(step,'bp')
        self.assertTrue(history_calls)
        self.assertTrue(all(r['score']['correct'] for r in rows))

    def test_results_change_acceptable_actions(self):
        for rows in (self.train,self.dev):
            groups=defaultdict(list)
            for t in rows:
                if t.get('reasoning_source_id') and t['skill']=='result_use' and not t.get('oracle_pair_of'):
                    groups[t['contrast_group']].append(t)
            self.assertTrue(any(len({t['answer_signature'] for t in ts})>1 for ts in groups.values()))

if __name__=='__main__':unittest.main()
