import json
from pathlib import Path
import unittest
from training.social_mixed.audit_sp_incentives import audit
from training.social_mixed.weighted_rules import OutcomeRules

class WitnessTests(unittest.TestCase):
    def test_certificates_replay_in_native_rules(self):
        rows=[json.loads(l) for l in Path('examples/social_mixed/data_reasoning_v5_candidate/selfplay_train.jsonl').read_text().splitlines()]
        for reset in (rows[0],next(r for r in rows if r['players']==3)):
            result=audit(reset);rules=OutcomeRules(reset['raw'])
            self.assertEqual(result['baseline'],[0.]*reset['players'])
            for witness in result['certificates']:
                node=rules.initial()
                for event in witness['path']:
                    self.assertEqual(event['player'],rules.actor(node))
                    action=next(a for a in rules.actions(node) if a.to_dict()==event['action'])
                    node=rules.step(node,action,realized_world=reset['realized_world'])
                self.assertTrue(node.state.is_terminal)
                self.assertEqual(list(rules.terminal_payoffs(node,reset['realized_world'])),witness['utility'])

if __name__=='__main__':unittest.main()
