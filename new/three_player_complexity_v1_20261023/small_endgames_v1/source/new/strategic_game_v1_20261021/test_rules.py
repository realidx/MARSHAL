import unittest

from training.b_sft.social_terminal_teacher import Investigate
from new.strategic_game_v1_20261021.rules import StrategicRules
from new.strategic_game_v1_20261021.pool import generate


class QueryContract(unittest.TestCase):
    def test_public_targets_excluded_but_all_hidden_targets_retained(self):
        raw,_=generate(31,players=2,goals=4,hidden=2)
        raw['game']['investigation_budget']=2
        rules=StrategicRules(raw);root=rules.initial();actor=rules.actor(root)
        actual={(a.player,a.goal) for a in rules.actions(root) if isinstance(a,Investigate)}
        expected={(p,g) for p,rows in rules.catalogues.items() if p!=actor
            for g in range(4) if len({r[g] for r in rows})>1}
        self.assertEqual(actual,expected)
        public=next((p,g) for p,rows in rules.catalogues.items() if p!=actor
                    for g in range(4) if len({r[g] for r in rows})==1)
        with self.assertRaises(ValueError):rules.step(root,Investigate(*public),realized_world=rules.worlds[0])

    def test_repeat_exclusion_does_not_depend_on_private_answer(self):
        raw,_=generate(32,players=2,goals=4,hidden=3)
        raw['game']['investigation_budget']=2
        rules=StrategicRules(raw);node=rules.initial();actor=rules.actor(node)
        queries=[a for a in rules.actions(node) if isinstance(a,Investigate)]
        # Find a turn with an unknown target if the opening player owns all unknowns.
        if not queries:
            node=rules.step(node,next(a for a in rules.actions(node) if a.to_dict().get('action')=='PASS'))
            actor=rules.actor(node);queries=[a for a in rules.actions(node) if isinstance(a,Investigate)]
        action=queries[0]
        children=[rules.step(node,action,realized_world=w) for w in (rules.worlds[0],rules.worlds[-1])]
        menus=[]
        for child in children:
            if child.state.is_terminal:raise AssertionError('Need another proposal for this test')
            while rules.actor(child)!=actor:
                child=rules.step(child,next(a for a in rules.actions(child) if a.to_dict().get('action')=='PASS'))
            menu=[a.to_dict() for a in rules.actions(child)]
            menus.append(menu)
            self.assertNotIn(action.to_dict(),menu)
            self.assertEqual(child.state.query_limit-child.state.query_used[actor],1)
        self.assertEqual(menus[0],menus[1])


if __name__=='__main__':unittest.main()
