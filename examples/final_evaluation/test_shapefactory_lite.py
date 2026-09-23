import unittest
from examples.final_evaluation.shapefactory_lite import config, verify_source, differences, UPSTREAM
import subprocess,sys,json

class NativeLiteTests(unittest.TestCase):
    def test_upstream_integrity_and_only_authorized_changes(self):
        verify_source()
        allowed={'experiment.id','agents','task.shapes_order','task.shapes_types','task.shape_options','task.specialties'}
        for condition in ('private','dashboard'):
            for swapped in (False,True):
                base,cfg=config(condition,swapped,'test','http://localhost:8000/v1')
                self.assertLessEqual({d['path'] for d in differences(base,cfg)},allowed | {'task.specialties.A','task.specialties.B','task.specialties.C','task.specialties.D','task.specialties.E','task.specialties.F'})
                for key in ('prompts','protocol','probe','controls','action_space'):
                    self.assertEqual(base[key],cfg[key])
                self.assertEqual(cfg['experiment']['duration_sec'],900)
                self.assertEqual(len(cfg['agents']),2)
                self.assertEqual(cfg['agents'][0]['model'],cfg['agents'][1]['model'])

    def test_native_initialization_and_self_supply(self):
        # Exercise upstream economic transitions unchanged, not the old adapter.
        _,cfg=config('private',False,'test','http://localhost:8000/v1')
        script='''import json,sys
from types import SimpleNamespace
from src.tasks.shapefactory import shapefactory_init_state,shapefactory_apply_action
cfg=json.loads(sys.argv[1]); state=SimpleNamespace(task_state=shapefactory_init_state(cfg)); events=[]
def emit(**event):events.append(event)
for actor in ('A','B'):
 p=state.task_state['participants'][actor]
 assert len(p['tasks'])==1 and p['tasks'][0]!=p['specialty']
 shape=p['tasks'][0]
 assert shapefactory_apply_action(state,actor,dict(type='produce_shape',payload=dict(shape=shape,quantity=1)),emit)
 assert shapefactory_apply_action(state,actor,dict(type='fulfill_order',payload=dict(order_indices=[0])),emit)
 assert p['order_progress']==1 and p['money']==220
assert not any(e['event_type']=='action_rejected' for e in events)
'''
        subprocess.run([sys.executable,'-c',script,json.dumps(cfg)],cwd=UPSTREAM,check=True)

if __name__=='__main__':unittest.main()
