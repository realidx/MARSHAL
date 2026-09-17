import unittest
from copy import deepcopy
from training.social_mixed.structure_coverage import geometry_id

class GeometryTests(unittest.TestCase):
    def test_renaming_and_scoring_do_not_make_new_geometry(self):
        a=dict(n_players=2,n_actions_per_player=[2,2],goals=[dict(binary=True,required_actions=[dict(player_id=0,action_id=0),dict(player_id=1,action_id=1)]),dict(binary=True,required_actions=[dict(player_id=1,action_id=0)])])
        b=deepcopy(a)
        b['goals'].reverse()
        for g in b['goals']:
            g['binary']=False
            for r in g['required_actions']:
                r['player_id']=1-r['player_id'];r['action_id']=1-r['action_id']
        self.assertEqual(geometry_id(a),geometry_id(b))
        b['goals'].append(deepcopy(b['goals'][0]))
        self.assertNotEqual(geometry_id(a),geometry_id(b))
    def test_dependency_change_is_detected(self):
        a=dict(n_players=2,n_actions_per_player=[2,2],goals=[dict(required_actions=[dict(player_id=0,action_id=0),dict(player_id=1,action_id=0)])])
        b=deepcopy(a);b['goals'][0]['required_actions'][1]['player_id']=0;b['goals'][0]['required_actions'][1]['action_id']=1
        self.assertNotEqual(geometry_id(a),geometry_id(b))


class PackTests(unittest.TestCase):
    def test_active_pack_split_and_development_coverage(self):
        import json
        from training.social_mixed.core import DATA, load_data
        from training.social_mixed.structure_coverage import audit
        from training.social_mixed.distribution_sampling import select
        data=load_data();report=audit(DATA)
        self.assertFalse(report['cross_split_families'])
        self.assertTrue(report['independent_structure_test_ready'])
        selected=select(data['bp_validation'],0,42,validation=True)
        cell=lambda t:(t['kernel'],t['completion_mode'],t.get('information_role','na'))
        self.assertEqual({cell(t) for t in selected},{cell(t) for t in data['bp_validation']})
        self.assertTrue(any(t['kernel']=='P4' and t['information_role']=='query_only' for t in selected))
        held={t['id'] for t in map(json.loads,(DATA/'bp_test.jsonl').read_text().splitlines())}
        for step in range(64):
            batch=select(data['bp_train'],step,42)
            self.assertFalse(held & {t['id'] for t in batch})
            if any(t['kernel']=='P4' for t in batch):
                self.assertTrue({'query_only','ordinary_only'} <= {t.get('information_role') for t in batch if t['kernel']=='P4'})

class SignalTests(unittest.TestCase):
    def test_zero_reward_groups_are_not_counted_as_task_signal(self):
        from training.social_mixed.core import assign_advantages
        rows=[];units=[]
        for kind,cell,rewards in [('B','B1/binary/reduced_support/na',[0,0]),('P','P4/binary/ordinary_only/deadline',[0,1]),('selfplay','na',[0,0])]:
            for replica,value in enumerate(rewards):
                uid=f'{kind}:{replica}'
                rows.append(dict(unit=uid,kind=kind))
                units.append(dict(unit=uid,group=kind,replica=replica,kind=kind,utility=value,protocol=0,diagnostic_cell=cell))
        metrics=assign_advantages(rows,units,'mixed')
        self.assertEqual(metrics['task_signal/B1/binary/reduced_support/na/nonzero_advantage_groups'],0)
        self.assertEqual(metrics['task_signal/P4/binary/ordinary_only/deadline/nonzero_advantage_groups'],1)
        self.assertAlmostEqual(sum(r['loss_weight'] for r in rows),len(rows))

if __name__=='__main__':unittest.main()
