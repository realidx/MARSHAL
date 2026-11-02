"""Rule/identity validation for the controlled game expansion and output types."""
from collections import Counter
from copy import deepcopy
import unittest

from .common import parents,stable
from .pool import variant
from .prepare_diagnostics import first_rr_queries
from new.strategic_game_v1_20261021.rules import StrategicRules


class Tests(unittest.TestCase):
    def test_all33_variants_keep_budget_prior_and_real_action_uses(self):
        for p in parents():
            if p['configuration']['players']!=3:continue
            before=deepcopy(p)
            for arm in ('H2','H3','A2H2'):
                raw,changes=variant(p,arm);rules=StrategicRules(raw)
                self.assertEqual(raw['background_prior'],p['raw']['background_prior'])
                self.assertEqual(raw['game']['round_robin'],p['raw']['game']['round_robin'])
                self.assertEqual(raw['game']['investigation_budget'],1)
                self.assertEqual(raw['game']['offer_budget'],1)
                self.assertEqual(len(rules.worlds),27 if arm=='H3' else 9)
                counts=Counter(a.player_id for g in rules.spec.goals for a in g.required_actions)
                self.assertEqual(set(counts),{0,1,2})
                hidden=changes['all_hidden_cells'];self.assertEqual(len({q for q,g in hidden}),len(hidden))
                self.assertEqual([g.binary for g in rules.spec.goals],[g['binary'] for g in p['raw']['game']['goals']])
                setup=first_rr_queries(raw);node=rules.initial()
                for a in setup:
                    choices=[x for x in rules.actions(node) if stable(x.to_dict())==stable(a)]
                    self.assertEqual(len(choices),1);node=rules._apply(node,choices[0])
                self.assertEqual(node.state.turn_index,3)
                self.assertTrue(all(not any(row) for row in node.state.snapshot_commitments()))
            self.assertEqual(p,before,'Source parent must not be mutated')

    def test_budget_charge_and_query_legality_unchanged(self):
        raw,_=variant(parents()[7],'A2H2');rules=StrategicRules(raw);node=rules.initial()
        actor=rules.actor(node);offer=next(a for a in rules.actions(node) if a.to_dict().get('action')=='OFFER')
        response=rules._apply(node,offer);self.assertEqual(response.state.offer_used[actor],1)
        reject=next(a for a in rules.actions(response) if a.to_dict().get('response')=='REJECT')
        after=rules._apply(response,reject);self.assertEqual(after.state.offer_used[actor],1)
        for p,rows in rules.catalogues.items():
            for g in range(len(rules.spec.goals)):
                if len({r[g] for r in rows})==1:
                    self.assertNotIn(dict(action='INVESTIGATE',player=p,goal=g),[a.to_dict() for a in rules.actions(node)])


if __name__=='__main__':unittest.main()
