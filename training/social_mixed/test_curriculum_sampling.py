from collections import Counter
import random
import unittest
from training.social_mixed.prepare_reasoning_v5 import OUT, SOURCE, read
from training.social_mixed.curriculum_sampling import select, reset_order
from training.social_mixed.distribution_sampling import select as original


class CurriculumTests(unittest.TestCase):
    def test_every_update_preserves_both_domains_and_budget(self):
        rows=read(OUT/'bp_train.jsonl');baseline=read(SOURCE/'bp_train.jsonl')
        for seed in (42,123):
            seen=set()
            for step in range(1000):
                batch=select(rows,step,seed)
                self.assertEqual({t['task'] for t in batch},{'B','P'},(seed,step))
                self.assertLessEqual(len(batch),len(original(baseline,step,seed)))
                seen.update(t['id'] for t in batch)
                p4=[t for t in batch if t['kernel']=='P4']
                if p4:self.assertTrue({'query_only','ordinary_only'}<={t['information_role'] for t in p4})
            self.assertEqual(seen,{t['id'] for t in rows})
    def test_legacy_schedule_unchanged(self):
        rows=read(SOURCE/'bp_train.jsonl')
        for step in range(20):
            self.assertEqual(select(rows,step,42),original(rows,step,42))
        sp=read(SOURCE/'selfplay_train.jsonl')
        expected=list(range(len(sp)));random.Random(42).shuffle(expected)
        self.assertEqual(reset_order(sp,random.Random(42)),expected)

    def test_complete_practice_groups_and_controls(self):
        rows=read(OUT/'bp_train.jsonl')
        baseline=read(SOURCE/'bp_train.jsonl')
        seen=Counter()
        for step in range(64):
            batch=select(rows,step,42)
            self.assertLessEqual(len(batch),len(original(baseline,step,42)))
            seen.update(t['id'] for t in batch)
            if step%4==1:
                raw=[t for t in batch if 'history' in t.get('practice_units',{}) and t['task']=='P' and not t.get('oracle_pair_of')]
                self.assertTrue(raw)
            p4=[t for t in batch if t['kernel']=='P4']
            if p4:self.assertTrue({'query_only','ordinary_only'}<={t['information_role'] for t in p4})
        for role in ('bridge','history'):
            self.assertTrue(all(seen[t['id']]>=1 for t in rows if role in t.get('practice_units',{})))

    def test_linear_pairs_and_fixed_validation_size(self):
        for split in ('train','validation'):
            rows=read(OUT/('bp_'+split+'.jsonl'));by={t['id']:t for t in rows}
            raw=[t for t in rows if t.get('linear_history_addition') and t['task']=='P' and not t.get('oracle_pair_of')]
            self.assertEqual(len(raw),5 if split=='train' else 8)
            for t in raw:
                self.assertEqual(t['completion_mode'],'linear')
                self.assertTrue(t['teacher']['history_changes_acceptable'])
                oracle=next(o for o in rows if o.get('oracle_pair_of')==t['id'])
                self.assertEqual(t['teacher'],oracle['teacher'])
                self.assertEqual(t['input']['voluntary_history'],by[t['linked_b_id']]['input']['voluntary_history'])
            if split=='validation':
                panel=[t for t in rows if t.get('periodic_validation')]
                self.assertEqual(len(panel),45)
                self.assertTrue(any(t in panel for t in raw))

    def test_sp_horizon_quota_covers_all_resets(self):
        rows=read(OUT/'selfplay_train.jsonl');order=reset_order(rows,random.Random(42))
        self.assertEqual(set(order),set(range(len(rows))))
        counts=Counter('short' if len(rows[i]['raw']['game']['round_robin'])<=6 else 'medium' if len(rows[i]['raw']['game']['round_robin'])<=9 else 'long' for i in order)
        self.assertEqual(counts['short'],2*counts['medium'])
        self.assertEqual(counts['medium'],counts['long'])

    def test_collector_consumes_quota(self):
        from training.social_mixed.core import Collector,seed_for
        from training.b_sft.social_bp_training import native_completion
        data={name:read(OUT/(name+'.jsonl')) for name in ('bp_train','bp_validation','selfplay_train','selfplay_validation')}
        for step in range(16):
            selected=select(data['bp_train'],step,42)
            lookup={seed_for(42,t['id'],r,step):t for t in selected for r in range(8)}
            def generate(reqs):
                return [dict(prompt_ids=[1],response_ids=[2],behavior_log_probs=[-.1],completion=native_completion(lookup[r['seed']])) for r in reqs]
            rows,_,_,_=Collector(data,generate,42,16).collect(step,'bp')
            self.assertEqual(Counter(r['task_id'] for r in rows),{t['id']:8 for t in selected})
            self.assertTrue(all(r['score']['correct'] for r in rows))
            for kind in ('B','P'):
                self.assertAlmostEqual(sum(r['loss_weight'] for r in rows if r['kind']==kind)/len(rows),.5)


if __name__=='__main__':unittest.main()
