"""Native equilibrium regression; independent one-decision finite-action VOI."""
import json,unittest
from pathlib import Path
import numpy as np
from examples.strategic_slices.check_entry_information import restore
from training.strategic_slices.behavior_information import public_history_value, public_behavior_value
from training.strategic_slices.equilibrium import certify_policy

class NativeEntryInformationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        folder=Path(__file__).resolve().parents[2]/'examples/strategic_slices/fixtures'
        cls.fixture=json.loads((folder/'public_history_information.json').read_text())
        cls.tree=restore(cls.fixture,cls.fixture,folder/cls.fixture['reference_file'])
    def test_saved_profile_independently_certifies(self):
        checked=certify_policy(self.tree)
        self.assertIsNotNone(checked)
    def test_native_nonquery_signal_matches_independent_action_enumeration(self):
        f=self.fixture;t=self.tree
        result=public_history_value(t,ego=f['ego'],entries=f['entries'],k=1)
        values=t.evaluate();q=[];mass=[]
        for e in f['entries']:
            i=e['root_index'];m=np.array(e['world_masses']);mass.append(m.sum())
            q.append([float(m@values[ch][:,f['ego']]/m.sum()) for ch in t.entries[i].children])
        q=np.array(q);p=np.array(mass)/sum(mass)
        full=float(p@q.max(axis=1));blind=float((p@q).max())
        self.assertAlmostEqual(full,f['expected_full'])
        self.assertAlmostEqual(blind,f['expected_restricted'])
        self.assertAlmostEqual(full-blind,1/66)
        self.assertAlmostEqual(result['S'],full-blind)
        self.assertEqual(q.argmax(axis=1).tolist(),[1,6,6,6])
        for history in f['histories']:
            self.assertFalse(any(a.get('action')=='INVESTIGATE' for a in history))
        for e,best in zip(f['entries'],q.argmax(axis=1)):
            self.assertEqual(t.entries[e['root_index']].actions[best].to_dict()['action'],'OFFER')
    def test_unmasked_forest_agrees(self):
        f=self.fixture
        result=public_history_value(self.tree,ego=f['ego'],entries=f['entries'],k=1,hide_history=False)
        self.assertAlmostEqual(result['S'],0.)
    def test_single_root_future_channel_misses_the_entry_signal(self):
        f=self.fixture
        for e in f['entries']:
            result=public_behavior_value(self.tree,ego=f['ego'],root_index=e['root_index'],
                root_weights=e['world_masses'],k=1)
            self.assertAlmostEqual(result['S'],0.)

if __name__=='__main__':unittest.main()
