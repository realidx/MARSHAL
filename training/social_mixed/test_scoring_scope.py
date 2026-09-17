import json
from copy import deepcopy
from pathlib import Path
import unittest
from training.social_mixed.core import DATA, ROOT, load_data
from training.social_mixed.scoring_scope import completion_mode, validate_rows
from training.b_sft.social_named_probe import request

class ScopeTests(unittest.TestCase):
    def test_every_active_split_and_request_excludes_mixed(self):
        manifest=json.loads((DATA/'manifest.json').read_text())
        self.assertEqual(manifest['allowed_completion_modes'],['binary','linear'])
        for name in ('bp_train','bp_validation','bp_test','selfplay_train','selfplay_validation','diagnostics'):
            rows=[json.loads(l) for l in (DATA/(name+'.jsonl')).read_text().splitlines()]
            validate_rows(rows,name)
            self.assertTrue(all(completion_mode(t) in ('binary','linear') for t in rows))
            if name.startswith('bp_'):
                requests=[json.loads(l) for l in (DATA/name.replace('bp_','requests_')).with_suffix('.jsonl').read_text().splitlines()]
                self.assertEqual([r['id'] for r in requests],[r['id'] for r in rows])
                for t,r in zip(rows,requests):
                    self.assertEqual(r['request'],request(t,'action_tools',t.get('name_variant',0)))

    def test_retained_labels_inputs_and_splits_unchanged(self):
        parent=ROOT/'examples/social_mixed/data_distribution_v2'
        for name in ('bp_train','bp_validation','bp_test','selfplay_train','selfplay_validation'):
            before=[json.loads(l) for l in (parent/(name+'.jsonl')).read_text().splitlines()]
            after=[json.loads(l) for l in (DATA/(name+'.jsonl')).read_text().splitlines()]
            self.assertEqual(after,[t for t in before if completion_mode(t)!='mixed'])

    def test_metadata_cannot_hide_mixed_game(self):
        row=deepcopy(load_data()['bp_train'][0])
        row['completion_mode']='binary'
        row['input']['game']['goals'][0]['binary']=True
        row['input']['game']['goals'][1]['binary']=False
        with self.assertRaisesRegex(ValueError,'Mixed completion'):
            validate_rows([row],'tampered')

if __name__=='__main__':unittest.main()
