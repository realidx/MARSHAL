"""Failure attribution and all-failure regression cases; no GPU needed."""
import unittest
from training.social_mixed.core import assign_advantages


class ProtocolSignalTests(unittest.TestCase):
    def test_all_truncated_bp_still_negative(self):
        rows=[];units=[]
        for kind in ('B','P'):
            for i in range(8):
                uid=f'{kind}{i}'
                units.append(dict(group=kind,unit=uid,replica=i,kind=kind,utility=0,protocol=0))
                rows.append(dict(unit=uid,kind=kind,score=dict(status='truncated'),completion=dict(finish_reason='length')))
        metrics=assign_advantages(rows,units,'bp')
        self.assertTrue(all(r['advantage']==-.2 and r['task_advantage']==0 for r in rows))
        self.assertEqual(metrics['B/call_signal/protocol_negative_calls'],8)
        self.assertEqual(metrics['B/utility_mixed_groups'],0)

    def test_high_utility_does_not_reward_failed_attempt(self):
        units=[dict(group='g',unit=str(i),replica=i,kind='selfplay',utility=10 if i==0 else 0,protocol=-.1 if i==0 else 0) for i in range(4)]
        rows=[dict(unit='0',kind='selfplay',valid=False,completion=dict(finish_reason='length'))]
        rows += [dict(unit=str(i),kind='selfplay',valid=True) for i in range(4)]
        assign_advantages(rows,units,'selfplay')
        self.assertEqual(rows[0]['advantage'],-.2)
        self.assertGreater(rows[1]['advantage'],0)
        self.assertEqual(rows[1]['protocol_advantage'],0)

    def test_nontruncated_invalid_and_legal_wrong_differ(self):
        rows=[];units=[]
        for kind in ('B','P'):
            for i in range(2):
                uid=f'{kind}{i}'
                units.append(dict(group=kind,unit=uid,replica=i,kind=kind,utility=0,protocol=0))
                rows.append(dict(unit=uid,kind=kind,score=dict(status='format_failure' if i==0 else 'ok')))
        assign_advantages(rows,units,'bp',.3)
        self.assertEqual([r['advantage'] for r in rows],[-.3,0,-.3,0])

    def test_infrastructure_failure_is_not_model_penalty(self):
        units=[dict(group='g',unit=str(i),replica=i,kind='selfplay',utility=None,protocol=0) for i in range(2)]
        rows=[dict(unit=str(i),kind='selfplay',valid=False,completion=dict(status='infrastructure_failure')) for i in range(2)]
        with self.assertRaisesRegex(ValueError,'Infrastructure'):
            assign_advantages(rows,units,'selfplay')

    def test_coefficient_rejects_nan_and_nonpositive(self):
        for value in (float('nan'),float('inf'),0,-.2):
            with self.assertRaises(ValueError):assign_advantages([],[],'bp',value)

    def test_resume_rejects_changed_protocol_contract(self):
        import json
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from training.social_mixed.run import validate_resume,data_manifest_sha256
        from training.social_mixed.core import PROTOCOL_VERSION
        with TemporaryDirectory() as tmp:
            root=Path(tmp);ckpt=root/'checkpoints/checkpoint-0';ckpt.mkdir(parents=True)
            (ckpt/'COMPLETE.json').write_text(json.dumps(dict(tp=2,world_size=2)))
            options=dict(arm='bp',seed=42,tokens_per_update=65536,gpu_profile='h100-96',protocol_coefficient=.2)
            record=dict(options=options,model='/base',data_manifest_sha256=data_manifest_sha256(),advantage_version=PROTOCOL_VERSION)
            (root/'experiment.json').write_text(json.dumps(record))
            validate_resume(ckpt,options,'/base')
            with self.assertRaisesRegex(ValueError,'protocol'):
                validate_resume(ckpt,dict(options,protocol_coefficient=.3),'/base')
            del record['advantage_version']
            (root/'experiment.json').write_text(json.dumps(record))
            with self.assertRaisesRegex(ValueError,'protocol'):validate_resume(ckpt,options,'/base')


if __name__=='__main__':unittest.main()
